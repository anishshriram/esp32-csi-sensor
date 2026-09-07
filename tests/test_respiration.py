import numpy as np
import pytest

from csi_sensing import csi_io
from csi_sensing.respiration import (
    RespirationConfig, bandpass, estimate_from_recording, hampel, pca_background_subtract,
)
from csi_sensing.metrics import respiration_mae


@pytest.mark.parametrize("bpm", [10, 12, 15, 18, 20])
def test_recovers_metronome_rate(sitting_csv, bpm):
    path, _ = sitting_csv(bpm=bpm, duration=160)
    res = estimate_from_recording(csi_io.load(path))
    assert abs(res.summary_bpm() - bpm) <= 1.5
    assert np.nanmean(res.confidence) > 0.3


def test_overall_mae_under_one_bpm(sitting_csv):
    est = {}
    for bpm in (10, 12, 15, 18, 20):
        path, _ = sitting_csv(bpm=bpm, duration=160)
        est[bpm] = [estimate_from_recording(csi_io.load(path)).summary_bpm()]
    assert respiration_mae(est)["overall_mae"] < 1.0


def test_hampel_removes_spikes():
    x = np.sin(np.linspace(0, 20, 400))
    x[100] += 12.0
    x[250] -= 9.0
    y = hampel(x, 7, 3.0)
    assert abs(y[100]) < 2 and abs(y[250]) < 2
    assert np.allclose(y[np.r_[0:90, 110:240]], x[np.r_[0:90, 110:240]], atol=1e-9)


def test_pca_drops_dominant_static_component():
    t = np.linspace(0, 60, 1200)
    static = np.outer(5 * np.sin(2 * np.pi * 0.01 * t), np.ones(10))
    breath = np.outer(0.2 * np.sin(2 * np.pi * 0.25 * t), np.random.default_rng(0).normal(1, 0.1, 10))
    resid = pca_background_subtract(static + breath, (1, 4))
    assert np.var(resid) < np.var(static)
    # breathing frequency survives
    f = np.fft.rfftfreq(len(t), t[1] - t[0])
    P = np.abs(np.fft.rfft(resid[:, 0])) ** 2
    assert 0.2 < f[np.argmax(P)] < 0.3


def test_through_wall_lowers_confidence(sitting_csv):
    los_path, _ = sitting_csv(bpm=15, duration=160, wall=False)
    wall_path, _ = sitting_csv(bpm=15, duration=160, wall=True)
    c_los = np.nanmean(estimate_from_recording(csi_io.load(los_path)).confidence)
    c_wall = np.nanmean(estimate_from_recording(csi_io.load(wall_path)).confidence)
    assert c_wall <= c_los + 1e-6
