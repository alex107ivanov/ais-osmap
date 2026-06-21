# AIS OSMap

A tiny Python app that receives AIS NMEA over UDP from `rtl-ais`, decodes messages with `pyais`, stores recent vessel state in SQLite, and renders live positions on a Leaflet/OpenStreetMap view.

## Features
- UDP listener for `rtl-ais` output
- AIS decode via `pyais`
- Web map with live vessel markers and tracks
- SQLite-backed persistence for current state and recent history
- 24-hour TTL cleanup for stale vessel state and tracks
- Batched track delivery in the `/ships` response
- Server-side track thinning to keep payloads lighter
- Marker clustering for dense vessel areas
- Vessel detail panel with live stats and metadata
- Vessel type labels and simple category icons
- Saved UI preferences for track visibility, clustering, and track density
- `/api/health` and `/api/stats` endpoints for lightweight ops visibility
- Frontend split into `templates/` and `static/` assets for easier maintenance
- Basic test suite and GitHub Actions CI
- Simple `Makefile` for local setup and test commands
- Docker and Compose support for reproducible local runs

## Architecture
- `ais_map.py` runs the UDP listener, Flask web app, API endpoints, and AIS message handling.
- `storage.py` owns SQLite schema, upserts, TTL cleanup, track thinning, and track queries.
- `templates/index.html` contains the page structure.
- `static/app.css` and `static/app.js` contain the map UI styling and behavior.
- `tests/` covers storage behavior and parser/update flows.
- `Makefile` provides local setup and test shortcuts.
- `Dockerfile` and `docker-compose.yml` provide containerized local runtime.

## Static aids and lighthouses
AIS Aid-to-Navigation messages, including lighthouse-like stations, are now treated as stationary objects.
They still appear on the map at their reported position, but they do not append movement tracks.
This fixes the case where a static object looked like it had "jumped away" and only left a stale track behind.

## Requirements
- Python 3.11+
- An AIS source, for example `rtl-ais`

## Installation
```bash
make install-dev
```

Manual setup also works:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Running the app
### Local Python
```bash
make run
```

### Docker Compose
```bash
make docker-up
```

By default the app listens on:
- AIS UDP input: `127.0.0.1:10110` locally, `0.0.0.0:10110` in Docker
- Web UI: `http://127.0.0.1:8080` locally, `http://127.0.0.1:8080` on the host with Docker
- SQLite DB: `ais_data.sqlite3` locally, `./data/ais_data.sqlite3` via Docker volume

Example forwarding pattern for an AIS toolchain:
```bash
rtl_ais ... | socat - UDP:127.0.0.1:10110
```

If you run `rtl_ais` on the host while the app runs in Docker, send UDP to the host-mapped port `127.0.0.1:10110`.

## Configuration
Environment variables:
- `AIS_UDP_HOST`
- `AIS_UDP_PORT`
- `AIS_WEB_HOST`
- `AIS_WEB_PORT`
- `AIS_DB_PATH`
- `AIS_DATA_TTL_SECONDS`
- `AIS_TRACK_POINT_LIMIT`

## API
- `GET /ships` returns active vessels with thinned recent tracks
- `GET /ships/<mmsi>/track` returns recent track points for one vessel
- `GET /api/health` returns status, uptime, TTL, and DB path
- `GET /api/stats` returns active vessel count, total tracked points, max vessel age, and app uptime

## Persistence model
SQLite stores three kinds of data:
- `vessel_static`: vessel name and static metadata such as call sign, IMO, destination, and vessel type
- `vessel_positions`: latest known position per MMSI, including whether the object is an aid to navigation
- `vessel_tracks`: append-only recent movement history per MMSI

Data retention uses a TTL, defaulting to 24 hours. Expired rows are purged during normal ingest and read activity.

Track payloads are thinned server-side before they are returned to the browser. This keeps long-running sessions responsive while preserving the first and last known points.

## UI controls
The map overlay includes:
- a track visibility toggle
- a marker clustering toggle
- a slider for limiting how many recent points are drawn per vessel
- a vessel detail panel opened by clicking a marker
- a small live stats strip for active vessels and retained tracks

The app stores the main map toggles in `localStorage`, so your preferred viewing mode survives page reloads.

## Tests
```bash
make test
```
