"""Scoring helpers for presence detection and respiration estimation."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


# ---- presence -------------------------------------------------------------------

@dataclass
class PresenceScore:
    accuracy: float
    false_positive_rate: float   # P(pred present | truly absent)
    false_negative_rate: float   # P(pred absent  | truly present)
    detection_latency_s: float   # mean over absent->present transitions
    clearance_latency_s: float   # mean over present->absent transitions
    n_samples: int

    def as_dict(self) -> dict:
        return asdict(self)


def intervals_to_mask(intervals, t: np.ndarray) -> np.ndarray:
    """intervals: iterable of (t0, t1[, ...]) -> boolean mask over t."""
    m = np.zeros(len(t), dtype=bool)
    for iv in intervals:
        t0, t1 = iv[0], iv[1]
        m |= (t >= t0) & (t < t1)
    return m


def _edge_latency(pred: np.ndarray, truth: np.ndarray, t: np.ndarray, rising: bool) -> float:
    """Mean delay from each truth edge to the first pred sample that matches the
    new truth state. Edges never matched before the next truth edge are counted
    at the time to that next edge (a miss, not silently dropped)."""
    want = rising
    edges = np.where(np.diff(truth.astype(int)) == (1 if rising else -1))[0] + 1
    lat = []
    for i, e in enumerate(edges):
        stop = len(t)
        nxt = np.where(np.diff(truth.astype(int))[e:] != 0)[0]
        if len(nxt):
            stop = e + nxt[0] + 1
        hit = np.where(pred[e:stop] == want)[0]
        lat.append((t[e + hit[0]] - t[e]) if len(hit) else (t[stop - 1] - t[e]))
    return float(np.mean(lat)) if lat else float("nan")


def score_presence(pred: np.ndarray, truth: np.ndarray, t: np.ndarray) -> PresenceScore:
    pred = np.asarray(pred, dtype=bool)
    truth = np.asarray(truth, dtype=bool)
    acc = float(np.mean(pred == truth))
    absent = ~truth
    present = truth
    fpr = float(np.mean(pred[absent])) if absent.any() else 0.0
    fnr = float(np.mean(~pred[present])) if present.any() else 0.0
    return PresenceScore(
        accuracy=acc,
        false_positive_rate=fpr,
        false_negative_rate=fnr,
        detection_latency_s=_edge_latency(pred, truth, t, rising=True),
        clearance_latency_s=_edge_latency(pred, truth, t, rising=False),
        n_samples=len(t),
    )


# ---- respiration ---------------------------------------------------------------

def respiration_mae(estimates: dict[float, list[float]]) -> dict:
    """estimates: {true_bpm: [estimated_bpm, ...]} -> per-rate and overall MAE."""
    per_rate = {}
    all_err = []
    for true_bpm, ests in estimates.items():
        ests = np.asarray(ests, dtype=float)
        ests = ests[np.isfinite(ests)]
        if len(ests) == 0:
            per_rate[true_bpm] = float("nan")
            continue
        err = np.abs(ests - true_bpm)
        per_rate[true_bpm] = float(np.mean(err))
        all_err.extend(err.tolist())
    return {
        "per_rate_mae": per_rate,
        "overall_mae": float(np.mean(all_err)) if all_err else float("nan"),
        "n": len(all_err),
    }
