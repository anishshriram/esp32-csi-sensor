FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt influxdb-client
COPY deploy/mqtt_to_influx.py deploy/__init__.py deploy/
CMD ["python", "-m", "deploy.mqtt_to_influx"]
