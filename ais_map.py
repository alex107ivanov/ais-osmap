import os
import socket
import threading
import time
from flask import Flask, jsonify, render_template_string
from pyais import decode

from storage import AISStorage, DEFAULT_TTL_SECONDS

UDP_HOST = os.getenv("AIS_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("AIS_UDP_PORT", "10110"))
WEB_HOST = os.getenv("AIS_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("AIS_WEB_PORT", "8080"))
DATA_TTL_SECONDS = int(os.getenv("AIS_DATA_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
DB_PATH = os.getenv("AIS_DB_PATH", "ais_data.sqlite3")

fragments = {}
storage = AISStorage(DB_PATH, ttl_seconds=DATA_TTL_SECONDS)

app = Flask(__name__)

HTML = """
<!doctype html>
<html>
<head>
  <title>AIS Map</title>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
  <style>
    :root {
      --panel-bg: rgba(248, 246, 239, 0.92);
      --panel-border: rgba(31, 53, 70, 0.18);
      --panel-shadow: 0 16px 30px rgba(22, 34, 44, 0.18);
      --text-main: #163241;
      --text-muted: #5f6f79;
      --accent: #bf5b39;
      --track: #bf5b39;
      --track-muted: #dfab7b;
    }

    html, body, #map { height: 100%; margin: 0; }
    body { font-family: Georgia, "Times New Roman", serif; }

    .control-panel {
      position: absolute;
      top: 14px;
      left: 14px;
      z-index: 1000;
      width: min(290px, calc(100vw - 28px));
      padding: 14px 16px;
      border: 1px solid var(--panel-border);
      border-radius: 16px;
      background: var(--panel-bg);
      box-shadow: var(--panel-shadow);
      backdrop-filter: blur(8px);
    }

    .control-panel h1 {
      margin: 0 0 6px;
      font-size: 20px;
      line-height: 1.1;
      color: var(--text-main);
    }

    .control-panel p {
      margin: 0 0 12px;
      font-size: 13px;
      color: var(--text-muted);
    }

    .control-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 10px 0;
      color: var(--text-main);
      font-size: 14px;
    }

    .control-row input[type="range"] {
      flex: 1;
      accent-color: var(--accent);
    }

    .control-row output {
      min-width: 48px;
      text-align: right;
      color: var(--accent);
      font-weight: bold;
    }

    .control-row input[type="checkbox"] {
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }

    @media (max-width: 640px) {
      .control-panel {
        top: 10px;
        left: 10px;
        right: 10px;
        width: auto;
      }
    }
  </style>
</head>
<body>
<div class="control-panel">
  <h1>AIS OSMap</h1>
  <p>Live vessels, recent tracks, and lightweight local persistence.</p>
  <label class="control-row">
    <span>Show tracks</span>
    <input id="toggle-tracks" type="checkbox" checked>
  </label>
  <label class="control-row">
    <span>Track points</span>
    <input id="track-limit" type="range" min="2" max="200" step="1" value="50">
    <output id="track-limit-value">50</output>
  </label>
</div>
<div id="map"></div>
<script>
const map = L.map('map').setView([41.65, 41.64], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

const markers = {};
const tracks = {};
const controls = {
  showTracks: document.getElementById('toggle-tracks'),
  trackLimit: document.getElementById('track-limit'),
  trackLimitValue: document.getElementById('track-limit-value'),
};

function popupHtml(vessel) {
  return `
    <b>${vessel.name || "Unknown vessel"}</b><br>
    MMSI: ${vessel.mmsi}<br>
    Call sign: ${vessel.callsign || "?"}<br>
    IMO: ${vessel.imo ?? "?"}<br>
    Destination: ${vessel.destination || "?"}<br>
    Type: ${vessel.vessel_type ?? "?"}<br>
    SOG: ${vessel.speed ?? "?"} kn<br>
    COG: ${vessel.course ?? "?"}&deg;<br>
    Heading: ${vessel.heading ?? "?"}&deg;<br>
    Last seen: ${vessel.age.toFixed(0)} s ago
  `;
}

function getLimitedTrack(track) {
  const limit = Number(controls.trackLimit.value);
  controls.trackLimitValue.textContent = String(limit);
  return (track || []).slice(-limit);
}

function syncTrack(vessel) {
  const shouldShow = controls.showTracks.checked;
  const latlngs = getLimitedTrack(vessel.track).map(point => [point.lat, point.lon]);

  if (!shouldShow || latlngs.length <= 1) {
    if (tracks[vessel.mmsi]) {
      map.removeLayer(tracks[vessel.mmsi]);
      delete tracks[vessel.mmsi];
    }
    return;
  }

  if (tracks[vessel.mmsi]) {
    tracks[vessel.mmsi].setLatLngs(latlngs);
    return;
  }

  tracks[vessel.mmsi] = L.polyline(latlngs, {
    weight: 2,
    opacity: 0.7,
    color: '#bf5b39',
  }).addTo(map);
}

async function refresh() {
  const res = await fetch('/ships');
  const vessels = await res.json();
  const visible = new Set();

  for (const vessel of vessels) {
    visible.add(String(vessel.mmsi));

    if (!markers[vessel.mmsi]) {
      markers[vessel.mmsi] = L.marker([vessel.lat, vessel.lon]).addTo(map);
    } else {
      markers[vessel.mmsi].setLatLng([vessel.lat, vessel.lon]);
    }

    markers[vessel.mmsi].bindPopup(popupHtml(vessel));
    syncTrack(vessel);
  }

  for (const mmsi of Object.keys(markers)) {
    if (!visible.has(mmsi)) {
      map.removeLayer(markers[mmsi]);
      delete markers[mmsi];
      if (tracks[mmsi]) {
        map.removeLayer(tracks[mmsi]);
        delete tracks[mmsi];
      }
    }
  }
}

controls.showTracks.addEventListener('change', refresh);
controls.trackLimit.addEventListener('input', refresh);
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/ships")
def get_ships():
    storage.purge_expired()
    return jsonify(storage.get_recent_vessels(include_tracks=True))


@app.route("/ships/<int:mmsi>/track")
def get_track(mmsi: int):
    storage.purge_expired()
    return jsonify(storage.get_track(mmsi))


def extract_static_fields(data: dict) -> dict:
    static_fields = {}
    for field in ("shipname", "callsign", "imo", "destination", "ship_type", "vessel_type"):
        value = data.get(field)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            static_fields[field] = value
    return static_fields


def handle_nmea(line: str):
    line = line.strip()
    if not line.startswith(("!AIVDM", "!AIVDO")):
        return

    fields = line.split(",")
    total = int(fields[1])
    number = int(fields[2])
    seq = fields[3] or "single"
    channel = fields[4]
    key = (seq, channel)

    try:
        if total == 1:
            msg = decode(line.encode())
        else:
            fragments.setdefault(key, {})[number] = line.encode()
            if len(fragments[key]) < total:
                return

            parts = [fragments[key][i] for i in range(1, total + 1)]
            del fragments[key]
            msg = decode(*parts)

        data = msg.asdict()
        mmsi = data.get("mmsi")
        if not mmsi:
            return

        seen_at = time.time()
        static_fields = extract_static_fields(data)
        if static_fields:
            storage.upsert_static(mmsi, static_fields, seen_at=seen_at)

        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None and lon is not None:
            storage.upsert_position(
                mmsi,
                lat,
                lon,
                data.get("speed"),
                data.get("course"),
                data.get("heading"),
                seen_at=seen_at,
            )

        storage.purge_expired(now=seen_at)
    except Exception as exc:
        print("Decode error:", exc, line)


def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_HOST, UDP_PORT))
    print(f"Listening for AIS NMEA on udp://{UDP_HOST}:{UDP_PORT}")

    while True:
        packet, _ = sock.recvfrom(4096)
        for raw_line in packet.splitlines():
            handle_nmea(raw_line.decode(errors="ignore"))


if __name__ == "__main__":
    threading.Thread(target=udp_listener, daemon=True).start()
    print(f"Open http://{WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT)
