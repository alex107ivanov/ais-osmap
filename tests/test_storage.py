from storage import AISStorage


def test_upsert_and_fetch_recent_vessels(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_static(123456789, "TEST VESSEL", seen_at=1000)
    storage.upsert_position(123456789, 41.1, 42.2, 12.3, 180, 175, seen_at=1000)

    vessels = storage.get_recent_vessels(now=1010)

    assert len(vessels) == 1
    assert vessels[0]["mmsi"] == 123456789
    assert vessels[0]["name"] == "TEST VESSEL"
    assert vessels[0]["lat"] == 41.1
    assert vessels[0]["lon"] == 42.2
    assert vessels[0]["age"] == 10


def test_track_history_keeps_multiple_points(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_position(111000111, 41.0, 42.0, None, None, None, seen_at=1000)
    storage.upsert_position(111000111, 41.5, 42.5, None, None, None, seen_at=1010)

    track = storage.get_track(111000111, now=1020)

    assert len(track) == 2
    assert track[0]["lat"] == 41.0
    assert track[1]["lat"] == 41.5


def test_purge_expired_removes_old_rows(tmp_path):
    storage = AISStorage(tmp_path / "test.sqlite3", ttl_seconds=60)
    storage.upsert_static(222000222, "OLD", seen_at=1000)
    storage.upsert_position(222000222, 40.0, 43.0, None, None, None, seen_at=1000)
    storage.upsert_position(333000333, 41.0, 44.0, None, None, None, seen_at=1100)

    storage.purge_expired(now=1070)
    vessels = storage.get_recent_vessels(now=1070)

    assert len(vessels) == 1
    assert vessels[0]["mmsi"] == 333000333
    assert storage.get_track(222000222, now=1070) == []
