"""Phase 3 -- presence detection.

Motion sharply raises the short-time variance of the AGC-normalized amplitude
across active subcarriers. Threshold that variance (level set from an `empty`
recording's noise floor, not by eye), then debounce so the output does not
chatter at the boundary.

A still subject is much harder than a moving one -- report `walking` and
`sitting` performance separately (see analysis/characterize.py and metrics).
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from csi_sensing import csi_io
from csi_sensing.agc import normalized_amplitude

log = logging.getLogger(__name__)


@dataclass
class PresenceConfig:
    window_s: float = 2.0
    hop_s: float = 0.5
    threshold_k: float = 6.0        # multiples of empty-baseline std above its median
    debounce_s: float = 3.0         # min dwell in a state before it flips


def motion_score(amp_norm: np.ndarray, t: np.ndarray, cfg: PresenceConfig):
    """Sliding-window mean over subcarriers of per-subcarrier variance.

    Returns (t_windows, score). `amp_norm` is (N, S), `t` is (N,) seconds.
    """
    fs = (len(t) - 1) / (t[-1] - t[0])
    win = max(2, int(round(cfg.window_s * fs)))
    hop = max(1, int(round(cfg.hop_s * fs)))
    # normalize each subcarrier to its own mean so strong bins don't dominate
    rel = amp_norm / (np.mean(amp_norm, axis=0, keepdims=True) + 1e-12)
    starts = np.arange(0, len(t) - win + 1, hop)
    score = np.empty(len(starts))
    tw = np.empty(len(starts))
    for i, s in enumerate(starts):
        seg = rel[s : s + win]
        score[i] = np.mean(np.var(seg, axis=0))
        tw[i] = t[s + win // 2]
    return tw, score


def threshold_from_baseline(baseline_score: np.ndarray, k: float) -> float:
    med = np.median(baseline_score)
    mad = np.median(np.abs(baseline_score - med)) * 1.4826
    return float(med + k * (mad if mad > 0 else np.std(baseline_score) + 1e-12))


def debounce(flags: np.ndarray, tw: np.ndarray, min_dwell_s: float) -> np.ndarray:
    out = flags.astype(bool).copy()
    i = 0
    n = len(out)
    while i < n:
        j = i
        while j < n and out[j] == out[i]:
            j += 1
        if i > 0 and (tw[j - 1] - tw[i]) < min_dwell_s:
            out[i:j] = out[i - 1]
        i = j
    return out


def _resp_peakiness(x: np.ndarray, fs: float, band=(0.15, 0.60)) -> float:
    """Sharpest respiration-band spectral line over the median of an out-of-band
    reference [0.8, 2.0] Hz. ~1 for noise, >>1 for a real periodic breath."""
    X = np.abs(np.fft.rfft((x - x.mean(0)) * np.hanning(len(x))[:, None], axis=0)) ** 2
    f = np.fft.rfftfreq(x.shape[0], 1 / fs)
    inb = (f >= band[0]) & (f <= band[1])
    ref = (f >= 0.8) & (f <= 2.0)
    if not inb.any() or not ref.any():
        return 0.0
    peak = X[inb].max(axis=0)
    floor = np.median(X[ref], axis=0) + 1e-18
    return float(np.sort(peak / floor)[-3:].mean())


def respiration_presence(rec: csi_io.CSIRecording, tw: np.ndarray,
                         cfg: PresenceConfig, peak_thresh: float = 40.0) -> np.ndarray:
    """Secondary cue (beyond the Phase 3 variance baseline): a sharp periodic
    component in the respiration band implies a (possibly still) subject."""
    from csi_sensing.respiration import RESP_BAND_HZ, pca_background_subtract

    amp = normalized_amplitude(rec, active_only=True)
    t = rec.host_ts - rec.host_ts[0]
    fs_u = 20.0
    n = int(t[-1] * fs_u) + 1
    tu = np.arange(n) / fs_u
    xu = np.column_stack([np.interp(tu, t, amp[:, j]) for j in range(amp.shape[1])])
    resid = pca_background_subtract(xu, (1, 4))
    win = int(40.0 * fs_u)
    flags = np.zeros(len(tw), dtype=bool)
    for i, tc in enumerate(tw):
        c = int(tc * fs_u)
        s, e = max(0, c - win // 2), min(len(resid), c + win // 2)
        if e - s < 20 * fs_u:
            flags[i] = flags[i - 1] if i else False
            continue
        flags[i] = _resp_peakiness(resid[s:e], fs_u, RESP_BAND_HZ) > peak_thresh
    return flags


def detect(rec: csi_io.CSIRecording, cfg: PresenceConfig, threshold: float,
           respiration_assist: bool = False):
    amp = normalized_amplitude(rec, active_only=True)
    tw, score = motion_score(amp, rec.host_ts - rec.host_ts[0], cfg)
    raw_flags = score > threshold
    if respiration_assist:
        raw_flags = raw_flags | respiration_presence(rec, tw, cfg)
    flags = debounce(raw_flags, tw, cfg.debounce_s)
    return tw, score, flags


def calibrate_threshold(empty_rec: csi_io.CSIRecording, cfg: PresenceConfig) -> float:
    amp = normalized_amplitude(empty_rec, active_only=True)
    _, score = motion_score(amp, empty_rec.host_ts - empty_rec.host_ts[0], cfg)
    return threshold_from_baseline(score, cfg.threshold_k)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Score presence detection on a recording.")
    p.add_argument("recording", help="CSV to detect on")
    p.add_argument("--empty", help="empty CSV to calibrate the threshold from")
    p.add_argument("--threshold", type=float, help="explicit motion-score threshold")
    p.add_argument("--truth", help="JSON list of [t0,t1] present intervals (seconds from start)")
    p.add_argument("--window", type=float, default=2.0)
    p.add_argument("--debounce", type=float, default=3.0)
    p.add_argument("--k", type=float, default=6.0)
    p.add_argument("--respiration-assist", action="store_true",
                   help="also flag windows with a strong respiration-band signal (helps 'sitting')")
    args = p.parse_args(argv)

    cfg = PresenceConfig(window_s=args.window, debounce_s=args.debounce, threshold_k=args.k)
    rec = csi_io.load(args.recording)

    if args.threshold is not None:
        thr = args.threshold
    elif args.empty:
        thr = calibrate_threshold(csi_io.load(args.empty), cfg)
    else:
        p.error("need --threshold or --empty to set the detection threshold")
    tw, score, flags = detect(rec, cfg, thr, respiration_assist=args.respiration_assist)

    print(f"threshold={thr:.3e}  windows={len(tw)}  present_fraction={np.mean(flags):.3f}")
    if args.truth:
        from csi_sensing.metrics import intervals_to_mask, score_presence

        intervals = json.loads(args.truth)
        truth = intervals_to_mask(intervals, tw)
        s = score_presence(flags, truth, tw)
        for key, val in s.as_dict().items():
            print(f"  {key:24s}: {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
