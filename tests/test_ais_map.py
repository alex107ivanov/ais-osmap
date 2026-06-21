import sys
import types

sys.modules.setdefault("flask", types.SimpleNamespace(
    Flask=lambda *_args, **_kwargs: types.SimpleNamespace(route=lambda *_a, **_k: (lambda func: func)),
    jsonify=lambda value: value,
    render_template=lambda template, **context: {"template": template, **context},
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
            "status_text": " Under way using engine ",
            "epfd_text": " Combined GPS/GLONASS ",
        }
    )

    assert fields == {
        "shipname": "DEMO",
        "callsign": "CALL",
        "imo": 1234567,
        "destination": "BATUMI",
        "ship_type": 60,
        "status_text": "Under way using engine",
        "epfd_text": "Combined GPS/GLONASS",
    }


def test_vessel_type_label_and_icon_mapping():
    assert ais_map.get_vessel_type_label(70) == "Cargo"
    assert ais_map.get_vessel_type_label(71) == "Cargo"
    assert ais_map.get_vessel_type_label(21) == "Aid to navigation"
    assert ais_map.get_vessel_type_icon("Cargo") == "📦"
    assert ais_map.get_vessel_type_icon("Aid to navigation") == "🗼"
    assert ais_map.get_vessel_type_icon(None) == ""


def test_enrich_vessel_adds_type_metadata():
    vessel = ais_map.enrich_vessel({"mmsi": 1, "vessel_type": 52, "is_aid_to_navigation": False})

    assert vessel["vessel_type_label"] == "Tug"
    assert vessel["type_icon"] == "🪢"


def test_aid_to_navigation_detection():
    assert ais_map.is_aid_to_navigation({"msg_type": 21}) is True
    assert ais_map.is_aid_to_navigation({"aid_type": 5}) is True
    assert ais_map.is_aid_to_navigation({"vessel_type": 21}) is True
    assert ais_map.is_aid_to_navigation({"shiptype": 21}) is True
    assert ais_map.is_aid_to_navigation({"msg_type": 1, "vessel_type": 70}) is False


def test_trackable_position_filters_stationary_objects():
    assert ais_map.is_trackable_position({"msg_type": 1, "vessel_type": 70}) is True
    assert ais_map.is_trackable_position({"msg_type": 21, "aid_type": 1}) is False
    assert ais_map.is_trackable_position({"msg_type": 4}) is False


def test_coordinate_validation_rejects_impossible_values():
    assert ais_map.is_valid_coordinate(41.65, 41.64) is True
    assert ais_map.is_valid_coordinate(181.0, 91.0) is False
    assert ais_map.is_valid_coordinate(2528.0, 2499.7) is False
    assert ais_map.is_valid_coordinate(None, 41.64) is False


def test_index_uses_template_context():
    result = ais_map.index()
    assert result["template"] == "index.html"
    assert result["default_track_limit"] == ais_map.TRACK_POINT_LIMIT


def test_handle_nmea_records_raw_message(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600, raw_retention_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)
    monkeypatch.setattr(
        ais_map,
        "decode",
        lambda *_args, **_kwargs: FakeMessage(
            {
                "mmsi": 123456789,
                "msg_type": 1,
                "lat": 41.7,
                "lon": 41.6,
            }
        ),
    )

    ais_map.handle_nmea("!AIVDM,1,1,,A,stub,0*00")
    raw_messages = storage.get_recent_raw_messages(limit=5)

    assert raw_messages[0]["mmsi"] == 123456789
    assert raw_messages[0]["message_type"] == 1
    assert raw_messages[0]["raw_line"] == "!AIVDM,1,1,,A,stub,0*00"


