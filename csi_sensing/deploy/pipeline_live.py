"""Phase 6 -- run presence + respiration on a live stream and emit one metric
record per second: {presence, bpm, confidence, timestamp}.

Sources:
  --port  /dev/tty...     read the receiver serial stream directly
  --replay some.csv       replay a capture CSV in (near) real time -- for demos
                          and for driving the dashboard without hardware

The metric record is printed as JSON on stdout and, if --mqtt is given, handed to
mqtt_publish.publish().
"""
from __future__ import annotations

import argparse
import json
import time
from collections import deque
from typing import Iterator, Optional

import numpy as np

from csi_sensing import csi_io, presence, respiration
from csi_sensing.serial_format import ParseStats, parse_line

BAUD = 921_600


def _serial_lines(port: str) -> Iterator[str]:
    import serial

    ser = serial.Serial()          # open without toggling DTR/RTS -> no board reset
    ser.port, ser.baudrate, ser.timeout = port, BAUD, 1
    ser.dtr = ser.rts = False
    ser.open()
    try:
        while True:
            raw = ser.readline()
            if raw:
                yield raw.decode("utf-8", errors="replace")
    finally:
        ser.close()


def _replay_lines(csv_path: str, speed: float) -> Iterator[tuple[float, dict]]:
    import pandas as pd

    df = pd.read_csv(csv_path)
    t0 = df["host_ts"].iloc[0]
    start = time.time()
    for _, row in df.iterrows():
        target = (row["host_ts"] - t0) / speed
        dt = target - (time.time() - start)
        if dt > 0:
            time.sleep(min(dt, 0.5))
        yield float(row["host_ts"]), row.to_dict()


class RollingCSI:
    """Fixed-duration ring buffer of (host_ts, complex CSI row)."""

    def __init__(self, seconds: float = 90.0, max_rows: int = 20000):
        self.seconds = seconds
        self.ts = deque(maxlen=max_rows)
        self.rows = deque(maxlen=max_rows)
        self.agc = deque(maxlen=max_rows)
        self._order: Optional[str] = None
        self._active: Optional[np.ndarray] = None

    def add(self, host_ts: float, data_ints: list[int], agc_gain: float = 0.0) -> None:
        self.ts.append(host_ts)
        self.rows.append(np.asarray(data_ints, dtype=np.int64))
        self.agc.append(float(agc_gain))
        while self.ts and host_ts - self.ts[0] > self.seconds:
            self.ts.popleft()
            self.rows.popleft()
            self.agc.popleft()

    def recording(self) -> Optional[csi_io.CSIRecording]:
        if len(self.rows) < 200:
            return None
        raw = np.vstack(self.rows)
        provisional = csi_io._to_complex(raw, "im_re")
        if self._active is None:
            self._active = csi_io.derive_active_subcarriers(provisional)
        if self._order is None:
            self._order = csi_io.detect_pair_order(raw, self._active)
        csi = csi_io._to_complex(raw, self._order)
        import pandas as pd

        meta = pd.DataFrame({"host_ts": list(self.ts), "agc_gain": list(self.agc)})
        return csi_io.CSIRecording(csi=csi, meta=meta, active=self._active,
                                   pair_order=self._order)


def run(source, *, is_serial: bool, buffer_s: float = 90.0, emit_every: float = 1.0,
        empty_threshold: Optional[float] = None, on_metric=None, max_records=None):
    buf = RollingCSI(buffer_s)
    pcfg = presence.PresenceConfig()
    rcfg = respiration.RespirationConfig()
    stats = ParseStats()
    last_emit = 0.0
    n = 0

    for item in source:
        if is_serial:
            rec = parse_line(item, stats)
            if rec is None:
                continue
            host_ts = time.time()
            data = rec["data"]
            agc = rec.get("agc_gain", 0.0)
        else:
            host_ts, row = item
            data = [int(v) for v in str(row["data"]).split()]
            agc = float(row.get("agc_gain", 0.0))
        buf.add(host_ts, data, agc)

        if host_ts - last_emit < emit_every:
            continue
        last_emit = host_ts
        r = buf.recording()
        if r is None:
            continue

        thr = empty_threshold if empty_threshold is not None else _adaptive_threshold(r, pcfg)
        tw, score, flags = presence.detect(r, pcfg, thr)
        present = bool(flags[-1]) if len(flags) else False

        bpm, conf = float("nan"), 0.0
        try:
            res = respiration.estimate_from_recording(r, rcfg)
            bpm, conf = res.summary_bpm(), float(np.nanmean(res.confidence))
        except Exception:  # noqa: BLE001
            pass

        record = {
            "timestamp": host_ts,
            "presence": present,
            "bpm": round(bpm, 2) if np.isfinite(bpm) else None,
            "confidence": round(conf, 3),
        }
        n += 1
        (on_metric or _print_metric)(record)
        if max_records and n >= max_records:
            break


def _adaptive_threshold(rec: csi_io.CSIRecording, cfg: presence.PresenceConfig) -> float:
    """No dedicated empty file live: use the quietest 20% of windows as baseline."""
    _, score = presence._score(rec, cfg)
    quiet = np.sort(score)[: max(3, len(score) // 5)]
    return presence.threshold_from_baseline(quiet, cfg.threshold_k)


def _print_metric(record: dict) -> None:
    print(json.dumps(record), flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--port")
    src.add_argument("--replay", metavar="CSV")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    p.add_argument("--buffer", type=float, default=90.0)
    p.add_argument("--emit-every", type=float, default=1.0)
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--mqtt", metavar="BROKER", default=None)
    p.add_argument("--topic", default="csi/metrics")
    p.add_argument("--max-records", type=int, default=None)
    args = p.parse_args(argv)

    on_metric = _print_metric
    if args.mqtt:
        from csi_sensing.deploy.mqtt_publish import Publisher

        pub = Publisher(args.mqtt, args.topic)

        def on_metric(rec):  # noqa: ARG001
            _print_metric(rec)
            pub.publish(rec)

    if args.port:
        run(_serial_lines(args.port), is_serial=True, buffer_s=args.buffer,
            emit_every=args.emit_every, empty_threshold=args.threshold,
            on_metric=on_metric, max_records=args.max_records)
    else:
        run(_replay_lines(args.replay, args.speed), is_serial=False, buffer_s=args.buffer,
            emit_every=args.emit_every, empty_threshold=args.threshold,
            on_metric=on_metric, max_records=args.max_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
