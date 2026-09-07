"""Synthetic CSI generator with known ground truth.

Produces data in exactly the capture-CSV schema (`csi_sensing.CAPTURE_COLUMNS`)
so every downstream stage can be exercised and scored before real recordings
exist. The physical model is deliberately simple but has the right structure:

  * a static direct path plus a few static multipath reflections (walls/furniture)
  * one *dynamic* reflection whose path length is modulated sinusoidally by
    breathing  ->  small amplitude ripple across subcarriers
  * "motion" windows add a large random-walking path  ->  broadband variance
  * ~52 of 64 subcarriers active; the rest are guard/DC nulls (near zero)
  * per-packet AGC gain steps multiply the observed amplitude
  * complex Gaussian receiver noise, then int8 quantization
  * jittery packet arrival and random drops
  * a `wall` flag attenuates every path and lowers SNR (through-wall proxy)

Everything the scorers need to check against is returned in `SynthResult.truth`.
"""
from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

import numpy as np
import pandas as pd

from csi_sensing import CAPTURE_COLUMNS
from csi_sensing.serial_format import FIELD_SPEC, format_line

C = 299_792_458.0                     # m/s
SUBCARRIER_SPACING = 312_500.0        # Hz, 20 MHz OFDM
N_SUB = 64
CENTER_FREQ = 2.437e9                 # channel 6

# Guard-band + DC null subcarrier positions (array index 0..63). ~52 active.
DEFAULT_NULL_IDX = tuple(list(range(0, 6)) + [32] + list(range(59, 64)))

PairOrder = Literal["im_re", "re_im"]
Motion = Literal["move", "still"]


@dataclass
class Segment:
    """A time interval [t0, t1) with a subject present, moving or still."""
    t0: float
    t1: float
    motion: Motion = "still"


@dataclass
class SynthConfig:
    duration: float = 120.0
    fs: float = 100.0                 # nominal packet rate (Hz)
    breathing_bpm: Optional[float] = 15.0
    breathing_amp_mm: float = 4.0     # chest-driven path-length swing
    segments: Sequence[Segment] = field(default_factory=list)
    wall: bool = False
    wall_atten_db: float = 9.0
    channel: int = 6
    mac: str = "7c:9e:bd:00:11:22"
    pair_order: PairOrder = "im_re"
    null_idx: Sequence[int] = DEFAULT_NULL_IDX
    jitter_s: float = 0.002           # std of packet-arrival jitter
    drop_rate: float = 0.01           # fraction of packets lost
    noise_floor_dbm: int = -95
    agc_step_period_s: float = 15.0   # AGC toggles on this cadence
    agc_levels_db: Sequence[float] = (0.0, 3.0)   # residual gain error left by coarse AGC
    seed: int = 0

    @property
    def f_breath(self) -> Optional[float]:
        return None if self.breathing_bpm is None else self.breathing_bpm / 60.0


@dataclass
class SynthResult:
    df: pd.DataFrame
    config: SynthConfig
    truth: dict

    def to_csv(self, path: str) -> None:
        self.df.to_csv(path, index=False)

    def to_serial_lines(self) -> list[str]:
        """Render rows as esp-csi FIELD_SPEC serial lines (for round-trip tests)."""
        lines = []
        for _, row in self.df.iterrows():
            rec = {name: row[name] for name, _ in FIELD_SPEC}
            rec["data"] = [int(v) for v in str(row["data"]).split()]
            lines.append(format_line(rec))
        return lines

    def write_meta(self, path: str, **overrides) -> None:
        import json

        meta = {
            "label": self.truth["label"],
            "channel": self.config.channel,
            "board_separation_m": 2.0,
            "wall_present": self.config.wall,
            "subject_position": "between boards" if self.truth["any_presence"] else "none",
            "start_time": float(self.df["host_ts"].iloc[0]),
            "firmware_sha": "SYNTHETIC",
            "synthetic": True,
            "breathing_bpm": self.config.breathing_bpm,
        }
        meta.update(overrides)
        with open(path, "w") as fh:
            json.dump(meta, fh, indent=2)


