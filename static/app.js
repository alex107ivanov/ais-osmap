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
  toggleDiagnosticsPanel: document.getElementById('toggle-diagnostics-panel'),
  toggleRawPanel: document.getElementById('toggle-raw-panel'),
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
  diagnosticsDrag: document.getElementById('diagnostics-drag'),
  diagnosticsToggle: document.getElementById('diagnostics-toggle'),
  diagnosticsSummary: document.getElementById('diagnostics-summary'),
  diagnosticsList: document.getElementById('diagnostics-list'),
  rawPanel: document.getElementById('raw-panel'),
  rawDrag: document.getElementById('raw-drag'),
  rawToggle: document.getElementById('raw-toggle'),
  rawSummary: document.getElementById('raw-summary'),
  rawTimeline: document.getElementById('raw-timeline'),
  rawList: document.getElementById('raw-list'),
  rawFilterMmsi: document.getElementById('raw-filter-mmsi'),
  rawFilterType: document.getElementById('raw-filter-type'),
  rawRefresh: document.getElementById('raw-refresh'),
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
    showDiagnosticsPanel: controls.toggleDiagnosticsPanel.checked,
    showRawPanel: controls.toggleRawPanel.checked,
    filterVessels: controls.filterVessels.checked,
    filterStations: controls.filterStations.checked,
    filterAton: controls.filterAton.checked,
    filterDiagnosticsHit: controls.filterDiagnosticsHit.checked,
    diagnosticsCollapsed: controls.diagnosticsPanel.classList.contains('is-collapsed'),
    rawCollapsed: controls.rawPanel.classList.contains('is-collapsed'),
    rawFilterMmsi: controls.rawFilterMmsi.value,
    rawFilterType: controls.rawFilterType.value,
    diagnosticsPanelPos: {
      left: controls.diagnosticsPanel.style.left,
      top: controls.diagnosticsPanel.style.top,
      right: controls.diagnosticsPanel.style.right,
      bottom: controls.diagnosticsPanel.style.bottom,
    },
    rawPanelPos: {
      left: controls.rawPanel.style.left,
      top: controls.rawPanel.style.top,
      right: controls.rawPanel.style.right,
      bottom: controls.rawPanel.style.bottom,
    },
  };
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
}

function applyPanelPosition(element, position) {
  if (!position) {
    return;
  }
  for (const key of ['left', 'top', 'right', 'bottom']) {
    if (position[key]) {
      element.style[key] = position[key];
    }
  }
}

function applyPreferences() {
  const preferences = loadPreferences();
  controls.showTracks.checked = preferences.showTracks ?? true;
  controls.showClusters.checked = preferences.showClusters ?? true;
  controls.trackLimit.value = String(preferences.trackLimit ?? DEFAULT_TRACK_LIMIT);
  controls.trackLimitValue.textContent = controls.trackLimit.value;
  controls.toggleDiagnosticsPanel.checked = preferences.showDiagnosticsPanel ?? false;
  controls.toggleRawPanel.checked = preferences.showRawPanel ?? false;
  controls.filterVessels.checked = preferences.filterVessels ?? true;
  controls.filterStations.checked = preferences.filterStations ?? true;
  controls.filterAton.checked = preferences.filterAton ?? true;
  controls.filterDiagnosticsHit.checked = preferences.filterDiagnosticsHit ?? true;
  controls.rawFilterMmsi.value = preferences.rawFilterMmsi ?? '';
  controls.rawFilterType.value = preferences.rawFilterType ?? '';
  controls.diagnosticsPanel.classList.toggle('is-collapsed', preferences.diagnosticsCollapsed ?? false);
  controls.rawPanel.classList.toggle('is-collapsed', preferences.rawCollapsed ?? false);
  controls.diagnosticsPanel.classList.toggle('is-hidden', !(preferences.showDiagnosticsPanel ?? false));
  controls.rawPanel.classList.toggle('is-hidden', !(preferences.showRawPanel ?? false));
  applyPanelPosition(controls.diagnosticsPanel, preferences.diagnosticsPanelPos);
  applyPanelPosition(controls.rawPanel, preferences.rawPanelPos);
  controls.diagnosticsToggle.textContent = controls.diagnosticsPanel.classList.contains('is-collapsed') ? 'Show' : 'Hide';
  controls.rawToggle.textContent = controls.rawPanel.classList.contains('is-collapsed') ? 'Show' : 'Hide';
}

