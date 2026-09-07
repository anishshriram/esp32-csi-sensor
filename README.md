# Through-Wall WiFi CSI Sensing

Device-free presence detection and respiration-rate estimation from WiFi Channel
State Information (CSI) on two ESP32 boards -- one SoftAP transmitter, one STA
receiver -- with no camera and no wearable on the subject.

Full scope and rationale: [`CSI_SENSING_AGENT_BRIEF.md`](CSI_SENSING_AGENT_BRIEF.md).
Execution plan and status: [`PROGRESS.md`](PROGRESS.md).

## Layout

```
csi_sensing/            host software (importable + `python -m`)
  serial_format.py      parse one esp-csi serial line  (edit FIELD_SPEC here after Phase 1.3)
  synth.py              synthetic CSI generator -- ground truth known
  capture.py            serial logger (csi-capture)
  csi_io.py             capture CSV -> complex CSI + metadata; derives active set & I/Q order
  agc.py                AGC gain normalization
  presence.py           Phase 3 -- windowed variance presence detection
  respiration.py        Phase 4 -- hampel -> resample -> PCA -> band-pass -> fuse -> spectral rate
  reference.py          Phyphox ground truth + clock alignment
  metrics.py            presence accuracy/latency, respiration MAE
  plots/                heatmap, AGC diagnostic, respiration figure
  deploy/               live pipeline + MQTT publisher (Phase 6)
analysis/characterize.py  Phase 5 -- LOS vs through-wall comparison table
firmware/               Phase 1 -- menuconfig matrix, sdkconfig defaults, serial format notes
scripts/                ESP-IDF + esp-csi bootstrap, firmware build/flash
deploy/                 docker-compose: Mosquitto + InfluxDB + Grafana
data/                   real recordings are committed; SYNTH_* (git-ignored) via scripts/make_synth_data.sh
tests/                  pytest suite -- runs entirely on synthetic CSI
```

## Setup

### Host (Python)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # 31 tests, all synthetic
```

### ESP-IDF (Phase 1, one time)

```bash
scripts/bootstrap_esp_idf.sh        # clones esp-idf v5.3.1, ./install.sh esp32
. ~/esp/esp-idf/export.sh           # REQUIRED in every new shell -- the #1 cause
                                    # of "idf.py: command not found"
scripts/clone_esp_csi.sh
```

macOS: install the Silicon Labs **CP210x VCP driver** if no `/dev/tty.usbserial*`
or `/dev/tty.SLAB_USBtoUART` appears when a board is plugged in.
Linux: add yourself to the `dialout` group (needs a re-login).

See [`firmware/README.md`](firmware/README.md) for flashing, the menuconfig
matrix, and how to verify the serial line format.

## Running the pipeline

The scripts work identically on synthetic and real CSVs.

```bash
# 0. build the synthetic demo set + figures (git-ignored; skip once real data exists)
scripts/make_synth_data.sh
#    or one recording by hand:
.venv/bin/python -m csi_sensing.synth --scenario mixed --duration 240 --bpm 14 \
    --out data/SYNTH_mixed.csv --meta

# 1. capture from the receiver  (idf.py monitor must be CLOSED)
.venv/bin/csi-capture --port /dev/tty.SLAB_USBtoUART --duration 60 \
    --out data/empty_los_2m.csv --label empty

# 2. AGC diagnostic (three-panel) + heatmaps
.venv/bin/python -m csi_sensing.plots.plot_diagnostic data/SYNTH_sitting_los_2m.csv
.venv/bin/python -m csi_sensing.plots.plot_heatmap   data/SYNTH_walking_los_2m.csv

# 3. presence  (threshold set from an empty recording, walking/sitting scored apart)
.venv/bin/csi-presence data/SYNTH_mixed_los_2m.csv --empty data/SYNTH_empty_los_2m.csv \
    --truth "[[36,108],[162,252],[288,342]]"

# 4. respiration  (vs a known rate or a Phyphox export)
.venv/bin/csi-respiration data/SYNTH_metronome_15bpm.csv --truth-bpm 15
.venv/bin/python -m csi_sensing.plots.plot_respiration data/SYNTH_metronome_15bpm.csv --truth-bpm 15

# 5. through-wall characterization table
.venv/bin/python -m analysis.characterize analysis/SYNTH_manifest.csv --outdir results

# 6. live dashboard
cd deploy && docker compose up -d && cd ..
.venv/bin/csi-live --replay data/SYNTH_mixed_los_2m.csv --speed 4 --mqtt localhost
#   real hardware:  csi-live --port /dev/tty.SLAB_USBtoUART --mqtt localhost
```

## Design rules (from the brief)

- Dedicated ESP32 SoftAP link only for Phases 1-5 -- never the home router.
- Nothing built on CSI phase (per-packet CFO/SFO on a single-antenna ESP32).
- Subcarrier indices and I/Q pair order are **derived from data and logged**,
  never hardcoded (`csi_io.derive_active_subcarriers`, `csi_io.detect_pair_order`).
- `rx_ctrl` fields are never dropped at parse time.
- Don't skip a phase gate.
- Heart rate is out of scope.

## Status vs synthetic ground truth

| stage | result on synthetic data |
|---|---|
| I/Q order + active set | derived from data for both interleavings; logged |
| AGC (blind) | removes a stepped common-mode level, ~2.6x CV reduction on a static clip |
| presence -- walking | ~99% accuracy, <1 s latency, <5% FPR |
| presence -- sitting | variance alone misses it (documented); `--respiration-assist` -> ~100% |
| respiration | MAE < 0.3 bpm over the 10/12/15/18/20 metronome set |
| through-wall | confidence and presence accuracy drop in the right direction |

Real hardware so far: both ESP32 boards flashed (ESP-NOW link, HT20, ch 6), CSI
streaming at ~85 Hz, format locked into `FIELD_SPEC`, full pipeline runs on a
real bench capture. The plain ESP32 exposes no `agc_gain`, so amplitude
normalization is blind (`agc.normalize_blind`). Real Stage-B metrics land as the
2 m link recordings come in.
