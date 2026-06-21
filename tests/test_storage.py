from storage import AISStorage


def test_upsert_and_fetch_recent_vessels(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_static(
        123456789,
        {
            "shipname": "TEST VESSEL",
            "callsign": "CALL",
            "imo": 9876543,
            "destination": "BATUMI",
            "ship_type": 70,
            "status_text": "Under way using engine",
            "epfd": 3,
            "epfd_text": "Combined GPS/GLONASS",
        },
        seen_at=1000,
    )
    storage.upsert_position(
        123456789,
        41.1,
        42.2,
        12.3,
        180,
        175,
        seen_at=1000,
        nav_status=0,
        nav_status_text="Under way using engine",
        accuracy=True,
        raim=False,
        epfd=3,
        epfd_text="Combined GPS/GLONASS",
        message_type=1,
    )

    vessels = storage.get_recent_vessels(now=1010, include_tracks=True)

    assert len(vessels) == 1
    assert vessels[0]["mmsi"] == 123456789
    assert vessels[0]["name"] == "TEST VESSEL"
    assert vessels[0]["callsign"] == "CALL"
    assert vessels[0]["imo"] == 9876543
    assert vessels[0]["destination"] == "BATUMI"
    assert vessels[0]["vessel_type"] == 70
    assert vessels[0]["status_text"] == "Under way using engine"
    assert vessels[0]["epfd_text"] == "Combined GPS/GLONASS"
    assert vessels[0]["message_type"] == 1
    assert vessels[0]["accuracy"] is True
    assert vessels[0]["raim"] is False
    assert vessels[0]["is_aid_to_navigation"] is False
    assert vessels[0]["lat"] == 41.1
    assert vessels[0]["lon"] == 42.2
    assert vessels[0]["age"] == 10
    assert len(vessels[0]["track"]) == 1
    assert vessels[0]["track_points"] == 1


def test_record_and_fetch_diagnostics(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.record_diagnostic_message(
        reason="invalid_coordinates",
        raw_line="!AIVDM,1,1,,A,stub,0*00",
        payload={"mmsi": 2130200, "lat": 91.0, "lon": 181.0},
        mmsi=2130200,
        message_type=1,
        created_at=1000,
    )

    summary = storage.get_diagnostics_summary()
    messages = storage.get_recent_diagnostics(limit=5)

    assert summary["total_messages"] == 1
    assert summary["invalid_coordinates"] == 1
    assert messages[0]["mmsi"] == 2130200
    assert messages[0]["reason"] == "invalid_coordinates"
    assert messages[0]["payload"]["lat"] == 91.0


def test_purge_invalid_coordinates_removes_bad_rows(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_position(1, 41.0, 42.0, None, None, None, seen_at=1000)
    storage.upsert_position(2, 91.0, 181.0, None, None, None, seen_at=1000)

    cleanup = storage.purge_invalid_coordinates()
    vessels = storage.get_recent_vessels(now=1010, include_tracks=True)

    assert cleanup["vessel_positions"] == 1
    assert cleanup["vessel_tracks"] == 1
    assert [v["mmsi"] for v in vessels] == [1]


def test_static_aid_position_does_not_append_track(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_static(993692000, {"shipname": "LIGHTHOUSE", "vessel_type": 21, "aid_type": 1}, seen_at=1000)
    storage.upsert_position(993692000, 41.0, 42.0, 0, 0, 0, seen_at=1000, is_aid_to_navigation=True, append_track=False, message_type=21)

    vessels = storage.get_recent_vessels(now=1010, include_tracks=True)

    assert len(vessels) == 1
    assert vessels[0]["is_aid_to_navigation"] is True
    assert vessels[0]["message_type"] == 21
    assert vessels[0]["aid_type"] == 1
    assert vessels[0]["track_points"] == 0
    assert vessels[0]["track"] == []


def test_track_history_keeps_multiple_points(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_position(111000111, 41.0, 42.0, None, None, None, seen_at=1000)
    storage.upsert_position(111000111, 41.5, 42.5, None, None, None, seen_at=1010)

    track = storage.get_track(111000111, now=1020)

    assert len(track) == 2
    assert track[0]["lat"] == 41.0
    assert track[1]["lat"] == 41.5


def test_track_thinning_preserves_first_and_last_points(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    for offset in range(10):
        storage.upsert_position(555000555, 41.0 + offset, 42.0 + offset, None, None, None, seen_at=1000 + offset)

    track = storage.get_track(555000555, now=1020, limit=4)

    assert len(track) == 4
    assert track[0]["lat"] == 41.0
    assert track[-1]["lat"] == 50.0


def test_purge_expired_removes_old_rows(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_static(222000222, {"shipname": "OLD"}, seen_at=1000)
    storage.upsert_position(222000222, 40.0, 43.0, None, None, None, seen_at=1000)
    storage.upsert_position(333000333, 41.0, 44.0, None, None, None, seen_at=1100)

    storage.purge_expired(now=1070)
    vessels = storage.get_recent_vessels(now=1070)

    assert len(vessels) == 1
    assert vessels[0]["mmsi"] == 333000333
    assert storage.get_track(222000222, now=1070) == []
