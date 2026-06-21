import sys
import types

sys.modules.setdefault("flask", types.SimpleNamespace(
    Flask=lambda *_args, **_kwargs: types.SimpleNamespace(route=lambda *_a, **_k: (lambda func: func)),
    jsonify=lambda value: value,
    render_template_string=lambda value: value,
    request=types.SimpleNamespace(args=types.SimpleNamespace(get=lambda _key, default=None, type=None: default)),
))
sys.modules.setdefault("pyais", types.SimpleNamespace(decode=lambda *_args, **_kwargs: None))

import ais_map
from storage import AISStorage


class FakeMessage:
    def __init__(self, payload):
        self._payload = payload

    def asdict(self):
        return self._payload


def test_extract_static_fields_strips_values():
    fields = ais_map.extract_static_fields(
        {
            "shipname": " DEMO ",
            "callsign": " CALL ",
            "imo": 1234567,
            "destination": " BATUMI ",
            "ship_type": 60,
        }
    )

    assert fields == {
        "shipname": "DEMO",
        "callsign": "CALL",
        "imo": 1234567,
        "destination": "BATUMI",
        "ship_type": 60,
    }


def test_map_html_contains_controls_and_detail_panel():
    assert 'id="toggle-tracks"' in ais_map.HTML
    assert 'id="toggle-clusters"' in ais_map.HTML
    assert 'id="track-limit"' in ais_map.HTML
    assert 'id="detail-panel"' in ais_map.HTML
    assert 'leaflet.markercluster' in ais_map.HTML


def test_handle_nmea_updates_static_and_position(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)
    monkeypatch.setattr(
        ais_map,
        "decode",
        lambda *_args, **_kwargs: FakeMessage(
            {
                "mmsi": 123456789,
                "shipname": " DEMO ",
                "callsign": " SIGN ",
                "imo": 9990001,
                "destination": " POTI ",
                "ship_type": 52,
                "lat": 41.7,
                "lon": 41.6,
                "speed": 8.5,
                "course": 90,
                "heading": 88,
            }
        ),
    )

    ais_map.handle_nmea("!AIVDM,1,1,,A,stub,0*00")
    vessels = storage.get_recent_vessels(include_tracks=True)

    assert len(vessels) == 1
    assert vessels[0]["mmsi"] == 123456789
    assert vessels[0]["name"] == "DEMO"
    assert vessels[0]["callsign"] == "SIGN"
    assert vessels[0]["imo"] == 9990001
    assert vessels[0]["destination"] == "POTI"
    assert vessels[0]["vessel_type"] == 52
    assert len(vessels[0]["track"]) == 1
    assert vessels[0]["track_points"] == 1


def test_handle_nmea_ignores_non_ais(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)

    ais_map.handle_nmea("$GPGGA,ignore,this")

    assert storage.get_recent_vessels() == []
