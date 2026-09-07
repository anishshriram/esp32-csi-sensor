"""AGC gain normalization.

The ESP32 adjusts receiver gain between packets. Uncorrected, the resulting
amplitude steps look exactly like motion. Divide out the gain:

    amp_norm = amp / 10 ** (agc_gain / 20)

`agc_gain` is treated as decibels (the esp-csi field is a small integer that
behaves like a dB-scale gain index; confirm the scaling on a static recording
with `plot_diagnostic` -- steps in the raw trace must flatten after this).
"""
from __future__ import annotations

import numpy as np

from csi_sensing.csi_io import CSIRecording


def normalize_amplitude(amp: np.ndarray, agc_gain: np.ndarray) -> np.ndarray:
    """amp: (N, S) or (N,); agc_gain: (N,). Returns same shape as amp."""
    agc_gain = np.asarray(agc_gain, dtype=float)
    factor = 10.0 ** (agc_gain / 20.0)
    if amp.ndim == 2:
        return amp / factor[:, None]
    return amp / factor


def normalized_amplitude(rec: CSIRecording, active_only: bool = True) -> np.ndarray:
    if "agc_gain" not in rec.meta.columns:
        raise ValueError("recording has no agc_gain column; amplitude cannot be normalized")
    amp = rec.amplitude(active_only=active_only)
    return normalize_amplitude(amp, rec.meta["agc_gain"].to_numpy())


def diagnostic_series(rec: CSIRecording, subcarrier: int | None = None) -> dict:
    """Three aligned series for the Phase 2.3 validation plot."""
    if subcarrier is None:
        # pick the strongest active subcarrier
        amp_act = rec.amplitude(active_only=True)
        subcarrier = int(rec.active[np.argmax(np.median(amp_act, axis=0))])
    raw = np.abs(rec.csi[:, subcarrier])
    gain = rec.meta["agc_gain"].to_numpy(dtype=float)
    return {
        "t": rec.host_ts - rec.host_ts[0],
        "subcarrier": subcarrier,
        "raw_amp": raw,
        "agc_gain": gain,
        "norm_amp": normalize_amplitude(raw, gain),
    }


def flatness_gain(rec: CSIRecording) -> float:
    """Ratio of raw to normalized coefficient-of-variation on the strongest
    subcarrier. > 1 means normalization reduced amplitude wander (good on a
    static recording)."""
    d = diagnostic_series(rec)
    cv = lambda x: np.std(x) / (np.mean(x) + 1e-12)
    return float(cv(d["raw_amp"]) / (cv(d["norm_amp"]) + 1e-12))
