import numpy as np

from csi_sensing import csi_io, presence
from csi_sensing.metrics import intervals_to_mask, score_presence


def _score(path, res, thr, assist=False):
    rec = csi_io.load(path)
    tw, _, flags = presence.detect(rec, presence.PresenceConfig(), thr, respiration_assist=assist)
    truth = intervals_to_mask([(a, b) for a, b, *_ in res.truth["presence_intervals"]], tw)
    return score_presence(flags, truth, tw)


def test_walking_detected_empty_quiet(scenario_csv):
    empty_path, _ = scenario_csv("empty", duration=120)
    thr = presence.calibrate_threshold(csi_io.load(empty_path), presence.PresenceConfig())

    walk_path, walk_res = scenario_csv("walking", duration=180)
    s = _score(walk_path, walk_res, thr)
    assert s.accuracy > 0.9
    assert s.false_negative_rate < 0.1
    assert s.detection_latency_s < 5.0

    empty_res_path, empty_res = scenario_csv("empty", duration=150, seed=2)
    s0 = _score(empty_res_path, empty_res, thr)
    assert s0.false_positive_rate < 0.05


def test_sitting_needs_respiration_assist(scenario_csv):
    empty_path, _ = scenario_csv("empty", duration=120)
    thr = presence.calibrate_threshold(csi_io.load(empty_path), presence.PresenceConfig())

    sit_path, sit_res = scenario_csv("sitting", duration=180)
    variance_only = _score(sit_path, sit_res, thr, assist=False)
    with_assist = _score(sit_path, sit_res, thr, assist=True)

    # a still subject is the documented hard case for variance alone; the
    # respiration-band cue closes the gap
    assert variance_only.false_negative_rate > 0.2
    assert with_assist.accuracy > 0.9
    assert with_assist.accuracy > variance_only.accuracy + 0.1


def test_debounce_suppresses_short_runs():
    tw = np.arange(0, 40, 1.0)
    flags = np.zeros(40, dtype=bool)
    flags[10:12] = True          # 2 s blip
    flags[20:35] = True          # 15 s real run
    out = presence.debounce(flags, tw, min_dwell_s=3.0)
    assert not out[10:12].any()
    assert out[20:35].all()
