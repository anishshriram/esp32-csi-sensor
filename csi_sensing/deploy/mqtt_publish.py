"""Publish CSI metric records to an MQTT broker (Mosquitto).

Payload: {"presence": bool, "bpm": float|null, "confidence": float, "timestamp": float}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional


class Publisher:
    def __init__(self, broker: str, topic: str = "csi/metrics", port: int = 1883,
                 client_id: str = "csi-sensor"):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:  # pragma: no cover
            sys.exit("paho-mqtt not installed: pip install paho-mqtt")
        self.topic = topic
        self._c = mqtt.Client(client_id=client_id)
        self._c.connect(broker, port, keepalive=60)
        self._c.loop_start()

    def publish(self, record: dict) -> None:
        self._c.publish(self.topic, json.dumps(record), qos=0, retain=True)

    def close(self) -> None:
        self._c.loop_stop()
        self._c.disconnect()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--broker", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--topic", default="csi/metrics")
    p.add_argument("--stdin", action="store_true",
                   help="read newline-delimited JSON metric records from stdin and forward")
    p.add_argument("--test", action="store_true", help="publish one synthetic record and exit")
    args = p.parse_args(argv)

    pub = Publisher(args.broker, args.topic, args.port)
    try:
        if args.test:
            pub.publish({"presence": True, "bpm": 15.2, "confidence": 0.9, "timestamp": time.time()})
            print("published test record")
        elif args.stdin:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    pub.publish(json.loads(line))
        else:
            p.error("nothing to do: pass --stdin or --test")
    finally:
        time.sleep(0.2)
        pub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
