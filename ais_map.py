import os
import socket
import threading
import time
from flask import Flask, jsonify, render_template_string, request
from pyais import decode

from storage import AISStorage, DEFAULT_TTL_SECONDS, DEFAULT_TRACK_POINT_LIMIT

UDP_HOST = os.getenv("AIS_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("AIS_UDP_PORT", "10110"))
WEB_HOST = os.getenv("AIS_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("AIS_WEB_PORT", "8080"))
DATA_TTL_SECONDS = int(os.getenv("AIS_DATA_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
DB_PATH = os.getenv("AIS_DB_PATH", "ais_data.sqlite3")
TRACK_POINT_LIMIT = int(os.getenv("AIS_TRACK_POINT_LIMIT", str(DEFAULT_TRACK_POINT_LIMIT)))

fragments = {}
storage = AISStorage(DB_PATH, ttl_seconds=DATA_TTL_SECONDS)
app_started_at = time.time()

app = Flask(__name__)

VESSEL_TYPE_LABELS = {
    30: "Fishing",
    31: "Towing",
    32: "Towing long/wide",
    33: "Dredging",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    50: "Pilot vessel",
    51: "Search and rescue",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution",
    55: "Law enforcement",
    58: "Medical transport",
    60: "Passenger",
    70: "Cargo",
    80: "Tanker",
}

VESSEL_TYPE_ICONS = {
    "Fishing": "🎣",
    "Cargo": "📦",
    "Passenger": "🧭",
    "Tanker": "🛢",
    "Tug": "🪢",
    "Pleasure craft": "⛵",
    "Sailing": "⛵",
    "Military ops": "🛡",
}

HTML = """
<!doctype html>
<html>
<head>
  <title>AIS Map</title>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
  <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <style>
    :root {
      --panel-bg: rgba(248, 246, 239, 0.94);
      --panel-border: rgba(31, 53, 70, 0.18);
      --panel-shadow: 0 16px 30px rgba(22, 34, 44, 0.18);
      --text-main: #163241;
      --text-muted: #5f6f79;
      --accent: #bf5b39;
      --accent-deep: #8d3f25;
      --track: #bf5b39;
      --surface-strong: rgba(255, 252, 247, 0.96);
    }

    html, body, #map { height: 100%; margin: 0; }
    body { font-family: Georgia, "Times New Roman", serif; }

    .control-panel,
    .detail-panel,
    .stats-strip {
      position: absolute;
      z-index: 1000;
      border: 1px solid var(--panel-border);
      border-radius: 16px;
      background: var(--panel-bg);
      box-shadow: var(--panel-shadow);
      backdrop-filter: blur(8px);
    }

    .control-panel {
      top: 14px;
      left: 14px;
      width: min(290px, calc(100vw - 28px));
      padding: 14px 16px;
    }

    .detail-panel {
      top: 14px;
      right: 14px;
      width: min(340px, calc(100vw - 28px));
      padding: 16px;
      display: none;
      background: var(--surface-strong);
    }

    .stats-strip {
      left: 14px;
      bottom: 14px;
      display: flex;
      gap: 10px;
      padding: 10px 12px;
    }

    .stats-chip {
      min-width: 72px;
    }

    .stats-chip-label {
      display: block;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-muted);
    }

    .stats-chip-value {
      display: block;
      margin-top: 3px;
      font-size: 18px;
      color: var(--text-main);
    }

    .detail-panel.is-visible {
      display: block;
    }

    .control-panel h1,
    .detail-panel h2 {
      margin: 0 0 6px;
      line-height: 1.1;
      color: var(--text-main);
    }

    .control-panel h1 { font-size: 20px; }
    .detail-panel h2 { font-size: 22px; }

    .control-panel p,
    .detail-subtitle,
    .detail-empty {
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

    .detail-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px 14px;
      margin-bottom: 14px;
    }

    .detail-stat {
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(191, 91, 57, 0.08);
    }

    .detail-stat-label {
      display: block;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-muted);
    }

    .detail-stat-value {
      display: block;
      margin-top: 4px;
      font-size: 17px;
      color: var(--text-main);
    }

    .detail-meta {
      margin: 0;
      padding: 0;
      list-style: none;
      color: var(--text-main);
      font-size: 14px;
    }

    .detail-meta li {
      padding: 8px 0;
      border-top: 1px solid rgba(31, 53, 70, 0.08);
    }

    .detail-close {
      position: absolute;
      top: 10px;
      right: 10px;
      border: 0;
      background: transparent;
      color: var(--accent-deep);
      font-size: 22px;
      cursor: pointer;
    }

    .marker-cluster-small,
    .marker-cluster-medium,
    .marker-cluster-large {
      background: rgba(191, 91, 57, 0.18);
    }

    .marker-cluster-small div,
    .marker-cluster-medium div,
    .marker-cluster-large div {
      background: rgba(191, 91, 57, 0.86);
      color: white;
      font-family: Georgia, "Times New Roman", serif;
    }

    @media (max-width: 900px) {
      .detail-panel {
        top: auto;
        right: 10px;
        bottom: 72px;
      }

      .stats-strip {
        left: 10px;
        right: 10px;
        width: auto;
        justify-content: space-between;
      }
    }

    @media (max-width: 640px) {
      .control-panel {
        top: 10px;
        left: 10px;
        right: 10px;
        width: auto;
      }

      .detail-panel {
        left: 10px;
        right: 10px;
        width: auto;
      }

      .stats-strip {
        gap: 8px;
      }

      .stats-chip-value {
        font-size: 16px;
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
    <span>Cluster markers</span>
    <input id="toggle-clusters" type="checkbox" checked>
  </label>
  <label class="control-row">
    <span>Track points</span>
    <input id="track-limit" type="range" min="2" max="200" step="1" value="50">
    <output id="track-limit-value">50</output>
  </label>
</div>
<div id="detail-panel" class="detail-panel">
  <button id="detail-close" class="detail-close" type="button" aria-label="Close details">&times;</button>
  <h2 id="detail-title">No vessel selected</h2>
  <p id="detail-subtitle" class="detail-subtitle">Click a marker to inspect live vessel details.</p>
  <div id="detail-content">
    <p class="detail-empty">Waiting for a vessel selection.</p>
  </div>
</div>
<div class="stats-strip">
  <div class="stats-chip">
    <span class="stats-chip-label">Active</span>
    <span id="stats-active" class="stats-chip-value">0</span>
  </div>
  <div class="stats-chip">
    <span class="stats-chip-label">Tracks</span>
    <span id="stats-tracks" class="stats-chip-value">0</span>
  </div>
  <div class="stats-chip">
    <span class="stats-chip-label">Age</span>
    <span id="stats-age" class="stats-chip-value">0s</span>
  </div>
</div>
<div id="map"></div>
<script>
const PREFERENCES_KEY = 'ais-osmap-preferences';
const map = L.map('map').setView([41.65, 41.64], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

const markers = {};
const tracks = {};
let selectedMmsi = null;
let activeVessels = [];
let markerLayer = L.markerClusterGroup({ disableClusteringAtZoom: 11 });
map.addLayer(markerLayer);

const controls = {
  showTracks: document.getElementById('toggle-tracks'),
  showClusters: document.getElementById('toggle-clusters'),
  trackLimit: document.getElementById('track-limit'),
  trackLimitValue: document.getElementById('track-limit-value'),
  detailPanel: document.getElementById('detail-panel'),
  detailTitle: document.getElementById('detail-title'),
  detailSubtitle: document.getElementById('detail-subtitle'),
  detailContent: document.getElementById('detail-content'),
  detailClose: document.getElementById('detail-close'),
  statsActive: document.getElementById('stats-active'),
  statsTracks: document.getElementById('stats-tracks'),
  statsAge: document.getElementById('stats-age'),
};

function loadPreferences() {
  try {
    return JSON.parse(localStorage.getItem(PREFERENCES_KEY) || '{}');
  } catch (_error) {
    return {};
  }
}

function savePreferences() {
  const preferences = {
    showTracks: controls.showTracks.checked,
    showClusters: controls.showClusters.checked,
    trackLimit: Number(controls.trackLimit.value),
  };
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
}

function applyPreferences() {
  const preferences = loadPreferences();
  controls.showTracks.checked = preferences.showTracks ?? true;
  controls.showClusters.checked = preferences.showClusters ?? true;
  controls.trackLimit.value = String(preferences.trackLimit ?? 50);
  controls.trackLimitValue.textContent = controls.trackLimit.value;
}

function popupHtml(vessel) {
  return `
    <b>${vessel.type_icon || ''} ${vessel.name || "Unknown vessel"}</b><br>
    MMSI: ${vessel.mmsi}<br>
    Type: ${vessel.vessel_type_label || vessel.vessel_type || "?"}<br>
    Call sign: ${vessel.callsign || "?"}<br>
    IMO: ${vessel.imo ?? "?"}<br>
    Destination: ${vessel.destination || "?"}<br>
    SOG: ${vessel.speed ?? "?"} kn<br>
    COG: ${vessel.course ?? "?"}&deg;<br>
    Heading: ${vessel.heading ?? "?"}&deg;<br>
    Last seen: ${vessel.age.toFixed(0)} s ago
  `;
}

function formatValue(value, suffix = '') {
  if (value === null || value === undefined || value === '') {
    return '?';
  }
  return `${value}${suffix}`;
}

function renderDetailPanel(vessel) {
  if (!vessel) {
    controls.detailPanel.classList.remove('is-visible');
    controls.detailTitle.textContent = 'No vessel selected';
    controls.detailSubtitle.textContent = 'Click a marker to inspect live vessel details.';
    controls.detailContent.innerHTML = '<p class="detail-empty">Waiting for a vessel selection.</p>';
    return;
  }

  controls.detailPanel.classList.add('is-visible');
  controls.detailTitle.textContent = `${vessel.type_icon || ''} ${vessel.name || `Vessel ${vessel.mmsi}`}`.trim();
  controls.detailSubtitle.textContent = `MMSI ${vessel.mmsi} - ${formatValue(vessel.track_points)} stored track points`;
  controls.detailContent.innerHTML = `
    <div class="detail-grid">
      <div class="detail-stat">
        <span class="detail-stat-label">Speed</span>
        <span class="detail-stat-value">${formatValue(vessel.speed, ' kn')}</span>
      </div>
      <div class="detail-stat">
        <span class="detail-stat-label">Course</span>
        <span class="detail-stat-value">${formatValue(vessel.course, '&deg;')}</span>
      </div>
      <div class="detail-stat">
        <span class="detail-stat-label">Heading</span>
        <span class="detail-stat-value">${formatValue(vessel.heading, '&deg;')}</span>
      </div>
      <div class="detail-stat">
        <span class="detail-stat-label">Age</span>
        <span class="detail-stat-value">${formatValue(vessel.age.toFixed(0), ' s')}</span>
      </div>
    </div>
    <ul class="detail-meta">
      <li><strong>Type:</strong> ${formatValue(vessel.vessel_type_label || vessel.vessel_type)}</li>
      <li><strong>Call sign:</strong> ${formatValue(vessel.callsign)}</li>
      <li><strong>IMO:</strong> ${formatValue(vessel.imo)}</li>
      <li><strong>Destination:</strong> ${formatValue(vessel.destination)}</li>
      <li><strong>Position:</strong> ${formatValue(vessel.lat)}, ${formatValue(vessel.lon)}</li>
    </ul>
  `;
}

function updateStats(vessels) {
  const activeCount = vessels.length;
  const totalTracks = vessels.reduce((sum, vessel) => sum + (vessel.track_points || 0), 0);
  const maxAge = vessels.reduce((max, vessel) => Math.max(max, vessel.age || 0), 0);
  controls.statsActive.textContent = String(activeCount);
  controls.statsTracks.textContent = String(totalTracks);
  controls.statsAge.textContent = `${Math.round(maxAge)}s`;
}

function getLimitedTrack(track) {
  const limit = Number(controls.trackLimit.value);
  controls.trackLimitValue.textContent = String(limit);
  return (track || []).slice(-limit);
}

function rebuildMarkerLayer() {
  if (map.hasLayer(markerLayer)) {
    map.removeLayer(markerLayer);
  }

  markerLayer = controls.showClusters.checked
    ? L.markerClusterGroup({ disableClusteringAtZoom: 11 })
    : L.layerGroup();

  for (const marker of Object.values(markers)) {
    markerLayer.addLayer(marker);
  }

  map.addLayer(markerLayer);
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

function bindMarker(marker, vessel) {
  marker.bindPopup(popupHtml(vessel));
  marker.off('click');
  marker.on('click', () => {
    selectedMmsi = vessel.mmsi;
    renderDetailPanel(vessel);
  });
}

async function refresh() {
  const trackLimit = Number(controls.trackLimit.value);
  const res = await fetch(`/ships?track_limit=${trackLimit}`);
  const vessels = await res.json();
  const visible = new Set();
  activeVessels = vessels;
  updateStats(vessels);

  for (const vessel of vessels) {
    visible.add(String(vessel.mmsi));

    if (!markers[vessel.mmsi]) {
      markers[vessel.mmsi] = L.marker([vessel.lat, vessel.lon]);
      markerLayer.addLayer(markers[vessel.mmsi]);
    } else {
      markers[vessel.mmsi].setLatLng([vessel.lat, vessel.lon]);
    }

    bindMarker(markers[vessel.mmsi], vessel);
    syncTrack(vessel);
  }

  for (const mmsi of Object.keys(markers)) {
    if (!visible.has(mmsi)) {
      markerLayer.removeLayer(markers[mmsi]);
      delete markers[mmsi];
      if (tracks[mmsi]) {
        map.removeLayer(tracks[mmsi]);
        delete tracks[mmsi];
      }
      if (selectedMmsi !== null && String(selectedMmsi) === mmsi) {
        selectedMmsi = null;
        renderDetailPanel(null);
      }
    }
  }

  if (selectedMmsi !== null) {
    renderDetailPanel(activeVessels.find(vessel => vessel.mmsi === selectedMmsi) || null);
  }
}

applyPreferences();
rebuildMarkerLayer();
controls.showTracks.addEventListener('change', () => {
  savePreferences();
  refresh();
});
controls.showClusters.addEventListener('change', () => {
  savePreferences();
  rebuildMarkerLayer();
  refresh();
});
controls.trackLimit.addEventListener('input', () => {
  controls.trackLimitValue.textContent = controls.trackLimit.value;
  savePreferences();
  refresh();
});
controls.detailClose.addEventListener('click', () => {
  selectedMmsi = null;
  renderDetailPanel(null);
});

renderDetailPanel(null);
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


def get_vessel_type_label(vessel_type: int | None) -> str | None:
    if vessel_type is None:
        return None
    if vessel_type in VESSEL_TYPE_LABELS:
        return VESSEL_TYPE_LABELS[vessel_type]
    major_class = (vessel_type // 10) * 10
    return VESSEL_TYPE_LABELS.get(major_class, f"AIS type {vessel_type}")


def get_vessel_type_icon(vessel_type_label: str | None) -> str:
    if not vessel_type_label:
        return ""
    return VESSEL_TYPE_ICONS.get(vessel_type_label, "🚢")


def enrich_vessel(vessel: dict) -> dict:
    vessel_type_label = get_vessel_type_label(vessel.get("vessel_type"))
    return {
        **vessel,
        "vessel_type_label": vessel_type_label,
        "type_icon": get_vessel_type_icon(vessel_type_label),
    }


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/ships")
def get_ships():
    storage.purge_expired()
    track_limit = request.args.get("track_limit", default=TRACK_POINT_LIMIT, type=int)
    vessels = storage.get_recent_vessels(include_tracks=True, track_limit=track_limit)
    return jsonify([enrich_vessel(vessel) for vessel in vessels])


@app.route("/ships/<int:mmsi>/track")
def get_track(mmsi: int):
    storage.purge_expired()
    track_limit = request.args.get("limit", default=None, type=int)
    return jsonify(storage.get_track(mmsi, limit=track_limit))


@app.route("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "uptime_seconds": round(time.time() - app_started_at, 3),
            "db_path": DB_PATH,
            "ttl_seconds": DATA_TTL_SECONDS,
        }
    )


@app.route("/api/stats")
def stats():
    storage.purge_expired()
    vessels = storage.get_recent_vessels(include_tracks=True, track_limit=TRACK_POINT_LIMIT)
    return jsonify(
        {
            "active_vessels": len(vessels),
            "tracked_points": sum(vessel.get("track_points") or 0 for vessel in vessels),
            "max_age_seconds": round(max((vessel.get("age") or 0) for vessel in vessels), 3) if vessels else 0,
            "uptime_seconds": round(time.time() - app_started_at, 3),
        }
    )


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
