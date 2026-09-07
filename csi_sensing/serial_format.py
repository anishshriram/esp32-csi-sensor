"""Parse one line of esp-csi serial output.

THE FIELD ORDER BELOW IS A DEFAULT, NOT GROUND TRUTH.
It matches the `csi_recv` get-started example of espressif/esp-csi (rev 8633d67,
ESP32 / non-C6 branch). The `firmware/patches/` change is CSI-config only (HT20,
fixed channel, frozen RX scaling) and does NOT touch the CSV line, so the header
below is exactly what the stock example prints on ESP32:

    type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,
    aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,
    secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data

Note: the plain ESP32 does NOT expose an AGC gain readout (`esp_csi_gain_ctrl`
is a stub for this target), so there is no `agc_gain` field. Instead the firmware
patch sets `manu_scale=true` to freeze the receiver scaling; the host treats
amplitude as already gain-stable and applies a blind step-removal fallback
(`agc.normalize_blind`) if drift is still visible.

During Phase 1 bring-up, capture a real line with `csi-capture --dump-raw` and
compare it field-by-field against `FIELD_SPEC`. Edit this one list if it differs
-- everything downstream reads through this module. The trailing `data` field is
a bracketed list of `len` int8 values, two per subcarrier; pair order
(imag,real vs real,imag) is NOT resolved here -- csi_io derives it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# name, converter. The final "data" field is handled specially.
FIELD_SPEC: list[tuple[str, Callable[[str], object]]] = [
    ("type", str),
    ("id", int),                 # rx_id -- packet counter from the sender payload
    ("mac", str),
    ("rssi", int),
    ("rate", int),
    ("sig_mode", int),
    ("mcs", int),
    ("bandwidth", int),          # rx_ctrl.cwb: 0 = 20 MHz, 1 = 40 MHz
    ("smoothing", int),
    ("not_sounding", int),
    ("aggregation", int),
    ("stbc", int),
    ("fec_coding", int),
    ("sgi", int),
    ("noise_floor", int),
    ("ampdu_cnt", int),
    ("channel", int),
    ("secondary_channel", int),
    ("local_timestamp", int),    # esp-side microseconds
    ("ant", int),
    ("sig_len", int),
    ("rx_format", int),          # stock branch prints sig_mode again in this slot
    ("len", int),                # number of int8 CSI values (2 per subcarrier)
    ("first_word", int),         # first_word_invalid flag
]

DATA_FIELD = "data"
LINE_PREFIX = "CSI_DATA"


@dataclass
class ParseStats:
    ok: int = 0
    malformed: int = 0
    non_csi: int = 0

    def summary(self) -> str:
        return f"parsed={self.ok} malformed={self.malformed} non_csi_lines={self.non_csi}"


def _split_data_field(raw: str) -> list[int]:
    """Parse the trailing bracketed int8 list: '"[1 -2 3 ...]"' or '[1,-2,3]'."""
    raw = raw.strip().strip('"').strip()
    if raw.startswith("["):
        raw = raw[1:]
    if raw.endswith("]"):
        raw = raw[:-1]
    raw = raw.replace(",", " ")
    return [int(tok) for tok in raw.split()]


def parse_line(line: str, stats: Optional[ParseStats] = None) -> Optional[dict]:
    """Return a dict of named fields, or None if the line is not a valid CSI row.

    A None return with `stats` provided increments either `malformed` (looked like
    a CSI row but did not parse) or `non_csi` (some other log line).
    """
    line = line.strip()
    if not line or not line.startswith(LINE_PREFIX):
        if stats is not None:
            stats.non_csi += 1
        return None

    # The data field can contain commas; split off everything from the first '['.
    br = line.find("[")
    if br == -1:
        if stats is not None:
            stats.malformed += 1
        return None
    head, data_raw = line[:br], line[br:]
    head_fields = head.rstrip(' ,"').split(",")

    if len(head_fields) != len(FIELD_SPEC):
        if stats is not None:
            stats.malformed += 1
        return None

    try:
        rec: dict = {}
        for (name, conv), value in zip(FIELD_SPEC, head_fields):
            rec[name] = conv(value)
        data = _split_data_field(data_raw)
    except (ValueError, TypeError):
        if stats is not None:
            stats.malformed += 1
        return None

    if rec.get("len") and len(data) != rec["len"]:
        if stats is not None:
            stats.malformed += 1
        return None
    if len(data) % 2 != 0 or len(data) == 0:
        if stats is not None:
            stats.malformed += 1
        return None

    rec[DATA_FIELD] = data
    if stats is not None:
        stats.ok += 1
    return rec


def format_line(rec: dict) -> str:
    """Inverse of parse_line for the fields in FIELD_SPEC (used by synth + tests)."""
    parts = [str(rec.get(name, 0)) for name, _ in FIELD_SPEC]
    data = " ".join(str(int(v)) for v in rec[DATA_FIELD])
    return ",".join(parts) + f',"[{data}]"'
