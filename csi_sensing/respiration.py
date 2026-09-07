"""Phase 4 -- respiration-rate extraction.

Pipeline order matters; each stage assumes the previous:

  1. Hampel filter per subcarrier      -- kill single-packet outliers
  2. Resample onto a uniform grid      -- spectral stage needs uniform sampling
  3. PCA background subtraction         -- drop PC1 (static multipath/direct path),
                                          keep components 2-4
  4. Band-pass 0.15-0.6 Hz              -- 4th-order Butterworth, zero-phase filtfilt
  5. Subcarrier selection by band SNR   -- rank, fuse the top 5-10
  6. Rate estimation                    -- spectral peak over a 30-60 s sliding
                                          window; confidence from peak prominence

Only amplitude is used. CSI phase is not a sensing input on a single-antenna
ESP32.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

from csi_sensing import csi_io
from csi_sensing.agc import normalized_amplitude

log = logging.getLogger(__name__)

RESP_BAND_HZ = (0.15, 0.60)     # 9-36 breaths/min


@dataclass
class RespirationConfig:
    fs: float = 20.0               # uniform resample rate (Hz)
    hampel_win: int = 7           # samples (odd)
    hampel_sigma: float = 3.0
    pca_keep: tuple[int, int] = (1, 4)   # component indices to retain (0-based: skip 0)
    n_fuse: int = 8              # subcarriers to fuse
    window_s: float = 45.0
    hop_s: float = 5.0
    band: tuple[float, float] = RESP_BAND_HZ


# ---- stage 1: hampel -----------------------------------------------------------

def hampel(x: np.ndarray, win: int = 7, n_sigma: float = 3.0) -> np.ndarray:
    """Per-column Hampel filter. x: (N,) or (N, S)."""
    x = np.asarray(x, dtype=float)
    single = x.ndim == 1
    if single:
        x = x[:, None]
    k = win // 2
    out = x.copy()
    n = len(x)
    for i in range(n):
        lo, hi = max(0, i - k), min(n, i + k + 1)
        seg = x[lo:hi]
        med = np.median(seg, axis=0)
        mad = 1.4826 * np.median(np.abs(seg - med), axis=0)
        bad = np.abs(x[i] - med) > n_sigma * np.where(mad > 0, mad, np.inf)
        out[i, bad] = med[bad]
    return out[:, 0] if single else out


# ---- stage 3: PCA background subtraction --------------------------------------

def pca_background_subtract(amp: np.ndarray, keep=(1, 4)) -> np.ndarray:
    """Center, SVD, reconstruct keeping only components keep[0]..keep[1]-1.

    Component 0 carries static multipath (walls, furniture, direct path) and is
    discarded. Returns the reconstructed (N, S) residual.
    """
    mu = amp.mean(axis=0, keepdims=True)
    xc = amp - mu
    U, S, Vt = np.linalg.svd(xc, full_matrices=False)
    lo, hi = keep
    hi = min(hi, len(S))
    if lo >= hi:
        return np.zeros_like(amp)
    recon = (U[:, lo:hi] * S[lo:hi]) @ Vt[lo:hi]
    return recon


# ---- stage 4: band-pass ------------------------------------------------------

def bandpass(x: np.ndarray, fs: float, band=RESP_BAND_HZ, order: int = 4) -> np.ndarray:
    ny = 0.5 * fs
    b, a = butter(order, [band[0] / ny, band[1] / ny], btype="band")
    padlen = 3 * max(len(a), len(b))
    if x.shape[0] <= padlen:
        return np.zeros_like(x)
    return filtfilt(b, a, x, axis=0)


# ---- stage 5: subcarrier selection by band-power SNR -------------------------

def _band_spectra(x: np.ndarray, fs: float, band):
    X = np.abs(np.fft.rfft((x - x.mean(axis=0, keepdims=True)) * np.hanning(len(x))[:, None], axis=0))
    f = np.fft.rfftfreq(x.shape[0], 1 / fs)
    m = (f >= band[0]) & (f <= band[1])
    return f, X, m


def band_snr(x: np.ndarray, fs: float, band=RESP_BAND_HZ) -> np.ndarray:
    """Per-column ratio of in-band energy to total energy."""
    f, X, m = _band_spectra(x, fs, band)
    p = X ** 2
    return p[m].sum(axis=0) / (p.sum(axis=0) + 1e-12)


def subcarrier_quality(x: np.ndarray, fs: float, band=RESP_BAND_HZ):
    """Return (score, peak_freq) per column.

    score = band_snr * peakiness, where peakiness is the dominant in-band bin
    over the in-band median -- rewards a single clean respiration line and
    penalizes broadband wander.
    """
    f, X, m = _band_spectra(x, fs, band)
    p = (X ** 2)
    snr = p[m].sum(axis=0) / (p.sum(axis=0) + 1e-12)
    pin = p[m]
    fb = f[m]
    peak_idx = np.argmax(pin, axis=0)
    peak_val = pin[peak_idx, np.arange(pin.shape[1])]
    med = np.median(pin, axis=0) + 1e-18
    peakiness = peak_val / med
    return snr * np.sqrt(peakiness), fb[peak_idx]


def select_consensus(x: np.ndarray, fs: float, band, n_fuse: int, n_pool: int = 16):
    """Rank by quality, take the peak-frequency consensus among the pool, keep the
    best `n_fuse` whose own peak agrees with it. Rejects harmonic (2f) subcarriers."""
    score, peak_f = subcarrier_quality(x, fs, band)
    pool = np.argsort(score)[::-1][:n_pool]
    consensus = np.median(peak_f[pool])
    agree = pool[np.abs(peak_f[pool] - consensus) <= max(0.03, 0.18 * consensus)]
    if len(agree) < 3:
        agree = pool[:max(3, n_fuse)]
    return agree[np.argsort(score[agree])[::-1][:n_fuse]], score


def fuse_subcarriers(x: np.ndarray, cols: np.ndarray, weights: np.ndarray) -> np.ndarray:
    sel = x[:, cols]
    ref = sel[:, 0]
    signs = np.sign(np.array([np.dot(sel[:, j], ref) or 1.0 for j in range(sel.shape[1])]))
    sel = sel * signs
    z = (sel - sel.mean(axis=0)) / (sel.std(axis=0) + 1e-12)
    w = weights / (weights.sum() + 1e-12)
    return z @ w


# ---- stage 6: rate estimation ----------------------------------------------

def _peak_bpm(sig: np.ndarray, fs: float, band=RESP_BAND_HZ):
    sig = sig - sig.mean()
    w = np.hanning(len(sig))
    X = np.abs(np.fft.rfft(sig * w))
    f = np.fft.rfftfreq(len(sig), 1 / fs)
    m = (f >= band[0]) & (f <= band[1])
    if not m.any():
        return float("nan"), 0.0
    fb, Xb = f[m], X[m]
    ipk = int(np.argmax(Xb))
    # parabolic interpolation around the peak
    if 0 < ipk < len(Xb) - 1:
        y0, y1, y2 = Xb[ipk - 1], Xb[ipk], Xb[ipk + 1]
        denom = (y0 - 2 * y1 + y2)
        delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    else:
        delta = 0.0
    df = fb[1] - fb[0]
    f_est = fb[ipk] + delta * df

    # sub-harmonic guard: if there is real energy at ~f_est/2 still inside the
    # band, the true fundamental is the lower line (we locked onto the 2f term).
    half = f_est / 2.0
    if half >= band[0]:
        jhalf = int(np.argmin(np.abs(fb - half)))
        if Xb[jhalf] > 0.5 * Xb[ipk]:
            f_est = fb[jhalf]
            ipk = jhalf

    prominence = Xb[ipk] / (np.median(Xb) + 1e-12)
    confidence = float(np.clip((prominence - 1.0) / 9.0, 0.0, 1.0))
    return float(f_est * 60.0), confidence


def sliding_rate(fused: np.ndarray, fs: float, cfg: RespirationConfig):
    win = int(cfg.window_s * fs)
    hop = max(1, int(cfg.hop_s * fs))
    if len(fused) < win:
        bpm, conf = _peak_bpm(fused, fs, cfg.band)
        return np.array([len(fused) / (2 * fs)]), np.array([bpm]), np.array([conf])
    starts = np.arange(0, len(fused) - win + 1, hop)
    t = np.empty(len(starts))
    bpm = np.empty(len(starts))
    conf = np.empty(len(starts))
    for i, s in enumerate(starts):
        bpm[i], conf[i] = _peak_bpm(fused[s : s + win], fs, cfg.band)
        t[i] = (s + win / 2) / fs
    return t, bpm, conf


# ---- top-level ---------------------------------------------------------------

@dataclass
class RespirationResult:
    t: np.ndarray
    bpm: np.ndarray
    confidence: np.ndarray
    fused: np.ndarray
    fs: float
    selected: np.ndarray

    def summary_bpm(self) -> float:
        w = self.confidence / (self.confidence.sum() + 1e-12)
        finite = np.isfinite(self.bpm)
        if not finite.any():
            return float("nan")
        if w[finite].sum() == 0:
            return float(np.nanmedian(self.bpm))
        return float(np.sum(self.bpm[finite] * w[finite]) / w[finite].sum())


def estimate(amp: np.ndarray, host_ts: np.ndarray, cfg: Optional[RespirationConfig] = None,
             already_uniform: bool = False) -> RespirationResult:
    cfg = cfg or RespirationConfig()
    x = hampel(amp, cfg.hampel_win, cfg.hampel_sigma)

    if already_uniform:
        xu = x
        fs = cfg.fs
    else:
        t0 = host_ts - host_ts[0]
        n = int(np.floor(t0[-1] * cfg.fs)) + 1
        tu = np.arange(n) / cfg.fs
        xu = np.column_stack([np.interp(tu, t0, x[:, j]) for j in range(x.shape[1])])
        fs = cfg.fs

    min_samples = int(20 * fs)  # need >= 20 s of data for a meaningful spectrum
    if xu.shape[0] < min_samples:
        nan = np.array([np.nan])
        return RespirationResult(t=np.array([0.0]), bpm=nan, confidence=np.array([0.0]),
                                 fused=np.zeros(xu.shape[0]), fs=fs,
                                 selected=np.arange(min(cfg.n_fuse, xu.shape[1])))

    resid = pca_background_subtract(xu, cfg.pca_keep)
    filt = bandpass(resid, fs, cfg.band)
    selected, score = select_consensus(filt, fs, cfg.band, cfg.n_fuse)
    fused = fuse_subcarriers(filt, selected, score[selected])
    t, bpm, conf = sliding_rate(fused, fs, cfg)
    return RespirationResult(t=t, bpm=bpm, confidence=conf, fused=fused, fs=fs, selected=selected)


def estimate_from_recording(rec: csi_io.CSIRecording,
                            cfg: Optional[RespirationConfig] = None) -> RespirationResult:
    amp = normalized_amplitude(rec, active_only=True)
    return estimate(amp, rec.host_ts, cfg)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Estimate respiration rate from a CSI recording.")
    p.add_argument("recording")
    p.add_argument("--fs", type=float, default=20.0)
    p.add_argument("--window", type=float, default=45.0)
    p.add_argument("--truth-bpm", type=float, help="known rate, prints error")
    p.add_argument("--phyphox", help="Phyphox accelerometer CSV for ground truth")
    args = p.parse_args(argv)

    cfg = RespirationConfig(fs=args.fs, window_s=args.window)
    rec = csi_io.load(args.recording)
    res = estimate_from_recording(rec, cfg)

    print(f"summary bpm   : {res.summary_bpm():.2f}")
    print(f"windows       : {len(res.t)}  (mean conf {np.nanmean(res.confidence):.2f})")
    print(f"fused from SCs : {sorted(rec.active[res.selected].tolist())}")
    for tt, bb, cc in zip(res.t, res.bpm, res.confidence):
        print(f"  t={tt:6.1f}s  bpm={bb:5.1f}  conf={cc:.2f}")

    truth = args.truth_bpm
    if args.phyphox:
        from csi_sensing.reference import load_phyphox, reference_bpm

        ref = load_phyphox(args.phyphox)
        truth = reference_bpm(ref, band=cfg.band)
        print(f"phyphox bpm   : {truth:.2f}")
    if truth is not None:
        print(f"ABS ERROR     : {abs(res.summary_bpm() - truth):.2f} bpm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
