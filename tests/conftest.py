import numpy as np
import pytest

from csi_sensing.synth import Segment, SynthConfig, generate, scenario


@pytest.fixture
def sitting_csv(tmp_path):
    def _make(bpm=15.0, duration=150.0, wall=False, seed=0, pair_order="im_re"):
        cfg = scenario("sitting", duration=duration, fs=100.0, breathing_bpm=bpm,
                       wall=wall, seed=seed)
        cfg = SynthConfig(**{**cfg.__dict__, "pair_order": pair_order})
        res = generate(cfg)
        path = tmp_path / f"sitting_{bpm}_{pair_order}.csv"
        res.to_csv(str(path))
        res.write_meta(str(path) + ".meta.json")
        return str(path), res
    return _make


@pytest.fixture
def scenario_csv(tmp_path):
    def _make(name, duration=180.0, bpm=15.0, seed=0):
        res = generate(scenario(name, duration=duration, fs=100.0, breathing_bpm=bpm, seed=seed))
        path = tmp_path / f"{name}_{seed}.csv"
        res.to_csv(str(path))
        return str(path), res
    return _make
