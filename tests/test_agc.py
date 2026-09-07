import numpy as np

from csi_sensing import csi_io
from csi_sensing.agc import diagnostic_series, flatness_gain, normalize_amplitude
from csi_sensing.synth import SynthConfig, Segment, generate, scenario


def test_normalize_removes_known_gain():
    true_amp = 2.0
    gain = np.array([0, 6, 12, 0, 6, 12, 0, 6, 12, 0], dtype=float)
    observed = np.full((10, 4), true_amp) * (10 ** (gain / 20.0))[:, None]
    norm = normalize_amplitude(observed, gain)
    # dividing out the gain recovers the constant true amplitude
    assert np.allclose(norm, true_amp, atol=1e-9)


def test_flatness_gain_on_static_recording(tmp_path):
    cfg = SynthConfig(duration=90, fs=100, breathing_bpm=15,
                      segments=[Segment(0, 90, "still")],
                      agc_levels_db=(0.0, 4.0), agc_step_period_s=12)
    res = generate(cfg)
    p = tmp_path / "still.csv"
    res.to_csv(str(p))
    rec = csi_io.load(str(p))

    d = diagnostic_series(rec)
    cv = lambda x: np.std(x) / np.mean(x)
    assert cv(d["norm_amp"]) < cv(d["raw_amp"])
    assert flatness_gain(rec) > 2.0     # blind corrector: clear but not exact
