"""Phase 2.3 AGC validation -- three panels sharing an x-axis:

    raw amplitude (one subcarrier) | agc_gain over time | normalized amplitude

On a static recording, steps in the raw trace should line up with gain changes
and flatten in the bottom panel. If they do not, stop and check the gain-to-dB
scaling in csi_sensing/agc.py -- everything downstream depends on it.
"""
from __future__ import annotations

import argparse

import matplotlib.pyplot as plt

from csi_sensing import csi_io
from csi_sensing.agc import diagnostic_series, flatness_gain
from csi_sensing.plots._common import title_from_meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("--out", default=None)
    p.add_argument("--subcarrier", type=int, default=None)
    args = p.parse_args(argv)

    rec = csi_io.load(args.csv)
    d = diagnostic_series(rec, args.subcarrier)
    fg = flatness_gain(rec)

    fig, ax = plt.subplots(3, 1, sharex=True, figsize=(11, 7))
    ax[0].plot(d["t"], d["raw_amp"], lw=0.6)
    ax[0].set_ylabel(f"raw |CSI|\nsc {d['subcarrier']}")
    ax[1].step(d["t"], d["agc_gain"], where="post", color="tab:orange")
    ax[1].set_ylabel("agc_gain")
    ax[2].plot(d["t"], d["norm_amp"], lw=0.6, color="tab:green")
    ax[2].set_ylabel("normalized |CSI|")
    ax[2].set_xlabel("time (s)")
    fig.suptitle(title_from_meta(args.csv, "AGC diagnostic") +
                 f"   flatness gain = {fg:.1f}x  ({'OK' if fg > 2 else 'CHECK SCALING'})")
    fig.tight_layout()
    out = args.out or (args.csv.rsplit(".", 1)[0] + "_agc.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}  (flatness gain {fg:.1f}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