def test_handle_nmea_updates_static_and_position(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)
    monkeypatch.setattr(
        ais_map,
        "decode",
        lambda *_args, **_kwargs: FakeMessage(
            {
                "mmsi": 123456789,
                "msg_type": 1,
                "shipname": " DEMO ",
                "callsign": " SIGN ",
                "imo": 9990001,
                "destination": " POTI ",
                "ship_type": 52,
                "status": 0,
                "status_text": "Under way using engine",
                "accuracy": True,
                "raim": False,
                "epfd": 3,
                "epfd_text": "Combined GPS/GLONASS",
                "lat": 41.7,
                "lon": 41.6,
                "speed": 8.5,
                "course": 90,
                "heading": 88,
            }
        ),
    )

    ais_map.handle_nmea("!AIVDM,1,1,,A,stub,0*00")
    vessels = [ais_map.enrich_vessel(vessel) for vessel in storage.get_recent_vessels(include_tracks=True)]

    assert len(vessels) == 1
    assert vessels[0]["mmsi"] == 123456789
    assert vessels[0]["name"] == "DEMO"
    assert vessels[0]["callsign"] == "SIGN"
    assert vessels[0]["imo"] == 9990001
    assert vessels[0]["destination"] == "POTI"
    assert vessels[0]["vessel_type"] == 52
    assert vessels[0]["status_text"] == "Under way using engine"
    assert vessels[0]["epfd_text"] == "Combined GPS/GLONASS"
    assert vessels[0]["message_type"] == 1
    assert vessels[0]["accuracy"] is True
    assert vessels[0]["raim"] is False
    assert vessels[0]["vessel_type_label"] == "Tug"
    assert vessels[0]["type_icon"] == "🪢"
    assert vessels[0]["is_aid_to_navigation"] is False
    assert len(vessels[0]["track"]) == 1
    assert vessels[0]["track_points"] == 1


def test_handle_nmea_records_invalid_coordinate_diagnostic(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)
    monkeypatch.setattr(
        ais_map,
        "decode",
        lambda *_args, **_kwargs: FakeMessage(
            {
                "mmsi": 2130200,
                "msg_type": 1,
                "lat": 91.0,
                "lon": 181.0,
            }
        ),
    )

    ais_map.handle_nmea("!AIVDM,1,1,,A,stub,0*00")
    diagnostics = storage.get_recent_diagnostics(limit=5)

    assert diagnostics[0]["reason"] == "invalid_coordinates"
    assert diagnostics[0]["mmsi"] == 2130200


def test_handle_nmea_keeps_aid_to_navigation_static(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)
    monkeypatch.setattr(
        ais_map,
        "decode",
        lambda *_args, **_kwargs: FakeMessage(
            {
                "mmsi": 993692000,
                "msg_type": 21,
                "shipname": " LIGHTHOUSE ",
                "aid_type": 1,
                "epfd": 3,
                "epfd_text": "Combined GPS/GLONASS",
                "lat": 41.65,
                "lon": 41.64,
                "speed": 0,
                "course": 0,
                "heading": 0,
                "raim": True,
            }
        ),
    )

    ais_map.handle_nmea("!AIVDM,1,1,,A,stub,0*00")
    vessels = [ais_map.enrich_vessel(vessel) for vessel in storage.get_recent_vessels(include_tracks=True)]
    diagnostics = storage.get_recent_diagnostics(limit=5)

    assert len(vessels) == 1
    assert vessels[0]["is_aid_to_navigation"] is True
    assert vessels[0]["vessel_type"] == 21
    assert vessels[0]["vessel_type_label"] == "Aid to navigation"
    assert vessels[0]["type_icon"] == "🗼"
    assert vessels[0]["message_type"] == 21
    assert vessels[0]["epfd_text"] == "Combined GPS/GLONASS"
    assert vessels[0]["raim"] is True
    assert vessels[0]["track_points"] == 0
    assert vessels[0]["track"] == []
    assert diagnostics[0]["reason"] == "stationary_position"


def test_handle_nmea_normalizes_shiptype_field(monkeypatch, tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=3600)
    monkeypatch.setattr(ais_map, "storage", storage)
    monkeypatch.setattr(
        ais_map,
        "decode",
        lambda *_args, **_kwargs: FakeMessage(
            {
                "mmsi": 2130200,
                "msg_type": 5,
                "shipname": " VTS BATUMI ",
                "shiptype": 0,
                "epfd_text": "Undefined",
            }
        ),
    )

    ais_map.handle_nmea("!AIVDM,1,1,,A,stub,0*00")
    vessels = storage.get_recent_vessels(include_tracks=True)

    assert vessels == []


def test_static_assets_include_filters_diagnostics_and_raw_panel():
    app_js = open('static/app.js', 'r', encoding='utf-8').read()
    template = open('templates/index.html', 'r', encoding='utf-8').read()

    assert 'filter-vessels' in template
    assert 'filter-stations' in template
    assert 'filter-aton' in template
    assert 'filter-diagnostics-hit' in template
    assert 'diagnostics-toggle' in template
    assert 'raw-panel' in template
    assert 'api/raw-messages' in app_js
    assert 'passesFilters' in app_js
