const PREFERENCES_KEY = 'ais-osmap-preferences';
const DEFAULT_TRACK_LIMIT = window.AIS_OSMAP_CONFIG?.defaultTrackLimit || 50;
const map = L.map('map').setView([41.65, 41.64], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

const markers = {};
const tracks = {};
let selectedMmsi = null;
let diagnosticsHitMmsis = new Set();
let markerLayer = L.markerClusterGroup({ disableClusteringAtZoom: 11 });
map.addLayer(markerLayer);

const controls = {
  showTracks: document.getElementById('toggle-tracks'),
  showClusters: document.getElementById('toggle-clusters'),
  trackLimit: document.getElementById('track-limit'),
  trackLimitValue: document.getElementById('track-limit-value'),
  filterVessels: document.getElementById('filter-vessels'),
  filterStations: document.getElementById('filter-stations'),
  filterAton: document.getElementById('filter-aton'),
  filterDiagnosticsHit: document.getElementById('filter-diagnostics-hit'),
  detailPanel: document.getElementById('detail-panel'),
  detailTitle: document.getElementById('detail-title'),
  detailSubtitle: document.getElementById('detail-subtitle'),
  detailContent: document.getElementById('detail-content'),
  detailClose: document.getElementById('detail-close'),
  diagnosticsPanel: document.getElementById('diagnostics-panel'),
  diagnosticsToggle: document.getElementById('diagnostics-toggle'),
  diagnosticsSummary: document.getElementById('diagnostics-summary'),
  diagnosticsList: document.getElementById('diagnostics-list'),
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
    filterVessels: controls.filterVessels.checked,
    filterStations: controls.filterStations.checked,
    filterAton: controls.filterAton.checked,
    filterDiagnosticsHit: controls.filterDiagnosticsHit.checked,
    diagnosticsCollapsed: controls.diagnosticsPanel.classList.contains('is-collapsed'),
  };
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
}

function applyPreferences() {
  const preferences = loadPreferences();
  controls.showTracks.checked = preferences.showTracks ?? true;
  controls.showClusters.checked = preferences.showClusters ?? true;
  controls.trackLimit.value = String(preferences.trackLimit ?? DEFAULT_TRACK_LIMIT);
  controls.trackLimitValue.textContent = controls.trackLimit.value;
  controls.filterVessels.checked = preferences.filterVessels ?? true;
  controls.filterStations.checked = preferences.filterStations ?? true;
  controls.filterAton.checked = preferences.filterAton ?? true;
  controls.filterDiagnosticsHit.checked = preferences.filterDiagnosticsHit ?? true;
  controls.diagnosticsPanel.classList.toggle('is-collapsed', preferences.diagnosticsCollapsed ?? false);
  controls.diagnosticsToggle.textContent = controls.diagnosticsPanel.classList.contains('is-collapsed') ? 'Show' : 'Hide';
}

function vesselKind(vessel) {
  if (vessel.is_aid_to_navigation) {
    return 'aton';
  }
  if (vessel.message_type === 4) {
    return 'station';
  }
  return 'vessel';
}

function passesFilters(vessel) {
  const kind = vesselKind(vessel);
  if (kind === 'vessel' && !controls.filterVessels.checked) {
    return false;
  }
  if (kind === 'station' && !controls.filterStations.checked) {
    return false;
  }
  if (kind === 'aton' && !controls.filterAton.checked) {
    return false;
  }
  if (diagnosticsHitMmsis.has(vessel.mmsi) && !controls.filterDiagnosticsHit.checked) {
    return false;
  }
  return true;
}

function markerClass(vessel) {
  if (vessel.is_aid_to_navigation) {
    return 'map-marker map-marker--aton';
  }
  if (vessel.message_type === 4) {
    return 'map-marker map-marker--station';
  }
  return 'map-marker map-marker--vessel';
}

