"""Host-side CSI serial logger.

Usage:
    csi-capture --port /dev/tty.SLAB_USBtoUART --duration 60 --out data/empty_los_2m.csv \
                --label empty

`idf.py monitor` holds the serial port exclusively -- it must NOT be running
during capture.

Writes one CSV row per CSI packet: a host wall-clock timestamp first, then every
parsed esp-csi field (no rx_ctrl field is dropped), then the raw int8 payload.
A sidecar `<out>.meta.json` records the recording context; anything not passed as
a flag is prompted for interactively.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from typing import Optional, TextIO

from csi_sensing import CAPTURE_COLUMNS
from csi_sensing.serial_format import ParseStats, parse_line

BAUD = 921_600
FLUSH_EVERY = 100


def _firmware_sha() -> str:
    for env in ("ESP_CSI_DIR", "IDF_PATH"):
        d = os.environ.get(env)
        if d and os.path.isdir(d):
            try:
                return subprocess.check_output(
                    ["git", "-C", d, "rev-parse", "--short", "HEAD"], text=True
                ).strip()
            except Exception:  # noqa: BLE001
                pass
    return "unknown"


def _prompt(name: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        val = input(f"{name}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or (default or "")


def build_meta(args) -> dict:
    return {
        "label": args.label or _prompt("label (empty/walking/sitting/...)"),
        "channel": args.channel or int(_prompt("wifi channel", "6")),
        "board_separation_m": args.separation
        if args.separation is not None
        else float(_prompt("board separation (m)", "2.0")),
        "wall_present": args.wall
        if args.wall is not None
        else _prompt("wall present? (y/n)", "n").lower().startswith("y"),
        "subject_position": args.position or _prompt("subject position", "n/a"),
        "start_time": time.time(),
        "firmware_sha": _firmware_sha(),
        "notes": args.notes or "",
        "synthetic": False,
    }


def open_serial(port: str):
    """Open the port WITHOUT resetting the board.

    pyserial asserts DTR/RTS on open, which drives the ESP32 dev-board auto-reset
    circuit (EN + GPIO0) and can wedge it. Hold both low and leave them.
    """
    try:
        import serial  # pyserial
    except ImportError:  # pragma: no cover
        sys.exit("pyserial not installed: pip install pyserial")
    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = BAUD
        ser.timeout = 1
        ser.dtr = False
        ser.rts = False
        ser.open()
        return ser
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"cannot open {port} @ {BAUD}: {exc}\n"
                 f"(is `idf.py monitor` still running? is the board plugged in?)")


def capture(port: str, duration: float, out_path: str, meta: dict,
            dump_raw: Optional[str] = None, _source_lines=None) -> dict:
    """Run the capture loop. `_source_lines` (an iterable of str) overrides the
    serial port for testing/replay."""
    stats = ParseStats()
    rows_written = 0
    t_start = time.time()

    raw_fh: Optional[TextIO] = open(dump_raw, "w") if dump_raw else None
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CAPTURE_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        if _source_lines is not None:
            line_iter = iter(_source_lines)
            ser = None
        else:
            ser = open_serial(port)
            line_iter = None
            # Opening the port can reset the board. Wait out the boot log and
            # only start the timed window once CSI is flowing *cleanly* -- a run
            # of consecutive CSI lines with no interleaved log output.
            settle_deadline = time.time() + 8.0
            clean_run = 0
            total_csi = 0
            while time.time() < settle_deadline:
                raw = ser.readline()
                if not raw:
                    continue
                if raw.startswith(b"CSI_DATA"):
                    clean_run += 1
                    total_csi += 1
                    if clean_run >= 60:        # ~0.6 s of uninterrupted CSI
                        break
                else:
                    clean_run = 0
            if total_csi < 20:
                print("WARNING: no steady CSI within 8 s of opening the port "
                      "(transmitter down? board wedged? -- power-cycle both)")
            ser.reset_input_buffer()
            t_start = time.time()

        try:
            while True:
                if line_iter is not None:
                    line = next(line_iter, None)
                    if line is None:
                        break
                else:
                    if time.time() - t_start >= duration:
                        break
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace")

                host_ts = time.time()
                if raw_fh is not None:
                    raw_fh.write(line if line.endswith("\n") else line + "\n")

                rec = parse_line(line, stats)
                if rec is None:
                    continue
                rec["host_ts"] = host_ts
                rec["data"] = " ".join(str(int(v)) for v in rec["data"])
                writer.writerow(rec)
                rows_written += 1
                if rows_written % FLUSH_EVERY == 0:
                    fh.flush()
        finally:
            if ser is not None:
                ser.close()
            if raw_fh is not None:
                raw_fh.close()

    elapsed = time.time() - t_start
    rate = rows_written / elapsed if elapsed > 0 else float("nan")
    meta = {**meta, "rows": rows_written, "duration_s": elapsed, "mean_pkt_rate_hz": rate}
    with open(out_path + ".meta.json", "w") as fh:
        json.dump(meta, fh, indent=2)

    summary = {
        "rows_written": rows_written,
        "duration_s": elapsed,
        "mean_pkt_rate_hz": rate,
        "malformed": stats.malformed,
        "non_csi_lines": stats.non_csi,
    }
    print("\n" + "=" * 52)
    print(f"  rows written      : {rows_written}")
    print(f"  duration          : {elapsed:.1f} s")
    print(f"  MEAN PACKET RATE  : {rate:.1f} Hz")
    print(f"  malformed lines   : {stats.malformed}")
    print(f"  non-CSI lines     : {stats.non_csi}")
    print("=" * 52)
    exp = duration * 100
    if _source_lines is None and rows_written < 0.7 * exp:
        print("  WARNING: row count far below 100 Hz expectation -- packet loss;")
        print("           fix before continuing (lower sample rate or channel).")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", required=True)
    p.add_argument("--duration", type=float, required=True, help="seconds")
    p.add_argument("--out", required=True, help="output CSV path")
    p.add_argument("--label", default=None)
    p.add_argument("--channel", type=int, default=None)
    p.add_argument("--separation", type=float, default=None, help="board separation (m)")
    p.add_argument("--wall", type=lambda s: s.lower().startswith("y"), default=None)
    p.add_argument("--position", default=None, help="subject position")
    p.add_argument("--notes", default=None)
    p.add_argument("--dump-raw", default=None, metavar="PATH",
                   help="also tee every serial line here (for format inspection)")
    args = p.parse_args(argv)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    meta = build_meta(args)
    capture(args.port, args.duration, args.out, meta, dump_raw=args.dump_raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