def _paths_at(t: float, cfg: SynthConfig, rng: np.random.Generator, walk_state: dict,
              drift: float = 0.0):
    """Return (amplitudes, delays_seconds) for all propagation paths at time t.

    `drift` is a slow (<0.1 Hz) common path-length wander in metres -- ambient
    conditions, tiny reflector motion, thermal. It dominates the temporal
    variance, so it lands in PCA component 0 (which the pipeline discards).
    """
    atten = 10 ** (-cfg.wall_atten_db / 20.0) if cfg.wall else 1.0

    amps = [1.0 * atten * (1.0 + 1.5 * drift)]            # direct path, slow wobble
    delays = [(3.0 + drift) / C]                          # ~3 m
    # static multipath, all riding the same slow drift
    for d, a in ((4.7, 0.45), (6.1, 0.30), (8.0, 0.20)):
        amps.append(a * atten)
        delays.append((d + 0.7 * drift) / C)

    seg = _segment_at(t, cfg.segments)
    if seg is not None:
        # dynamic breathing path
        if cfg.f_breath is not None:
            swing = cfg.breathing_amp_mm * 1e-3 * np.sin(2 * np.pi * cfg.f_breath * t)
            d_p = 5.2 + swing
            amps.append(0.42 * atten * (0.55 if cfg.wall else 1.0))
            delays.append(d_p / C)
        # motion path: random walk in path length
        if seg.motion == "move":
            walk_state["d"] = walk_state.get("d", 5.5) + rng.normal(0, 0.06)
            walk_state["d"] = float(np.clip(walk_state["d"], 3.0, 9.0))
            amps.append(0.55 * atten)
            delays.append(walk_state["d"] / C)
    return np.array(amps), np.array(delays)


def _segment_at(t: float, segments: Sequence[Segment]) -> Optional[Segment]:
    for s in segments:
        if s.t0 <= t < s.t1:
            return s
    return None