function markerIcon(vessel) {
  return L.divIcon({
    className: '',
    html: `<div class="${markerClass(vessel)}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function popupHtml(vessel) {
  const kind = vessel.is_aid_to_navigation ? 'Aid to navigation' : (vessel.vessel_type_label || vessel.vessel_type || '?');
  return `
    <b>${vessel.type_icon || ''} ${vessel.name || 'Unknown vessel'}</b><br>
    MMSI: ${vessel.mmsi}<br>
    Type: ${kind}<br>
    Nav status: ${vessel.nav_status_text || vessel.status_text || '?'}<br>
    Position source: ${vessel.epfd_text || '?'}<br>
    Accuracy: ${vessel.accuracy === null || vessel.accuracy === undefined ? '?' : (vessel.accuracy ? 'High' : 'Low')}<br>
    RAIM: ${vessel.raim === null || vessel.raim === undefined ? '?' : (vessel.raim ? 'On' : 'Off')}<br>
    SOG: ${vessel.speed ?? '?'} kn<br>
    COG: ${vessel.course ?? '?'}&deg;<br>
    Heading: ${vessel.heading ?? '?'}&deg;<br>
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

  const kind = vessel.is_aid_to_navigation ? 'Aid to navigation' : (vessel.vessel_type_label || vessel.vessel_type);
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
      <li><strong>Type:</strong> ${formatValue(kind)}</li>
      <li><strong>Nav status:</strong> ${formatValue(vessel.nav_status_text || vessel.status_text)}</li>
      <li><strong>Message type:</strong> ${formatValue(vessel.message_type)}</li>
      <li><strong>Position source:</strong> ${formatValue(vessel.epfd_text)}</li>
      <li><strong>Accuracy:</strong> ${vessel.accuracy === null || vessel.accuracy === undefined ? '?' : (vessel.accuracy ? 'High' : 'Low')}</li>
      <li><strong>RAIM:</strong> ${vessel.raim === null || vessel.raim === undefined ? '?' : (vessel.raim ? 'On' : 'Off')}</li>
      <li><strong>Call sign:</strong> ${formatValue(vessel.callsign)}</li>
      <li><strong>IMO:</strong> ${formatValue(vessel.imo)}</li>
      <li><strong>Destination:</strong> ${formatValue(vessel.destination)}</li>
      <li><strong>Position:</strong> ${formatValue(vessel.lat)}, ${formatValue(vessel.lon)}</li>
    </ul>
  `;
}

function updateDiagnostics(data) {
  diagnosticsHitMmsis = new Set(data.messages.map(message => message.mmsi).filter(Boolean));
  controls.diagnosticsSummary.textContent = `${data.summary.total_messages} stored diagnostics, ${data.summary.invalid_coordinates} invalid coordinates, ${data.summary.stationary_messages} stationary reports`;
  if (!data.messages.length) {
    controls.diagnosticsList.innerHTML = '<p class="detail-empty">No recent diagnostics.</p>';
    return;
  }

  controls.diagnosticsList.innerHTML = data.messages.map(message => `
    <div class="diagnostics-item">
      <div class="diagnostics-reason">${message.reason}</div>
      <div>MMSI: ${message.mmsi ?? '?'} | Type: ${message.message_type ?? '?'}</div>
      <div>${message.raw_line ? message.raw_line.slice(0, 72) : 'No raw line stored'}</div>
    </div>
  `).join('');
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

  if (!shouldShow || vessel.is_aid_to_navigation || !passesFilters(vessel) || latlngs.length <= 1) {
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
  const [vesselsRes, diagnosticsRes] = await Promise.all([
    fetch(`/ships?track_limit=${trackLimit}`),
    fetch('/api/diagnostics?limit=8'),
  ]);
  const allVessels = await vesselsRes.json();
  const diagnostics = await diagnosticsRes.json();
  updateDiagnostics(diagnostics);
  const vessels = allVessels.filter(passesFilters);
  const visible = new Set();
  updateStats(vessels);

  for (const vessel of vessels) {
    visible.add(String(vessel.mmsi));

    if (!markers[vessel.mmsi]) {
      markers[vessel.mmsi] = L.marker([vessel.lat, vessel.lon], { icon: markerIcon(vessel) });
      markerLayer.addLayer(markers[vessel.mmsi]);
    } else {
      markers[vessel.mmsi].setLatLng([vessel.lat, vessel.lon]);
      markers[vessel.mmsi].setIcon(markerIcon(vessel));
    }

    bindMarker(markers[vessel.mmsi], vessel);
    syncTrack(vessel);

    if (selectedMmsi === vessel.mmsi) {
      renderDetailPanel(vessel);
    }
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
for (const filterControl of [controls.filterVessels, controls.filterStations, controls.filterAton, controls.filterDiagnosticsHit]) {
  filterControl.addEventListener('change', () => {
    savePreferences();
    refresh();
  });
}
controls.diagnosticsToggle.addEventListener('click', () => {
  controls.diagnosticsPanel.classList.toggle('is-collapsed');
  controls.diagnosticsToggle.textContent = controls.diagnosticsPanel.classList.contains('is-collapsed') ? 'Show' : 'Hide';
  savePreferences();
});
controls.detailClose.addEventListener('click', () => {
  selectedMmsi = null;
  renderDetailPanel(null);
});

renderDetailPanel(null);
refresh();
setInterval(refresh, 2000);
