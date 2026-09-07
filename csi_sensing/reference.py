"""Phyphox accelerometer ground truth + clock alignment.

The operator straps a phone to the subject's sternum running Phyphox (linear or
raw accelerometer, timestamped), exports CSV, and produces a sharp shared event
-- a few deliberate deep breaths -- at the start of every recording. That event
lets us solve the phone<->host clock offset by cross-correlation.

Phyphox CSV columns vary by experiment; this loader accepts the common shapes:
  "Time (s)","Acceleration x (m/s^2)","Acceleration y (m/s^2)","Acceleration z (m/s^2)"
  or "Linear Acceleration x ...", or a leading absolute-time column.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from csi_sensing.respiration import RESP_BAND_HZ


@dataclass
class Reference:
    t: np.ndarray          # seconds (phone clock, zero-based)
    chest: np.ndarray      # 1-D chest-motion proxy (band-passed principal axis)
    fs: float
    t_abs0: float = 0.0    # absolute epoch of t[0] if known, else 0


def _find_col(cols, *keys):
    for c in cols:
        cl = c.lower()
        if all(k in cl for k in keys):
            return c
    return None


def load_phyphox(path: str, band=RESP_BAND_HZ) -> Reference:
    df = pd.read_csv(path)
    cols = list(df.columns)

    tcol = _find_col(cols, "time") or cols[0]
    ax = _find_col(cols, "acceleration", "x") or _find_col(cols, "linear", "x")
    ay = _find_col(cols, "acceleration", "y") or _find_col(cols, "linear", "y")
    az = _find_col(cols, "acceleration", "z") or _find_col(cols, "linear", "z")
    if ax is None or ay is None or az is None:
        raise ValueError(f"{path}: could not find acceleration x/y/z columns in {cols}")

    t = df[tcol].to_numpy(dtype=float)
    t_abs0 = 0.0
    if t[0] > 1e9:            # looks like an absolute unix time column
        t_abs0 = float(t[0])
    t = t - t[0]
    acc = df[[ax, ay, az]].to_numpy(dtype=float)

    # resample to a uniform grid at the median rate
    dt = np.median(np.diff(t))
    fs = 1.0 / dt if dt > 0 else 50.0
    tu = np.arange(0, t[-1], dt)
    accu = np.column_stack([np.interp(tu, t, acc[:, j]) for j in range(3)])

    # principal axis of chest motion, then band-pass to the respiration band
    accu = accu - accu.mean(axis=0)
    _, _, Vt = np.linalg.svd(accu, full_matrices=False)
    proj = accu @ Vt[0]
    ny = 0.5 * fs
    b, a = butter(4, [band[0] / ny, band[1] / ny], btype="band")
    chest = filtfilt(b, a, proj) if len(proj) > 30 else proj
    return Reference(t=tu, chest=chest, fs=fs, t_abs0=t_abs0)


def reference_bpm(ref: Reference, band=RESP_BAND_HZ) -> float:
    sig = ref.chest - ref.chest.mean()
    w = np.hanning(len(sig))
    X = np.abs(np.fft.rfft(sig * w))
    f = np.fft.rfftfreq(len(sig), 1 / ref.fs)
    m = (f >= band[0]) & (f <= band[1])
    if not m.any():
        return float("nan")
    return float(f[m][np.argmax(X[m])] * 60.0)


def _energy_envelope(x: np.ndarray, fs: float, win_s: float = 2.0) -> np.ndarray:
    from scipy.ndimage import uniform_filter1d

    e = uniform_filter1d(np.abs(x - np.mean(x)) ** 2, max(1, int(win_s * fs)))
    return (e - e.mean()) / (e.std() + 1e-12)


def align(csi_t: np.ndarray, csi_sig: np.ndarray,
          ref: Reference, max_offset_s: float = 20.0) -> float:
    """Return the offset (seconds) to ADD to `ref.t` so it lines up with `csi_t`.

    The steady breathing is present throughout and would peg the correlation at
    zero lag, so we align on the *energy envelopes* instead: the shared burst of
    deliberate deep breaths at the start shows up as a matching bump in both.
    """
    fs = max(4.0, min(ref.fs, (len(csi_t) - 1) / (csi_t[-1] - csi_t[0])))
    span = min(csi_t[-1] - csi_t[0], ref.t[-1], 90.0)
    grid = np.arange(0, span, 1 / fs)

    a = _energy_envelope(np.interp(grid, csi_t - csi_t[0], csi_sig), fs)
    b = _energy_envelope(np.interp(grid, ref.t, ref.chest), fs)

    corr = np.correlate(a, b, mode="full")
    lags = (np.arange(len(corr)) - (len(b) - 1)) / fs
    keep = np.abs(lags) <= max_offset_s
    return float(lags[keep][np.argmax(corr[keep])])
