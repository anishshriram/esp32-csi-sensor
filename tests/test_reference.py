import numpy as np
import pandas as pd

from csi_sensing.reference import align, load_phyphox, reference_bpm


def _write_phyphox(path, bpm=15.0, dur=120.0, fs=50.0, offset=0.0):
    t = np.arange(0, dur, 1 / fs)
    f = bpm / 60.0
    chest = np.sin(2 * np.pi * f * t)
    # a sharp shared "deep breaths" burst near the start
    burst = np.exp(-((t - 5) ** 2) / 2.0) * np.sin(2 * np.pi * 0.4 * t) * 3
    z = 9.81 + 0.05 * (chest + burst)
    df = pd.DataFrame({
        "Time (s)": t + offset,
        "Acceleration x (m/s^2)": 0.01 * np.random.default_rng(0).normal(size=len(t)),
        "Acceleration y (m/s^2)": 0.01 * np.random.default_rng(1).normal(size=len(t)),
        "Acceleration z (m/s^2)": z,
    })
    df.to_csv(path, index=False)


def test_load_and_reference_bpm(tmp_path):
    p = tmp_path / "phyphox.csv"
    _write_phyphox(str(p), bpm=15.0)
    ref = load_phyphox(str(p))
    assert abs(reference_bpm(ref) - 15.0) < 1.0


def test_align_recovers_clock_offset(tmp_path):
    p = tmp_path / "phyphox.csv"
    _write_phyphox(str(p), bpm=15.0, dur=120)
    ref = load_phyphox(str(p))

    # CSI-side signal on the host clock, running 7 s ahead of the phone: the
    # shared event at phone-time 5 s lands at host-time 12 s here.
    true_offset = 7.0
    fs = 20.0
    tc = np.arange(0, 120, 1 / fs)
    f = 15 / 60.0
    event_host_t = 5.0 + true_offset
    burst = np.exp(-((tc - event_host_t) ** 2) / 2.0) * np.sin(2 * np.pi * 0.4 * tc) * 3
    csi_sig = np.sin(2 * np.pi * f * tc) + burst

    est = align(tc, csi_sig, ref, max_offset_s=20.0)
    # align returns the offset to ADD to ref.t to line up with csi_t
    assert abs(est - true_offset) < 1.5
