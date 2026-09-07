"""Parse one line of esp-csi serial output.

THE FIELD ORDER BELOW IS A DEFAULT, NOT GROUND TRUTH.
It matches the `csi_recv` example of espressif/esp-csi as of ESP-IDF v5.3.x. The
layout has changed between esp-csi revisions. During Phase 1 bring-up (step 9),
capture a real line with `idf.py monitor`, compare it field-by-field against
`FIELD_SPEC`, and edit this one list if it differs. Everything downstream reads
through this module, so this is the only place that needs to change.

Expected line shape (one CSV row, trailing field is a bracketed int8 list):

    CSI_DATA,123,7c:9e:bd:...,-42,11,1,0,0,1,1,0,0,0,1,-95,0,6,0,140736,0,128,0,52,11,128,0,"[13 -7 12 ...]"

The bracketed list holds `len` signed 8-bit values, two per subcarrier. The pair
order (imag,real) vs (real,imag) is NOT resolved here -- csi_io derives it from
the data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# name, converter. The final "data" field is handled specially.
FIELD_SPEC: list[tuple[str, Callable[[str], object]]] = [
    ("type", str),
    ("seq", int),
    ("mac", str),
    ("rssi", int),
    ("rate", int),
    ("sig_mode", int),
    ("mcs", int),
    ("bandwidth", int),
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
    ("local_timestamp", int),
    ("ant", int),
    ("sig_len", int),
    ("rx_state", int),
    ("agc_gain", int),
    ("fft_gain", int),
    ("len", int),
    ("first_word_invalid", int),
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
