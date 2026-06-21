import os
import socket
import threading
import time
from flask import Flask, jsonify, render_template, request
from pyais import decode

from storage import AISStorage, DEFAULT_TTL_SECONDS, DEFAULT_TRACK_POINT_LIMIT

UDP_HOST = os.getenv("AIS_UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("AIS_UDP_PORT", "10110"))
WEB_HOST = os.getenv("AIS_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("AIS_WEB_PORT", "8080"))
DATA_TTL_SECONDS = int(os.getenv("AIS_DATA_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
DB_PATH = os.getenv("AIS_DB_PATH", "ais_data.sqlite3")
TRACK_POINT_LIMIT = int(os.getenv("AIS_TRACK_POINT_LIMIT", str(DEFAULT_TRACK_POINT_LIMIT)))

fragments = {}
storage = AISStorage(DB_PATH, ttl_seconds=DATA_TTL_SECONDS)
startup_cleanup = storage.purge_invalid_coordinates()
app_started_at = time.time()

app = Flask(__name__)

VESSEL_TYPE_LABELS = {
    21: "Aid to navigation",
    30: "Fishing",
    31: "Towing",
    32: "Towing long/wide",
    33: "Dredging",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    50: "Pilot vessel",
    51: "Search and rescue",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution",
    55: "Law enforcement",
    58: "Medical transport",
    60: "Passenger",
    70: "Cargo",
    80: "Tanker",
}

VESSEL_TYPE_ICONS = {
    "Aid to navigation": "🗼",
    "Fishing": "🎣",
    "Cargo": "📦",
    "Passenger": "🧭",
    "Tanker": "🛢",
    "Tug": "🪢",
    "Pleasure craft": "⛵",
    "Sailing": "⛵",
    "Military ops": "🛡",
}

AID_TO_NAVIGATION_MESSAGE_TYPES = {21}
STATIONARY_MESSAGE_TYPES = {4, 21}


def get_vessel_type_label(vessel_type: int | None) -> str | None:
    if vessel_type is None:
        return None
    if vessel_type in VESSEL_TYPE_LABELS:
        return VESSEL_TYPE_LABELS[vessel_type]
    major_class = (vessel_type // 10) * 10
    return VESSEL_TYPE_LABELS.get(major_class, f"AIS type {vessel_type}")


def get_vessel_type_icon(vessel_type_label: str | None) -> str:
    if not vessel_type_label:
        return ""
    return VESSEL_TYPE_ICONS.get(vessel_type_label, "🚢")


def is_aid_to_navigation(data: dict) -> bool:
    vessel_type = data.get("vessel_type") or data.get("ship_type") or data.get("shiptype")
    msg_type = data.get("msg_type") or data.get("type")
    aid_type = data.get("aid_type")
    return msg_type in AID_TO_NAVIGATION_MESSAGE_TYPES or vessel_type == 21 or aid_type is not None


def is_trackable_position(data: dict) -> bool:
    msg_type = data.get("msg_type") or data.get("type")
    if msg_type in STATIONARY_MESSAGE_TYPES:
        return False
    if is_aid_to_navigation(data):
        return False
    return True


def is_valid_coordinate(lat: float | int | None, lon: float | int | None) -> bool:
    if lat is None or lon is None:
        return False
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except (TypeError, ValueError):
        return False
    return -90.0 <= lat_value <= 90.0 and -180.0 <= lon_value <= 180.0


def enrich_vessel(vessel: dict) -> dict:
    vessel_type_label = get_vessel_type_label(vessel.get("vessel_type"))
    aid_flag = bool(vessel.get("is_aid_to_navigation"))
    if aid_flag:
        vessel_type_label = "Aid to navigation"
    return {
        **vessel,
        "vessel_type_label": vessel_type_label,
        "type_icon": get_vessel_type_icon(vessel_type_label),
        "is_aid_to_navigation": aid_flag,
    }


@app.route("/")
def index():
    return render_template("index.html", default_track_limit=TRACK_POINT_LIMIT)


@app.route("/ships")
def get_ships():
    storage.purge_expired()
    track_limit = request.args.get("track_limit", default=TRACK_POINT_LIMIT, type=int)
    vessels = storage.get_recent_vessels(include_tracks=True, track_limit=track_limit)
    return jsonify([enrich_vessel(vessel) for vessel in vessels])


@app.route("/ships/<int:mmsi>/track")
def get_track(mmsi: int):
    storage.purge_expired()
    track_limit = request.args.get("limit", default=None, type=int)
    return jsonify(storage.get_track(mmsi, limit=track_limit))


@app.route("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "uptime_seconds": round(time.time() - app_started_at, 3),
            "db_path": DB_PATH,
            "ttl_seconds": DATA_TTL_SECONDS,
            "startup_cleanup": startup_cleanup,
        }
    )


@app.route("/api/stats")
def stats():
    storage.purge_expired()
    vessels = storage.get_recent_vessels(include_tracks=True, track_limit=TRACK_POINT_LIMIT)
    return jsonify(
        {
            "active_vessels": len(vessels),
            "tracked_points": sum(vessel.get("track_points") or 0 for vessel in vessels),
            "max_age_seconds": round(max((vessel.get("age") or 0) for vessel in vessels), 3) if vessels else 0,
            "aid_to_navigation_count": sum(1 for vessel in vessels if vessel.get("is_aid_to_navigation")),
            "base_station_like_count": sum(1 for vessel in vessels if vessel.get("message_type") == 4),
            "uptime_seconds": round(time.time() - app_started_at, 3),
        }
    )


def extract_static_fields(data: dict) -> dict:
    static_fields = {}
    for field in (
        "shipname",
        "callsign",
        "imo",
        "destination",
        "ship_type",
        "shiptype",
        "vessel_type",
        "status_text",
        "epfd",
        "epfd_text",
        "aid_type",
    ):
        value = data.get(field)
        normalized_field = "ship_type" if field == "shiptype" else field
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            static_fields[normalized_field] = value
    return static_fields


def handle_nmea(line: str):
    line = line.strip()
    if not line.startswith(("!AIVDM", "!AIVDO")):
        return

    fields = line.split(",")
    total = int(fields[1])
    number = int(fields[2])
    seq = fields[3] or "single"
    channel = fields[4]
    key = (seq, channel)

    try:
        if total == 1:
            msg = decode(line.encode())
        else:
            fragments.setdefault(key, {})[number] = line.encode()
            if len(fragments[key]) < total:
                return

            parts = [fragments[key][i] for i in range(1, total + 1)]
            del fragments[key]
            msg = decode(*parts)

        data = msg.asdict()
        mmsi = data.get("mmsi")
        if not mmsi:
            return

        seen_at = time.time()
        static_fields = extract_static_fields(data)
        if static_fields:
            if is_aid_to_navigation(data):
                static_fields["vessel_type"] = 21
            storage.upsert_static(mmsi, static_fields, seen_at=seen_at)

        lat = data.get("lat")
        lon = data.get("lon")
        if is_valid_coordinate(lat, lon):
            common_kwargs = {
                "nav_status": data.get("status"),
                "nav_status_text": data.get("status_text"),
                "accuracy": data.get("accuracy"),
                "raim": data.get("raim"),
                "epfd": data.get("epfd"),
                "epfd_text": data.get("epfd_text"),
                "message_type": data.get("msg_type") or data.get("type"),
            }
            if is_trackable_position(data):
                storage.upsert_position(
                    mmsi,
                    lat,
                    lon,
                    data.get("speed"),
                    data.get("course"),
                    data.get("heading"),
                    seen_at=seen_at,
                    is_aid_to_navigation=False,
                    **common_kwargs,
                )
            else:
                storage.upsert_position(
                    mmsi,
                    lat,
                    lon,
                    data.get("speed"),
                    data.get("course"),
                    data.get("heading"),
                    seen_at=seen_at,
                    is_aid_to_navigation=is_aid_to_navigation(data),
                    append_track=False,
                    **common_kwargs,
                )

        storage.purge_expired(now=seen_at)
    except Exception as exc:
        print("Decode error:", exc, line)


def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_HOST, UDP_PORT))
    print(f"Listening for AIS NMEA on udp://{UDP_HOST}:{UDP_PORT}")

    while True:
        packet, _ = sock.recvfrom(4096)
        for raw_line in packet.splitlines():
            handle_nmea(raw_line.decode(errors="ignore"))


if __name__ == "__main__":
    threading.Thread(target=udp_listener, daemon=True).start()
    print(f"Open http://{WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT)
