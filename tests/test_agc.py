import numpy as np

from csi_sensing import csi_io
from csi_sensing.agc import (
    diagnostic_series, flatness_gain, normalize_amplitude, normalize_blind,
)
from csi_sensing.synth import Segment, SynthConfig, generate, scenario


def test_normalize_removes_known_gain():
    true_amp = 2.0
    gain = np.array([0, 6, 12, 0, 6, 12, 0, 6, 12, 0], dtype=float)
    observed = np.full((10, 4), true_amp) * (10 ** (gain / 20.0))[:, None]
    norm = normalize_amplitude(observed, gain)
    assert np.allclose(norm, true_amp, atol=1e-9)


def test_blind_removes_slow_common_mode_step():
    n, s, fs = 3000, 8, 100.0
    rng = np.random.default_rng(0)
    base = rng.uniform(20, 60, s)
    amp = np.tile(base, (n, 1)) + rng.normal(0, 1.0, (n, s))
    amp[n // 2 :] *= 1.6                       # a slow common-mode gain step
    out = normalize_blind(amp, fs=fs)

    cv = lambda x: np.std(x.mean(1)) / np.mean(x.mean(1))
    assert cv(out) < 0.4 * cv(amp)             # step largely removed
    # per-subcarrier structure preserved (ratios between subcarriers unchanged)
    assert np.allclose(out.mean(0) / out.mean(0)[0], amp.mean(0) / amp.mean(0)[0], atol=0.05)


def test_blind_is_noop_on_stable_input():
    rng = np.random.default_rng(1)
    amp = rng.uniform(30, 50, (2000, 6)) * 0 + 40 + rng.normal(0, 0.5, (2000, 6))
    out = normalize_blind(amp, fs=100.0)
    assert np.allclose(out, amp)               # <10% swing -> untouched


def test_static_recording_amplitude_is_stable(tmp_path):
    res = generate(SynthConfig(duration=60, fs=100, breathing_bpm=15,
                               segments=[Segment(0, 60, "still")]))
    p = tmp_path / "still.csv"
    res.to_csv(str(p))
    rec = csi_io.load(str(p))
    d = diagnostic_series(rec)
    cv = lambda x: np.std(x) / np.mean(x)
    # ESP32 AGC keeps amplitude stable on a static link; blind must not worsen it
    assert cv(d["norm_amp"]) <= cv(d["raw_amp"]) + 1e-6
    assert 0.8 < flatness_gain(rec) < 3.0
