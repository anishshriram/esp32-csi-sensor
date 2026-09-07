from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")


def load_sidecar(csv_path: str) -> dict:
    for cand in (csv_path + ".meta.json", os.path.splitext(csv_path)[0] + ".meta.json"):
        if os.path.exists(cand):
            with open(cand) as fh:
                return json.load(fh)
    return {}


def title_from_meta(csv_path: str, prefix: str) -> str:
    m = load_sidecar(csv_path)
    bits = [prefix, os.path.basename(csv_path)]
    if m.get("label"):
        bits.append(f"label={m['label']}")
    if m.get("wall_present") is not None:
        bits.append("wall" if m["wall_present"] else "LOS")
    if m.get("board_separation_m"):
        bits.append(f"{m['board_separation_m']} m")
    if m.get("synthetic"):
        bits.append("[SYNTHETIC]")
    return "  ".join(bits)
