FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIS_UDP_HOST=0.0.0.0 \
    AIS_UDP_PORT=10110 \
    AIS_WEB_HOST=0.0.0.0 \
    AIS_WEB_PORT=8080 \
    AIS_DB_PATH=/data/ais_data.sqlite3

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ais_map.py storage.py ./

VOLUME ["/data"]
EXPOSE 8080/udp 8080 10110/udp

CMD ["python", "ais_map.py"]
