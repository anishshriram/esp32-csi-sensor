from csi_sensing.serial_format import FIELD_SPEC, ParseStats, format_line, parse_line
from csi_sensing.synth import generate, scenario


def test_roundtrip_synth_serial_lines():
    res = generate(scenario("sitting", duration=20, fs=100, breathing_bpm=15))
    lines = res.to_serial_lines()
    stats = ParseStats()
    parsed = [parse_line(l, stats) for l in lines]

    assert stats.malformed == 0
    assert stats.ok == len(lines)
    first = parsed[0]
    for name, _ in FIELD_SPEC:
        assert name in first
    assert len(first["data"]) == first["len"] == 128
    assert all(-128 <= v <= 127 for v in first["data"])


def test_rejects_non_csi_and_malformed():
    stats = ParseStats()
    assert parse_line("I (123) wifi: connected", stats) is None
    assert parse_line("CSI_DATA,1,2,3", stats) is None
    assert stats.non_csi == 1
    assert stats.malformed == 1


def test_format_line_inverse():
    rec = {name: (0 if conv is int else "CSI_DATA") for name, conv in FIELD_SPEC}
    rec["len"] = 4
    rec["data"] = [1, -2, 3, -4]
    back = parse_line(format_line(rec))
    assert back is not None
    assert back["data"] == [1, -2, 3, -4]


def test_handles_quoted_and_unquoted_data_field():
    rec = {name: (0 if conv is int else "CSI_DATA") for name, conv in FIELD_SPEC}
    rec["len"] = 2
    rec["data"] = [7, 8]
    line = format_line(rec)
    assert parse_line(line)["data"] == [7, 8]
    assert parse_line(line.replace('"', ""))["data"] == [7, 8]
