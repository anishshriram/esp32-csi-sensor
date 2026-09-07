"""Load a capture CSV into a complex CSI array plus a metadata DataFrame.

Design rules (from the work order):
  * The interleaved int8 pair order (imag,real vs real,imag) is DERIVED from the
    data, not assumed. esp-csi documents (imag,real); we confirm per file.
  * The active subcarrier set is DERIVED by finding consistently near-zero
    columns (guard bands + DC), not hardcoded. The chosen indices are logged.
  * Every rx_ctrl column from the CSV is kept in `meta`.
  * CSI phase is exposed but is NOT usable for sensing on a single-antenna ESP32
    (per-packet CFO/SFO). Do not build on it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PairOrder = str  # "im_re" | "re_im"


@dataclass
class CSIRecording:
    csi: np.ndarray          # (N, S) complex64
    meta: pd.DataFrame       # (N, ...) all non-data columns, incl. host_ts
    active: np.ndarray       # int indices of active subcarriers
    pair_order: PairOrder
    path: str = ""

    @property
    def host_ts(self) -> np.ndarray:
        return self.meta["host_ts"].to_numpy(dtype=float)

    @property
    def n(self) -> int:
        return self.csi.shape[0]

    def amplitude(self, active_only: bool = False) -> np.ndarray:
        a = np.abs(self.csi)
        return a[:, self.active] if active_only else a

    def phase(self, active_only: bool = False, unwrap: bool = True) -> np.ndarray:
        """Raw CSI phase. Exposed for inspection only -- not a sensing input."""
        p = np.angle(self.csi)
        if unwrap:
            p = np.unwrap(p, axis=1)
        return p[:, self.active] if active_only else p

    def packet_rate(self) -> float:
        t = self.host_ts
        return (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 else float("nan")

    def resample_uniform(self, fs: float, active_only: bool = True):
        """Interpolate onto a uniform time grid at `fs` Hz using host timestamps.

        Returns (t_uniform, csi_uniform). Real and imag parts are interpolated
        separately; packet arrival is jittery and the spectral stage needs
        uniform sampling.
        """
        t = self.host_ts
        t = t - t[0]
        n = int(np.floor(t[-1] * fs)) + 1
        tu = np.arange(n) / fs
        src = self.csi[:, self.active] if active_only else self.csi
        re = np.empty((n, src.shape[1]))
        im = np.empty((n, src.shape[1]))
        for j in range(src.shape[1]):
            re[:, j] = np.interp(tu, t, src[:, j].real)
            im[:, j] = np.interp(tu, t, src[:, j].imag)
        return tu, (re + 1j * im).astype(np.complex64)


def _parse_data_column(series: pd.Series) -> np.ndarray:
    """Space-separated int8 strings -> (N, 2*S) int array."""
    rows = [np.fromstring(s, sep=" ", dtype=np.int64) for s in series.astype(str)]
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        # keep only the modal width; drop malformed rows
        from collections import Counter

        common = Counter(len(r) for r in rows).most_common(1)[0][0]
        rows = [r for r in rows if len(r) == common]
        log.warning("csi_io: dropped rows with off-width CSI payloads; kept width=%d", common)
    return np.vstack(rows)


def _to_complex(raw: np.ndarray, order: PairOrder) -> np.ndarray:
    a = raw[:, 0::2].astype(np.float64)
    b = raw[:, 1::2].astype(np.float64)
    if order == "im_re":
        return (b + 1j * a).astype(np.complex64)      # (imag, real)
    return (a + 1j * b).astype(np.complex64)           # (real, imag)


def detect_pair_order(raw: np.ndarray, active: np.ndarray) -> PairOrder:
    """Pick the interleaving that yields a causal power-delay profile.

    Swapping real/imag conjugates H, which time-reverses its impulse response:
    the correct order concentrates energy at small positive lags (early taps
    within the cyclic prefix); the wrong order pushes the peak to wrapped-around
    negative lags.
    """
    scores = {}
    for order in ("im_re", "re_im"):
        H = _to_complex(raw, order)
        h = np.fft.ifft(H[:, active], axis=1)
        pdp = (np.abs(h) ** 2).mean(axis=0)
        L = len(pdp)
        # The wrong order conjugates H, which time-reverses the impulse response:
        # bin k -> bin (L-k) mod L. Physical (causal) taps sit in the first half;
        # the conjugate pushes them into the second half. Compare the two halves.
        first_half = pdp[1 : L // 2].sum()
        second_half = pdp[L // 2 + 1 :].sum()
        scores[order] = float((first_half - second_half) / (first_half + second_half + 1e-12))
    best = max(scores, key=scores.get)
    log.info("csi_io: derived I/Q pair order = %s (scores=%s)", best, scores)
    return best


def derive_active_subcarriers(raw_complex: np.ndarray, rel_threshold: float = 0.05) -> np.ndarray:
    """Columns whose median magnitude exceeds `rel_threshold` * (median active)."""
    med = np.median(np.abs(raw_complex), axis=0)
    ref = np.median(med[med > 0]) if np.any(med > 0) else 1.0
    active = np.where(med > rel_threshold * ref)[0]
    log.info("csi_io: derived %d active subcarriers: %s", len(active), active.tolist())
    return active


def load(path: str, pair_order: str | None = None) -> CSIRecording:
    df = pd.read_csv(path)
    if "host_ts" not in df.columns:
        raise ValueError(f"{path}: missing host_ts column (not a capture CSV?)")
    df = df.sort_values("host_ts").reset_index(drop=True)

    raw = _parse_data_column(df["data"])
    if len(raw) != len(df):
        df = df.iloc[: len(raw)].reset_index(drop=True)

    # provisional complex (order-agnostic magnitude) to find active set
    provisional = _to_complex(raw, "im_re")
    active = derive_active_subcarriers(provisional)

    order = pair_order or detect_pair_order(raw, active)
    csi = _to_complex(raw, order)

    meta = df.drop(columns=["data"])
    return CSIRecording(csi=csi, meta=meta, active=active, pair_order=order, path=path)
