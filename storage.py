import math
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path("ais_data.sqlite3")
DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_TRACK_POINT_LIMIT = 50


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
                    callsign TEXT,
                    imo INTEGER,
                    destination TEXT,
                    vessel_type INTEGER,
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
            self._ensure_column(conn, "vessel_static", "callsign", "TEXT")
            self._ensure_column(conn, "vessel_static", "imo", "INTEGER")
            self._ensure_column(conn, "vessel_static", "destination", "TEXT")
            self._ensure_column(conn, "vessel_static", "vessel_type", "INTEGER")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _thin_track(self, points: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
        if limit is None or limit <= 0 or len(points) <= limit:
            return points
        if limit == 1:
            return [points[-1]]

        step = (len(points) - 1) / (limit - 1)
        indices = [min(len(points) - 1, round(step * index)) for index in range(limit)]

        thinned = []
        seen_indices = set()
        for index in indices:
            if index not in seen_indices:
                thinned.append(points[index])
                seen_indices.add(index)

        if thinned[-1] is not points[-1]:
            thinned[-1] = points[-1]
        if thinned[0] is not points[0]:
            thinned[0] = points[0]
        return thinned

    def purge_expired(self, now: float | None = None) -> None:
        cutoff = (now or time.time()) - self.ttl_seconds
        with self._connect() as conn:
            conn.execute("DELETE FROM vessel_positions WHERE last_seen < ?", (cutoff,))
            conn.execute("DELETE FROM vessel_tracks WHERE seen_at < ?", (cutoff,))
            conn.execute(
                "DELETE FROM vessel_static WHERE updated_at < ? AND mmsi NOT IN (SELECT mmsi FROM vessel_positions)",
                (cutoff,),
            )

    def upsert_static(self, mmsi: int, fields: dict[str, Any], seen_at: float | None = None) -> None:
        timestamp = seen_at or time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vessel_static (
                    mmsi, shipname, callsign, imo, destination, vessel_type, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mmsi) DO UPDATE SET
                    shipname = COALESCE(excluded.shipname, vessel_static.shipname),
                    callsign = COALESCE(excluded.callsign, vessel_static.callsign),
                    imo = COALESCE(excluded.imo, vessel_static.imo),
                    destination = COALESCE(excluded.destination, vessel_static.destination),
                    vessel_type = COALESCE(excluded.vessel_type, vessel_static.vessel_type),
                    updated_at = excluded.updated_at
                """,
                (
                    mmsi,
                    fields.get("shipname"),
                    fields.get("callsign"),
                    fields.get("imo"),
                    fields.get("destination"),
                    fields.get("ship_type") or fields.get("vessel_type"),
                    timestamp,
                ),
            )

    def upsert_position(
        self,
        mmsi: int,
        lat: float,
        lon: float,
        speed: Any,
        course: Any,
        heading: Any,
        seen_at: float | None = None,
    ) -> None:
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

    def get_recent_vessels(
        self,
        now: float | None = None,
        include_tracks: bool = False,
        track_limit: int | None = DEFAULT_TRACK_POINT_LIMIT,
    ) -> list[dict[str, Any]]:
        current_time = now or time.time()
        cutoff = current_time - self.ttl_seconds
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.mmsi,
                    s.shipname,
                    s.callsign,
                    s.imo,
                    s.destination,
                    s.vessel_type,
                    p.lat,
                    p.lon,
                    p.speed,
                    p.course,
                    p.heading,
                    p.last_seen
                FROM vessel_positions p
                LEFT JOIN vessel_static s ON s.mmsi = p.mmsi
                WHERE p.last_seen >= ?
                ORDER BY p.last_seen DESC
                """,
                (cutoff,),
            ).fetchall()

            tracks_by_mmsi = {}
            if include_tracks:
                track_rows = conn.execute(
                    """
                    SELECT mmsi, lat, lon, speed, course, heading, seen_at
                    FROM vessel_tracks
                    WHERE seen_at >= ?
                    ORDER BY mmsi ASC, seen_at ASC
                    """,
                    (cutoff,),
                ).fetchall()
                for row in track_rows:
                    tracks_by_mmsi.setdefault(row["mmsi"], []).append(
                        {
                            "lat": row["lat"],
                            "lon": row["lon"],
                            "speed": row["speed"],
                            "course": row["course"],
                            "heading": row["heading"],
                            "seen_at": row["seen_at"],
                        }
                    )

        return [
            {
                "mmsi": row["mmsi"],
                "name": row["shipname"],
                "callsign": row["callsign"],
                "imo": row["imo"],
                "destination": row["destination"],
                "vessel_type": row["vessel_type"],
                "lat": row["lat"],
                "lon": row["lon"],
                "speed": row["speed"],
                "course": row["course"],
                "heading": row["heading"],
                "age": current_time - row["last_seen"],
                "track": self._thin_track(tracks_by_mmsi.get(row["mmsi"], []), track_limit) if include_tracks else None,
                "track_points": len(tracks_by_mmsi.get(row["mmsi"], [])) if include_tracks else None,
            }
            for row in rows
        ]

    def get_track(self, mmsi: int, now: float | None = None, limit: int | None = None) -> list[dict[str, Any]]:
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
        return self._thin_track([dict(row) for row in rows], limit)
