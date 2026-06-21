import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path("ais_data.sqlite3")
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class AISStorage:
    def __init__(self, db_path: str | Path = DB_PATH, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.db_path = str(db_path)
        self.ttl_seconds = ttl_seconds
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vessel_static (
                    mmsi INTEGER PRIMARY KEY,
                    shipname TEXT,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vessel_positions (
                    mmsi INTEGER PRIMARY KEY,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    speed REAL,
                    course REAL,
                    heading REAL,
                    last_seen REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vessel_tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mmsi INTEGER NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    speed REAL,
                    course REAL,
                    heading REAL,
                    seen_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_vessel_tracks_mmsi_seen_at
                    ON vessel_tracks (mmsi, seen_at);
                """
            )

    def purge_expired(self, now: float | None = None) -> None:
        cutoff = (now or time.time()) - self.ttl_seconds
        with self._connect() as conn:
            conn.execute("DELETE FROM vessel_positions WHERE last_seen < ?", (cutoff,))
            conn.execute("DELETE FROM vessel_tracks WHERE seen_at < ?", (cutoff,))
            conn.execute(
                "DELETE FROM vessel_static WHERE updated_at < ? AND mmsi NOT IN (SELECT mmsi FROM vessel_positions)",
                (cutoff,),
            )

    def upsert_static(self, mmsi: int, shipname: str, seen_at: float | None = None) -> None:
        timestamp = seen_at or time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vessel_static (mmsi, shipname, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(mmsi) DO UPDATE SET
                    shipname = excluded.shipname,
                    updated_at = excluded.updated_at
                """,
                (mmsi, shipname, timestamp),
            )

    def upsert_position(self, mmsi: int, lat: float, lon: float, speed: Any, course: Any, heading: Any, seen_at: float | None = None) -> None:
        timestamp = seen_at or time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vessel_positions (mmsi, lat, lon, speed, course, heading, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mmsi) DO UPDATE SET
                    lat = excluded.lat,
                    lon = excluded.lon,
                    speed = excluded.speed,
                    course = excluded.course,
                    heading = excluded.heading,
                    last_seen = excluded.last_seen
                """,
                (mmsi, lat, lon, speed, course, heading, timestamp),
            )
            conn.execute(
                """
                INSERT INTO vessel_tracks (mmsi, lat, lon, speed, course, heading, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mmsi, lat, lon, speed, course, heading, timestamp),
            )

    def get_recent_vessels(self, now: float | None = None) -> list[dict[str, Any]]:
        current_time = now or time.time()
        cutoff = current_time - self.ttl_seconds
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.mmsi, s.shipname, p.lat, p.lon, p.speed, p.course, p.heading, p.last_seen
                FROM vessel_positions p
                LEFT JOIN vessel_static s ON s.mmsi = p.mmsi
                WHERE p.last_seen >= ?
                ORDER BY p.last_seen DESC
                """,
                (cutoff,),
            ).fetchall()
        return [
            {
                "mmsi": row["mmsi"],
                "name": row["shipname"],
                "lat": row["lat"],
                "lon": row["lon"],
                "speed": row["speed"],
                "course": row["course"],
                "heading": row["heading"],
                "age": current_time - row["last_seen"],
            }
            for row in rows
        ]

    def get_track(self, mmsi: int, now: float | None = None) -> list[dict[str, Any]]:
        cutoff = (now or time.time()) - self.ttl_seconds
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT lat, lon, speed, course, heading, seen_at
                FROM vessel_tracks
                WHERE mmsi = ? AND seen_at >= ?
                ORDER BY seen_at ASC
                """,
                (mmsi, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]
