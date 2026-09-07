"""Phase 2.4 CSI amplitude heatmap: subcarrier (y) vs time (x).

AGC-normalized. Per-subcarrier robust display scaling (median / IQR) so strong
subcarriers do not swamp weak ones. Title from the sidecar metadata.
"""
from __future__ import annotations

import argparse

import numpy as np
import matplotlib.pyplot as plt

from csi_sensing import csi_io
from csi_sensing.agc import normalized_amplitude
from csi_sensing.plots._common import title_from_meta


def robust_scale(amp: np.ndarray) -> np.ndarray:
    med = np.median(amp, axis=0, keepdims=True)
    q1, q3 = np.percentile(amp, [25, 75], axis=0, keepdims=True)
    iqr = np.where((q3 - q1) > 0, q3 - q1, 1.0)
    return (amp - med) / iqr


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("--out", default=None)
    p.add_argument("--clip", type=float, default=4.0, help="color scale in IQR units")
    args = p.parse_args(argv)

    rec = csi_io.load(args.csv)
    amp = normalized_amplitude(rec, active_only=True)
    disp = robust_scale(amp)
    t = rec.host_ts - rec.host_ts[0]

    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(disp.T, aspect="auto", origin="lower", cmap="magma",
                   vmin=-args.clip, vmax=args.clip,
                   extent=[t[0], t[-1], 0, len(rec.active)])
    ax.set_xlabel("time (s)")
    ax.set_ylabel("active subcarrier index")
    ax.set_yticks(np.arange(len(rec.active)) + 0.5)
    ax.set_yticklabels(rec.active, fontsize=5)
    fig.colorbar(im, ax=ax, label="normalized amplitude (robust, IQR units)")
    ax.set_title(title_from_meta(args.csv, "CSI heatmap"))
    fig.tight_layout()
    out = args.out or (args.csv.rsplit(".", 1)[0] + "_heatmap.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
