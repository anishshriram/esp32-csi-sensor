"""Phase 4 respiration figure: fused waveform, its spectrum, and rate-over-time
(optionally against a Phyphox reference)."""
from __future__ import annotations

import argparse

import numpy as np
import matplotlib.pyplot as plt

from csi_sensing import csi_io
from csi_sensing.respiration import RespirationConfig, estimate_from_recording
from csi_sensing.plots._common import title_from_meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv")
    p.add_argument("--out", default=None)
    p.add_argument("--phyphox", default=None)
    p.add_argument("--truth-bpm", type=float, default=None)
    p.add_argument("--window", type=float, default=45.0)
    args = p.parse_args(argv)

    rec = csi_io.load(args.csv)
    cfg = RespirationConfig(window_s=args.window)
    res = estimate_from_recording(rec, cfg)

    truth = args.truth_bpm
    ref_series = None
    if args.phyphox:
        from csi_sensing.reference import load_phyphox, reference_bpm

        ref = load_phyphox(args.phyphox)
        truth = reference_bpm(ref, band=cfg.band)
        ref_series = ref

    fig, ax = plt.subplots(3, 1, figsize=(11, 8))
    tt = np.arange(len(res.fused)) / res.fs
    ax[0].plot(tt, res.fused, lw=0.7)
    ax[0].set_title("fused respiration waveform")
    ax[0].set_xlabel("s")

    sig = res.fused - res.fused.mean()
    X = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
    f = np.fft.rfftfreq(len(sig), 1 / res.fs) * 60
    ax[1].plot(f, X)
    ax[1].set_xlim(0, 40)
    ax[1].axvspan(cfg.band[0] * 60, cfg.band[1] * 60, color="k", alpha=0.06)
    if truth:
        ax[1].axvline(truth, color="tab:red", ls="--", label=f"reference {truth:.1f}")
        ax[1].legend()
    ax[1].set_title("spectrum")
    ax[1].set_xlabel("breaths/min")

    ax[2].plot(res.t, res.bpm, "-o", ms=3, label="CSI estimate")
    ax[2].scatter(res.t, res.bpm, c=res.confidence, cmap="viridis", s=18, zorder=3)
    if truth:
        ax[2].axhline(truth, color="tab:red", ls="--", label=f"reference {truth:.1f}")
    ax[2].set_ylim(0, 40)
    ax[2].set_title(f"rate over time   (summary {res.summary_bpm():.1f} bpm"
                    + (f", |err| {abs(res.summary_bpm() - truth):.2f}" if truth else "") + ")")
    ax[2].set_xlabel("s")
    ax[2].legend()

    fig.suptitle(title_from_meta(args.csv, "Respiration"))
    fig.tight_layout()
    out = args.out or (args.csv.rsplit(".", 1)[0] + "_resp.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}  summary {res.summary_bpm():.2f} bpm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
