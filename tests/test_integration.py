"""End-to-end: synthetic capture CSV -> capture replay -> full pipeline."""
import json

import numpy as np

from csi_sensing import csi_io, presence, respiration
from csi_sensing.capture import capture
from csi_sensing.metrics import intervals_to_mask, score_presence
from csi_sensing.synth import generate, scenario


def test_capture_replay_then_pipeline(tmp_path):
    res = generate(scenario("mixed", duration=240, fs=100, breathing_bpm=14))
    lines = res.to_serial_lines()

    # capture parses the serial stream into the on-disk schema
    out = tmp_path / "capture.csv"
    summary = capture("ignored", 0, str(out), {"label": "mixed"}, _source_lines=lines)
    assert summary["rows_written"] == len(lines)
    assert summary["malformed"] == 0
    captured = csi_io.load(str(out))
    assert captured.n == len(lines)
    assert "agc_gain" in captured.meta.columns

    # the pipeline runs on a capture CSV with a real (jittered) time base
    synth_csv = tmp_path / "synth.csv"
    res.to_csv(str(synth_csv))
    rec = csi_io.load(str(synth_csv))

    # presence (variance) recovers the moving segments
    empty = generate(scenario("empty", duration=120, fs=100))
    ep = tmp_path / "empty.csv"
    empty.to_csv(str(ep))
    thr = presence.calibrate_threshold(csi_io.load(str(ep)), presence.PresenceConfig())
    tw, _, flags = presence.detect(rec, presence.PresenceConfig(), thr)

    move_iv = [(a, b) for a, b, m in res.truth["presence_intervals"] if m == "move"]
    move_mask = intervals_to_mask(move_iv, tw)
    s = score_presence(flags, move_mask, tw)
    assert s.false_negative_rate < 0.15

    # respiration recovers the 14 bpm rate
    r = respiration.estimate_from_recording(rec)
    assert abs(r.summary_bpm() - 14) < 1.5


def test_live_replay_emits_metric_records(tmp_path):
    from csi_sensing.deploy.pipeline_live import run, _replay_lines

    res = generate(scenario("sitting", duration=200, fs=100, breathing_bpm=16))
    csv = tmp_path / "sit.csv"
    res.to_csv(str(csv))

    records = []
    run(_replay_lines(str(csv), speed=800.0), is_serial=False, buffer_s=90,
        emit_every=5.0, on_metric=records.append, max_records=25)

    assert len(records) == 25
    for rec in records:
        assert set(rec) == {"timestamp", "presence", "bpm", "confidence"}
    # once the rolling buffer is warm (>=45 s in), the estimate tracks 16 bpm
    warm = [r["bpm"] for r in records[10:] if r["bpm"]]
    assert warm and abs(np.median(warm) - 16) < 3
