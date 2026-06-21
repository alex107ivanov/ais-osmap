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
    html, body, #map { height: 100%; margin: 0; }
  </style>
</head>
<body>
<div id="map"></div>
<script>
const map = L.map('map').setView([41.65, 41.64], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

const markers = {};
const tracks = {};

function popupHtml(vessel) {
  return `
    <b>${vessel.name || "Unknown vessel"}</b><br>
    MMSI: ${vessel.mmsi}<br>
    SOG: ${vessel.speed ?? "?"} kn<br>
    COG: ${vessel.course ?? "?"}&deg;<br>
    Heading: ${vessel.heading ?? "?"}&deg;<br>
    Last seen: ${vessel.age.toFixed(0)} s ago
  `;
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

    const trackRes = await fetch(`/ships/${vessel.mmsi}/track`);
    const track = await trackRes.json();
    const latlngs = track.map(point => [point.lat, point.lon]);

    if (tracks[vessel.mmsi]) {
      tracks[vessel.mmsi].setLatLngs(latlngs);
    } else if (latlngs.length > 1) {
      tracks[vessel.mmsi] = L.polyline(latlngs, {weight: 2, opacity: 0.6}).addTo(map);
    }
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

setInterval(refresh, 2000);
refresh();
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
    return jsonify(storage.get_recent_vessels())


@app.route("/ships/<int:mmsi>/track")
def get_track(mmsi: int):
    storage.purge_expired()
    return jsonify(storage.get_track(mmsi))


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

        if "shipname" in data and data["shipname"]:
            storage.upsert_static(mmsi, data["shipname"].strip(), seen_at=seen_at)

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