function makePanelDraggable(panel, handle) {
  let dragging = false;
  let offsetX = 0;
  let offsetY = 0;

  handle.addEventListener('mousedown', event => {
    dragging = true;
    const rect = panel.getBoundingClientRect();
    offsetX = event.clientX - rect.left;
    offsetY = event.clientY - rect.top;
    panel.style.left = `${rect.left}px`;
    panel.style.top = `${rect.top}px`;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
  });

  window.addEventListener('mousemove', event => {
    if (!dragging) {
      return;
    }
    panel.style.left = `${event.clientX - offsetX}px`;
    panel.style.top = `${event.clientY - offsetY}px`;
  });

  window.addEventListener('mouseup', () => {
    if (!dragging) {
      return;
    }
    dragging = false;
    savePreferences();
  });
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
    Message: ${vessel.message_type_label || vessel.message_type || '?'}<br>
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
      <li><strong>Message:</strong> ${formatValue(vessel.message_type_label || vessel.message_type)}</li>
      <li><strong>Nav status:</strong> ${formatValue(vessel.nav_status_text || vessel.status_text)}</li>
      <li><strong>Position source:</strong> ${formatValue(vessel.epfd_text)}</li>
      <li><strong>Report time:</strong> ${formatValue(vessel.report_time_label)}</li>
      <li><strong>Radio:</strong> ${formatValue(vessel.radio)}</li>
      <li><strong>Draught:</strong> ${formatValue(vessel.draught, ' m')}</li>
      <li><strong>ETA:</strong> ${formatValue(vessel.eta_label)}</li>
      <li><strong>Dimensions:</strong> ${formatValue(vessel.dimensions_label)}</li>
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

function renderRawTimeline(timeline) {
  if (!timeline.length) {
    controls.rawTimeline.innerHTML = '<p class="detail-empty">No raw message timeline yet.</p>';
    return;
  }
  controls.rawTimeline.innerHTML = timeline.map(item => `
    <div class="raw-timeline-item">
      <div><strong>MMSI:</strong> ${item.mmsi}</div>
      <div>${item.message_types.map(typeItem => `<span class="raw-type-chip">${typeItem.label || typeItem.message_type} x${typeItem.count}</span>`).join('')}</div>
    </div>
  `).join('');
}

function type20DetailsHtml(details) {
  const entries = Object.entries(details || {});
  if (!entries.length) {
    return '';
  }
  return `<div>${entries.map(([key, value]) => `<span class="raw-type-chip">${key}: ${value}</span>`).join('')}</div>`;
}

function updateRawPanel(data) {
  controls.rawSummary.textContent = `${data.summary.total_messages} raw messages in ${Math.round(data.summary.retention_seconds / 3600)}h retention, ${data.summary.unique_mmsi} MMSIs`;
  renderRawTimeline(data.timeline || []);
  if (!data.messages.length) {
    controls.rawList.innerHTML = '<p class="detail-empty">No raw messages for this filter.</p>';
    return;
  }
  controls.rawList.innerHTML = data.messages.map(message => `
    <div class="raw-item">
      <div><strong>MMSI:</strong> ${message.mmsi ?? '?'} | <strong>${message.message_type_label || message.message_type || '?'}</strong></div>
      <div>${message.raw_line ? message.raw_line.slice(0, 96) : 'No raw line stored'}</div>
      ${message.message_type === 20 ? type20DetailsHtml(message.type20_details) : ''}
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

function rawQueryParams() {
  const params = new URLSearchParams();
  params.set('limit', '12');
  if (controls.rawFilterMmsi.value.trim()) {
    params.set('mmsi', controls.rawFilterMmsi.value.trim());
  }
  if (controls.rawFilterType.value.trim()) {
    params.set('message_type', controls.rawFilterType.value.trim());
  }
  return params.toString();
}

async function refresh() {
  const trackLimit = Number(controls.trackLimit.value);
  const [vesselsRes, diagnosticsRes, rawRes] = await Promise.all([
    fetch(`/ships?track_limit=${trackLimit}`),
    fetch('/api/diagnostics?limit=8'),
    fetch(`/api/raw-messages?${rawQueryParams()}`),
  ]);
  const allVessels = await vesselsRes.json();
  const diagnostics = await diagnosticsRes.json();
  const rawData = await rawRes.json();
  updateDiagnostics(diagnostics);
  updateRawPanel(rawData);
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
makePanelDraggable(controls.diagnosticsPanel, controls.diagnosticsDrag);
makePanelDraggable(controls.rawPanel, controls.rawDrag);
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
controls.toggleDiagnosticsPanel.addEventListener('change', () => {
  controls.diagnosticsPanel.classList.toggle('is-hidden', !controls.toggleDiagnosticsPanel.checked);
  savePreferences();
});
controls.toggleRawPanel.addEventListener('change', () => {
  controls.rawPanel.classList.toggle('is-hidden', !controls.toggleRawPanel.checked);
  savePreferences();
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
controls.rawToggle.addEventListener('click', () => {
  controls.rawPanel.classList.toggle('is-collapsed');
  controls.rawToggle.textContent = controls.rawPanel.classList.contains('is-collapsed') ? 'Show' : 'Hide';
  savePreferences();
});
controls.rawRefresh.addEventListener('click', () => {
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
