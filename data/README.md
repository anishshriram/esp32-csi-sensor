# Recordings

Raw CSI captures are committed here alongside code -- re-recording costs a
physical session. Each `<name>.csv` has a `<name>.csv.meta.json` sidecar.

## Naming

```
<label>_<config>_<distance>_<YYYYMMDD-HHMMSS>.csv
empty_los_2m_20260907-141500.csv
sitting_wall_3m_20260907-153000.csv
```

`label` ∈ {empty, walking, sitting, mixed, metronome<bpm>}
`config` ∈ {los, wall}

Files prefixed `SYNTH_` are synthetic (from `csi_sensing.synth`), used to validate
the pipeline before the hardware exists. They carry `"synthetic": true` in the
sidecar. Delete or ignore them once real recordings land.

## CSV schema (`csi_sensing.CAPTURE_COLUMNS`)

`host_ts` (wall clock, primary time base) + every parsed esp-csi field
(`agc_gain`, `rssi`, `noise_floor`, `channel`, ...) + `data` (space-separated
int8, 2 values per subcarrier). Nothing from `rx_ctrl` is dropped at capture.

## Sidecar fields

`label, channel, board_separation_m, wall_present, subject_position, start_time,
firmware_sha, rows, duration_s, mean_pkt_rate_hz` -- plus free-form `notes`.
For labeled scoring sessions also keep an entry/exit log (for presence) or a
Phyphox export (for respiration) next to the CSV.
