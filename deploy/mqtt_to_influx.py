"""Subscribe to the CSI metrics MQTT topic and write each record to InfluxDB.

Record shape: {"presence": bool, "bpm": float|null, "confidence": float, "timestamp": float}
Written as measurement `csi` with fields presence(int), bpm(float), confidence(float).
"""
from __future__ import annotations

import argparse
import json


def main(argv=None) -> int:
    import paho.mqtt.client as mqtt
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--broker", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--topic", default="csi/metrics")
    p.add_argument("--influx", default="http://localhost:8086")
    p.add_argument("--token", default="csi-sensor-dev-token")
    p.add_argument("--org", default="csi")
    p.add_argument("--bucket", default="metrics")
    args = p.parse_args(argv)

    influx = InfluxDBClient(url=args.influx, token=args.token, org=args.org)
    write_api = influx.write_api(write_options=SYNCHRONOUS)

    def on_message(_c, _u, msg):
        try:
            r = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        pt = (
            Point("csi")
            .field("presence", int(bool(r.get("presence"))))
            .field("confidence", float(r.get("confidence") or 0.0))
        )
        if r.get("bpm") is not None:
            pt = pt.field("bpm", float(r["bpm"]))
        ts = r.get("timestamp")
        if ts:
            pt = pt.time(int(ts * 1e9), WritePrecision.NS)
        write_api.write(bucket=args.bucket, record=pt)

    c = mqtt.Client()
    c.on_message = on_message
    c.connect(args.broker, args.port, 60)
    c.subscribe(args.topic)
    print(f"bridging {args.broker}:{args.port}/{args.topic} -> {args.influx} ({args.bucket})")
    c.loop_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