def _agc_gain_db(t: float, cfg: SynthConfig) -> float:
    idx = int(t // cfg.agc_step_period_s) % len(cfg.agc_levels_db)
    return float(cfg.agc_levels_db[idx])


def generate(cfg: SynthConfig) -> SynthResult:
    rng = np.random.default_rng(cfg.seed)
    k = np.arange(N_SUB) - N_SUB // 2                 # -32..31
    f_k = CENTER_FREQ + k * SUBCARRIER_SPACING
    active_mask = np.ones(N_SUB, dtype=bool)
    active_mask[list(cfg.null_idx)] = False

    # jittered, occasionally-dropped arrival times
    n_nom = int(cfg.duration * cfg.fs)
    ideal = np.arange(n_nom) / cfg.fs
    jitter = rng.normal(0, cfg.jitter_s, n_nom)
    times = np.sort(np.clip(ideal + jitter, 0, cfg.duration))
    keep = rng.random(n_nom) >= cfg.drop_rate
    times = times[keep]

    host_t0 = 1_700_000_000.0
    walk_state: dict = {}
    rows = []
    noise_sigma = 0.02 * 10 ** ((cfg.noise_floor_dbm + 95) / 20.0)

    # slow common drift trajectory: a few low-frequency sinusoids (0.004-0.05 Hz),
    # strictly below the respiration band so nothing leaks in for the empty case.
    # It still dominates the temporal variance -> PCA component 0.
    drift = np.zeros(len(times))
    for _ in range(4):
        fr = rng.uniform(0.004, 0.03)
        ph = rng.uniform(0, 2 * np.pi)
        drift += rng.uniform(0.4, 1.0) * np.sin(2 * np.pi * fr * times + ph)
    drift = 0.006 * drift / (np.std(drift) + 1e-9)   # ~6 mm rms common wander

    # Fixed hardware scale for the whole recording. It must NOT be recomputed per
    # packet -- that would divide the AGC gain back out and the normalization step
    # would have nothing to correct. Calibrate once from a gain-free reference
    # packet so a typical active bin sits mid-range in int8.
    ref_amps, ref_delays = _paths_at(0.0, cfg, rng, {})
    ref_H = (ref_amps[None, :] * np.exp(-2j * np.pi * np.outer(f_k, ref_delays))).sum(axis=1)
    hw_scale = 55.0 / (np.median(np.abs(ref_H[active_mask])) + 1e-9)

    for seq, t in enumerate(times):
        amps, delays = _paths_at(t, cfg, rng, walk_state, drift=float(drift[seq]))
        # H[k] = sum_p a_p exp(-j 2 pi f_k tau_p)
        phasors = amps[None, :] * np.exp(-2j * np.pi * np.outer(f_k, delays))
        H = phasors.sum(axis=1)
        H[~active_mask] = 0.0

        gain = 10 ** (_agc_gain_db(t, cfg) / 20.0)
        noise = (rng.normal(0, noise_sigma, N_SUB) + 1j * rng.normal(0, noise_sigma, N_SUB))
        noise[~active_mask] = 0.0
        obs = (H + noise) * gain * hw_scale

        re = np.clip(np.round(obs.real), -128, 127).astype(np.int8)
        im = np.clip(np.round(obs.imag), -128, 127).astype(np.int8)

        if cfg.pair_order == "im_re":
            interleaved = np.empty(2 * N_SUB, dtype=np.int8)
            interleaved[0::2] = im
            interleaved[1::2] = re
        else:
            interleaved = np.empty(2 * N_SUB, dtype=np.int8)
            interleaved[0::2] = re
            interleaved[1::2] = im

        rows.append(
            {
                "host_ts": host_t0 + t,
                "type": "CSI_DATA",
                "id": seq,
                "mac": cfg.mac,
                "rssi": int(-40 - (cfg.wall_atten_db if cfg.wall else 0) + rng.integers(-2, 3)),
                "rate": 11,
                "sig_mode": 1,
                "mcs": 7,
                "bandwidth": 0,
                "smoothing": 0,
                "not_sounding": 1,
                "aggregation": 0,
                "stbc": 0,
                "fec_coding": 0,
                "sgi": 1,
                "noise_floor": cfg.noise_floor_dbm + int(rng.integers(-1, 2)),
                "ampdu_cnt": 0,
                "channel": cfg.channel,
                "secondary_channel": 0,
                "local_timestamp": int(t * 1e6),
                "ant": 0,
                "sig_len": 52,
                "rx_format": 1,
                "agc_gain": int(round(_agc_gain_db(t, cfg))),
                "fft_gain": 8,
                "len": 2 * N_SUB,
                "first_word": 0,
                "data": " ".join(str(int(v)) for v in interleaved),
            }
        )

    df = pd.DataFrame(rows, columns=CAPTURE_COLUMNS)

    any_presence = len(cfg.segments) > 0
    truth = {
        "label": _label_for(cfg),
        "fs_nominal": cfg.fs,
        "breathing_bpm": cfg.breathing_bpm,
        "any_presence": any_presence,
        "presence_intervals": [(s.t0, s.t1, s.motion) for s in cfg.segments],
        "pair_order": cfg.pair_order,
        "active_idx": np.where(active_mask)[0].tolist(),
        "null_idx": list(cfg.null_idx),
        "host_t0": host_t0,
        "wall": cfg.wall,
    }
    return SynthResult(df=df, config=cfg, truth=truth)


def _label_for(cfg: SynthConfig) -> str:
    if not cfg.segments:
        return "empty"
    if any(s.motion == "move" for s in cfg.segments):
        return "walking"
    return "sitting"


# ---- convenience scenario builders -------------------------------------------------

def scenario(name: str, duration: float = 120.0, fs: float = 100.0,
             breathing_bpm: float = 15.0, wall: bool = False, seed: int = 0) -> SynthConfig:
    name = name.lower()
    if name == "empty":
        segs: list[Segment] = []
    elif name == "walking":
        segs = [Segment(0.15 * duration, 0.85 * duration, "move")]
    elif name in ("sitting", "still"):
        segs = [Segment(0.0, duration, "still")]
    elif name == "mixed":
        segs = [
            Segment(0.10 * duration, 0.30 * duration, "move"),
            Segment(0.45 * duration, 0.70 * duration, "still"),
            Segment(0.80 * duration, 0.95 * duration, "move"),
        ]
    else:
        raise ValueError(f"unknown scenario {name!r}")
    return SynthConfig(duration=duration, fs=fs, breathing_bpm=breathing_bpm,
                       segments=segs, wall=wall, seed=seed)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate a synthetic CSI recording.")
    p.add_argument("--scenario", default="mixed",
                   choices=["empty", "walking", "sitting", "still", "mixed"])
    p.add_argument("--duration", type=float, default=120.0)
    p.add_argument("--fs", type=float, default=100.0)
    p.add_argument("--bpm", type=float, default=15.0, help="breathing rate")
    p.add_argument("--wall", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--pair-order", default="im_re", choices=["im_re", "re_im"])
    p.add_argument("--out", required=True, help="output CSV path")
    p.add_argument("--meta", action="store_true", help="also write <out>.meta.json")
    args = p.parse_args(argv)

    cfg = scenario(args.scenario, args.duration, args.fs, args.bpm, args.wall, args.seed)
    cfg = dataclasses.replace(cfg, pair_order=args.pair_order)
    res = generate(cfg)
    res.to_csv(args.out)
    if args.meta:
        res.write_meta(args.out + ".meta.json")
    rate = len(res.df) / args.duration
    print(f"[SYNTHETIC] wrote {len(res.df)} rows to {args.out}  "
          f"(~{rate:.1f} pkt/s, label={res.truth['label']}, bpm={args.bpm}, wall={args.wall})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
