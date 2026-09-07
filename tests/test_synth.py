import numpy as np

from csi_sensing import CAPTURE_COLUMNS
from csi_sensing.synth import generate, scenario


def test_schema_and_rate():
    res = generate(scenario("walking", duration=30, fs=100))
    assert list(res.df.columns) == CAPTURE_COLUMNS
    rate = len(res.df) / 30
    assert 90 < rate < 101
    # a few percent of packets dropped
    assert len(res.df) < 30 * 100


def test_null_subcarriers_are_near_zero():
    res = generate(scenario("sitting", duration=20, fs=100))
    raw = np.vstack([np.fromstring(s, sep=" ") for s in res.df["data"]])
    comp = raw[:, 0::2] + 1j * raw[:, 1::2]
    mag = np.median(np.abs(comp), axis=0)
    nulls = res.truth["null_idx"]
    assert mag[nulls].max() < 0.2 * np.median(mag[res.truth["active_idx"]])


def test_int8_range():
    res = generate(scenario("mixed", duration=30, fs=100))
    raw = np.vstack([np.fromstring(s, sep=" ") for s in res.df["data"]])
    assert raw.min() >= -128 and raw.max() <= 127


def test_wall_attenuates_rssi():
    los = generate(scenario("sitting", duration=20, fs=100, wall=False))
    wall = generate(scenario("sitting", duration=20, fs=100, wall=True))
    assert wall.df["rssi"].mean() < los.df["rssi"].mean()
