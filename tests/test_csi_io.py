import numpy as np
import pytest

from csi_sensing import csi_io


@pytest.mark.parametrize("pair_order", ["im_re", "re_im"])
def test_derives_pair_order_and_active_set(sitting_csv, pair_order):
    path, res = sitting_csv(pair_order=pair_order)
    rec = csi_io.load(path)

    assert rec.pair_order == pair_order
    # active set matches the generator's, allowing a small boundary tolerance
    got = set(rec.active.tolist())
    want = set(res.truth["active_idx"])
    assert len(got ^ want) <= 2
    assert rec.csi.shape[1] == 64


def test_amplitude_is_pair_order_invariant(sitting_csv):
    p1, _ = sitting_csv(pair_order="im_re", seed=1)
    p2, _ = sitting_csv(pair_order="re_im", seed=1)
    a1 = np.sort(np.abs(csi_io.load(p1).csi), axis=1)
    a2 = np.sort(np.abs(csi_io.load(p2).csi), axis=1)
    assert np.allclose(a1, a2, atol=1e-4)


def test_resample_uniform_grid(sitting_csv):
    path, _ = sitting_csv(duration=60)
    rec = csi_io.load(path)
    t, csi = rec.resample_uniform(20.0)
    assert np.allclose(np.diff(t), 1 / 20.0)
    assert csi.shape[0] == len(t)
    assert csi.shape[1] == len(rec.active)


def test_packet_rate_reasonable(sitting_csv):
    path, _ = sitting_csv(duration=60)
    assert 90 < csi_io.load(path).packet_rate() < 101
