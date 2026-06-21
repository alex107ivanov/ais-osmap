# AIS OSMap

A tiny Python app that receives AIS NMEA over UDP from `rtl-ais`, decodes messages with `pyais`, stores recent vessel state in SQLite, and renders live positions on a Leaflet/OpenStreetMap view.

## Features
- UDP listener for `rtl-ais` output
- AIS decode via `pyais`
- Web map with live vessel markers
- SQLite-backed persistence for current state and recent history
- 24-hour TTL cleanup for stale vessel state and tracks
- Track storage for moving objects
- Basic test suite and GitHub Actions CI

## Architecture
- `ais_map.py` runs the UDP listener and Flask web app.
- `storage.py` owns SQLite schema, upserts, TTL cleanup, and track queries.
- `tests/` covers storage behavior and key parser/update flows.

## Requirements
- Python 3.11+
- An AIS source, for example `rtl-ais`

## Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Running the app
Start `rtl-ais` so it forwards NMEA lines to UDP, then run:

```bash
python ais_map.py
```

By default the app listens on:
- AIS UDP input: `127.0.0.1:10110`
- Web UI: `http://127.0.0.1:8080`

Example forwarding pattern for an AIS toolchain:
```bash
rtl_ais ... | socat - UDP:127.0.0.1:10110
```

## Persistence model
SQLite stores three kinds of data:
- `vessel_static`: vessel name and static metadata snapshots
- `vessel_positions`: latest known position per MMSI
- `vessel_tracks`: append-only recent movement history per MMSI

Data retention uses a TTL, defaulting to 24 hours. Expired rows are purged during normal ingest and read activity.

## Tests
```bash
pytest -q
```

## Future ideas
- Draw track polylines on the map
- Add configurable retention and bind addresses via environment variables
- Store more static AIS fields such as callsign and destination
