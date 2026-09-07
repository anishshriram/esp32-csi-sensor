"""Phase 5 -- through-wall characterization table.

Input: a manifest CSV with one row per recording:

    path,config,distance_m,truth_bpm,empty_path,present_intervals
    data/los_2m_sitting.csv,los,2.0,15,data/los_empty.csv,"[[0,150]]"
    data/wall_2m_sitting.csv,wall,2.0,15,data/wall_empty.csv,"[[0,150]]"

`present_intervals` is optional JSON (seconds from start); `empty_path` is
optional (falls back to an adaptive baseline). `truth_bpm` may be a number or a
path to a Phyphox CSV.

Output: results/comparison.md + results/comparison.csv with, per row,
presence accuracy and respiration MAE -- and the degradation between matched
los/wall configurations.
"""
from __future__ import annotations

import argparse
import ast
import json
import os

import numpy as np
import pandas as pd

from csi_sensing import csi_io, presence, respiration
from csi_sensing.metrics import intervals_to_mask, score_presence


def _truth_bpm(val) -> float | None:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        pass
    if isinstance(val, str) and os.path.exists(val):
        from csi_sensing.reference import load_phyphox, reference_bpm

        return reference_bpm(load_phyphox(val))
    return None


def _intervals(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return ast.literal_eval(val)
    return val


def evaluate_row(row: dict) -> dict:
    rec = csi_io.load(row["path"])
    pcfg = presence.PresenceConfig()
    rcfg = respiration.RespirationConfig()

    if row.get("empty_path") and isinstance(row["empty_path"], str) and os.path.exists(row["empty_path"]):
        thr = presence.calibrate_threshold(csi_io.load(row["empty_path"]), pcfg)
    else:
        from csi_sensing.deploy.pipeline_live import _adaptive_threshold

        thr = _adaptive_threshold(rec, pcfg)

    tw, _, flags = presence.detect(rec, pcfg, thr, respiration_assist=True)
    ivs = _intervals(row.get("present_intervals"))
    if ivs is not None:
        truth_mask = intervals_to_mask(ivs, tw)
        pscore = score_presence(flags, truth_mask, tw)
        presence_acc = pscore.accuracy
        presence_lat = pscore.detection_latency_s
    else:
        presence_acc = float("nan")
        presence_lat = float("nan")

    res = respiration.estimate_from_recording(rec, rcfg)
    est = res.summary_bpm()
    tb = _truth_bpm(row.get("truth_bpm"))
    mae = abs(est - tb) if tb is not None else float("nan")

    return {
        "recording": os.path.basename(row["path"]),
        "config": row.get("config", "?"),
        "distance_m": row.get("distance_m", float("nan")),
        "present_fraction": round(float(np.mean(flags)), 3),
        "presence_accuracy": round(presence_acc, 3),
        "presence_latency_s": round(presence_lat, 2),
        "resp_bpm_est": round(est, 2),
        "resp_bpm_truth": round(tb, 2) if tb is not None else None,
        "resp_abs_err": round(mae, 2) if np.isfinite(mae) else None,
        "resp_confidence": round(float(np.nanmean(res.confidence)), 2),
    }


def degradation_table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    out = []
    for dist in sorted(set(df["distance_m"].dropna())):
        sub = df[df["distance_m"] == dist]
        los = sub[sub["config"] == "los"]
        wall = sub[sub["config"] == "wall"]
        if len(los) and len(wall):
            out.append({
                "distance_m": dist,
                "presence_acc_los": los["presence_accuracy"].mean(),
                "presence_acc_wall": wall["presence_accuracy"].mean(),
                "resp_mae_los": los["resp_abs_err"].astype(float).mean(),
                "resp_mae_wall": wall["resp_abs_err"].astype(float).mean(),
                "resp_mae_delta": wall["resp_abs_err"].astype(float).mean()
                - los["resp_abs_err"].astype(float).mean(),
            })
    return pd.DataFrame(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("manifest")
    p.add_argument("--outdir", default="results")
    args = p.parse_args(argv)

    man = pd.read_csv(args.manifest)
    rows = [evaluate_row(r.to_dict()) for _, r in man.iterrows()]
    per_rec = pd.DataFrame(rows)
    deg = degradation_table(rows)

    os.makedirs(args.outdir, exist_ok=True)
    per_rec.to_csv(os.path.join(args.outdir, "comparison.csv"), index=False)
    md = ["# Through-wall characterization\n",
          "## Per recording\n", per_rec.to_markdown(index=False), "\n"]
    if len(deg):
        md += ["## LOS vs wall degradation\n", deg.to_markdown(index=False), "\n"]
        for _, r in deg.iterrows():
            md.append(f"- at {r['distance_m']:.0f} m: respiration MAE "
                      f"{r['resp_mae_los']:.2f} bpm LOS -> {r['resp_mae_wall']:.2f} bpm through wall "
                      f"(+{r['resp_mae_delta']:.2f})")
    with open(os.path.join(args.outdir, "comparison.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")
    print(per_rec.to_string(index=False))
    print(f"\nwrote {args.outdir}/comparison.md and comparison.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
