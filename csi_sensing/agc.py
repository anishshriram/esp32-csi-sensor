"""Receiver-gain normalization.

Two regimes, depending on the receiver:

* **`agc_gain` reported** (ESP32-S3/C3/C6, or a synthetic recording): divide it
  out directly.  ``amp_norm = amp / 10 ** (agc_gain / 20)``

* **no `agc_gain`** (plain ESP32-WROOM-32 -- the hardware has no gain readout,
  and `esp_csi_gain_ctrl` ships an empty lib for this target). The receiver runs
  its own auto-scale AGC that we cannot read, so ``normalize_blind`` estimates a
  smoothed cross-subcarrier level (the AGC proxy) from the data and divides it
  out. The respiration stage's PCA removes any residue.

Validate on a static recording with ``plot_diagnostic`` -- slow level drift in
the raw trace must flatten after normalization.
"""
from __future__ import annotations

import logging

import numpy as np

from csi_sensing.csi_io import CSIRecording

log = logging.getLogger(__name__)


def normalize_amplitude(amp: np.ndarray, agc_gain: np.ndarray) -> np.ndarray:
    """amp: (N, S) or (N,); agc_gain: (N,) in dB. Returns same shape as amp."""
    agc_gain = np.asarray(agc_gain, dtype=float)
    factor = 10.0 ** (agc_gain / 20.0)
    if amp.ndim == 2:
        return amp / factor[:, None]
    return amp / factor


def _smooth(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return x
    k = np.ones(win) / win
    pad = win // 2
    xp = np.concatenate([np.full(pad, x[0]), x, np.full(pad, x[-1])])
    return np.convolve(xp, k, mode="same")[pad:-pad][: len(x)]


def common_mode_level(amp: np.ndarray, fs: float = 100.0, smooth_s: float = 5.0) -> np.ndarray:
    """Slowly-varying cross-subcarrier level -- a proxy for the (unreported)
    receiver AGC. Smoothed over `smooth_s` so it tracks AGC drift but not the
    0.15-0.6 Hz respiration ripple."""
    if amp.ndim == 1:
        amp = amp[:, None]
    inst = np.median(amp, axis=1)
    inst = np.where(inst > 0, inst, np.median(inst[inst > 0]) if np.any(inst > 0) else 1.0)
    return _smooth(inst, max(1, int(smooth_s * fs)))


def normalize_blind(amp: np.ndarray, fs: float = 100.0, smooth_s: float = 5.0,
                    min_swing: float = 0.10) -> np.ndarray:
    """Remove slow common-mode level drift (blind AGC) without an agc_gain field.

    Divides out a smoothed cross-subcarrier level and restores the global level.
    Applied only when that level actually swings more than `min_swing` (fraction
    of its median) -- dividing by a near-flat, noisy level estimate would just
    inject correlated noise. The respiration stage's PCA takes any residue.
    """
    single = amp.ndim == 1
    if single:
        amp = amp[:, None]
    level = common_mode_level(amp, fs, smooth_s)
    g = np.median(level)
    swing = (level.max() - level.min()) / (g + 1e-12)
    if swing < min_swing:
        return amp[:, 0] if single else amp
    out = amp / level[:, None] * g
    return out[:, 0] if single else out


def has_agc_gain(rec: CSIRecording) -> bool:
    return "agc_gain" in rec.meta.columns and rec.meta["agc_gain"].notna().any()


def normalized_amplitude(rec: CSIRecording, active_only: bool = True,
                         blind: bool | None = None) -> np.ndarray:
    """AGC-normalized amplitude.

    `blind=None` (default): use `agc_gain` if the recording has it, otherwise fall
    back to `normalize_blind`. `blind=True`/`False` forces the choice.
    """
    amp = rec.amplitude(active_only=active_only)
    if blind is False or (blind is None and has_agc_gain(rec)):
        return normalize_amplitude(amp, rec.meta["agc_gain"].to_numpy())
    return normalize_blind(amp, fs=_fs(rec))


def _fs(rec: CSIRecording) -> float:
    t = rec.host_ts
    return (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 and t[-1] > t[0] else 100.0


def diagnostic_series(rec: CSIRecording, subcarrier: int | None = None) -> dict:
    """Three aligned series for the Phase 2.3 validation plot.

    Panel 2 is `agc_gain` when reported, else the per-packet common-mode level
    that `normalize_blind` removes.
    """
    if subcarrier is None:
        amp_act = rec.amplitude(active_only=True)
        subcarrier = int(rec.active[np.argmax(np.median(amp_act, axis=0))])
    raw = np.abs(rec.csi[:, subcarrier])
    t = rec.host_ts - rec.host_ts[0]

    if has_agc_gain(rec):
        gain = rec.meta["agc_gain"].to_numpy(dtype=float)
        return {"t": t, "subcarrier": subcarrier, "raw_amp": raw, "panel2": gain,
                "panel2_label": "agc_gain", "norm_amp": normalize_amplitude(raw, gain)}

    fs = _fs(rec)
    amp_act = rec.amplitude(active_only=True)
    level = common_mode_level(amp_act, fs)
    if subcarrier in rec.active:
        norm = normalize_blind(amp_act, fs=fs)[:, list(rec.active).index(subcarrier)]
    else:
        norm = normalize_blind(raw, fs=fs)
    return {"t": t, "subcarrier": subcarrier, "raw_amp": raw, "panel2": level,
            "panel2_label": "common-mode level", "norm_amp": norm}


def flatness_gain(rec: CSIRecording) -> float:
    """Raw / normalized coefficient-of-variation on the strongest subcarrier.
    > 1 means normalization reduced amplitude wander (good on a static recording)."""
    d = diagnostic_series(rec)
    cv = lambda x: np.std(x) / (np.mean(x) + 1e-12)
    return float(cv(d["raw_amp"]) / (cv(d["norm_amp"]) + 1e-12))
