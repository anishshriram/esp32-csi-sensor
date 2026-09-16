# Progress

Two stages. **Stage A** (host software) is built and validated on synthetic CSI.
**Stage B** (real hardware + phase gates) needs operator recording sessions.

## Stage A -- host software stack  ✅ complete, synthetic-validated

| # | Piece | Files | Synthetic result |
|---|---|---|---|
| 1 | repo, venv, deps, CLIs | `pyproject.toml`, `.gitignore`, `README.md` | 31 pytest tests green |
| 2 | Phase 1 assets | `scripts/*.sh`, `firmware/README.md`, `firmware/sdkconfig.defaults.{tx,rx}` | docs only -- board work is step 9 |
| 3 | capture pipeline | `serial_format.py`, `synth.py`, `capture.py`, `csi_io.py`, `agc.py`, `plots/` | I/Q order + active set recovered for both interleavings; AGC flattens injected steps 8x |
| 4 | presence | `presence.py`, `metrics.py` | walking ~99% acc / <1 s latency; sitting needs `--respiration-assist` (documented) |
| 5 | respiration | `respiration.py`, `reference.py` | MAE 0.14 bpm over 10/12/15/18/20; clock offset recovered within 1 s |
| 6 | through-wall tooling | `analysis/characterize.py` | comparison table; confidence + presence drop through wall |
| 7 | deployment | `csi_sensing/deploy/`, `deploy/` (compose, grafana) | `csi-live --replay ... --mqtt` emits `{presence,bpm,confidence,timestamp}` |
| 8 | tests | `tests/` | `pytest` -- 31 passed |

Synthetic demo data in `data/SYNTH_*`, figures in `results/`.

## Stage B -- real hardware & phase gates  ⏳ in progress

Each ends at an **approval checkpoint**.

- [~] **9. Phase 1 gate** -- toolchain + firmware + CSI stream
  - [x] ESP-IDF v5.3.1 installed. `bootstrap_esp_idf.sh` now also handles two
        macOS gaps it hit: `SSL_CERT_FILE` from certifi (framework Python), and
        `idf_tools.py install cmake ninja` (install.sh doesn't pull them).
  - [x] esp-csi cloned (rev 8633d67). The get-started examples use a **dedicated
        ESP-NOW link** (not SoftAP -- still no router), default **HT40 / ch 11**.
  - [x] `firmware/patches/0001-dedicated-link-ht20.patch` (+ `apply_patches.sh`):
        HT20, channel 6. Applies cleanly to rev 8633d67.
  - [x] Both boards flashed and running.
        tx `68:09:47:26:ee:14` @ usbserial-0001, rx `68:09:47:9e:fd:a4` @ usbserial-5.
  - [x] **CSI stream confirmed.** ~82-92 pkt/s, 0 malformed through `csi-capture`.
  - [x] **Real serial format locked into `FIELD_SPEC`** (24 fields, no `agc_gain`).
        Real quirks handled: `len=256` (LLTF+HT-LTF) -> `csi_io.load(ltf="htltf")`
        slices to `(N,64)`; pair order derives to `re_im`; raw sample committed
        at `data/REAL_probe_raw.txt`.
  - [x] **Plain ESP32 has no AGC gain readout** -- `esp_csi_gain_ctrl` is an empty
        lib for this target. `agc.py` reworked: `normalize_blind` removes a
        smoothed common-mode level only when it swings >10% (measured ~6% on the
        bench, so it is usually a no-op). Synth updated to match (no fake AGC
        steps). 31 tests green.
  - [x] End-to-end run on a real bench capture (`data/REAL_desk_probe.csv`):
        csi_io / AGC / presence / respiration all run, presence ~0 on a static
        bench.
  - [x] Link set up: ~3.86 m LOS, boards ~1.2 m high, antennas vertical/parallel,
        ch 6, ~90 pkt/s. Transmitter on wall power (its power bank auto-shut-off).
  - [x] Three labeled recordings: `data/{empty,walking,sitting}_los_3m9_s3_*.csv`
        (60 s each, 88-94 Hz, 0-1 malformed).
  - **RF finding:** even with `manu_scale`, ESP32 CSI *amplitude* is AGC-flattened
    by the RF front end and barely moves when a person crosses the path.
    **RSSI does** (empty std 0.6 dB, walking std 3.3 dB with -20 dB crossing
    dips). Presence detection re-keyed onto RSSI windowed-std + CSI variance;
    `manu_scale=true, shift=3` kept only for a cleaner int8 range (0.2% clip).
  - **Phase 2 gate MET:** walking heatmap shows the periodic crossings clearly
    vs a flat empty; motion score separates ~5x (empty median 0.6, walking 3.1).
  - **Phase 3 (early):** walking 100% detect / 0% empty FP; sitting needs
    `--respiration-assist` (documented hard case) -> ~94%.
  - **approval checkpoint** -- recordings collected, gate demonstrated. Longer
    labeled sessions (15-30 min mixed, entry/exit log) still needed for a
    scored Phase 3 accuracy/latency number.
- [x] **10. Phase 2 gate** -- three labeled recordings (3.86 m LOS); ~90 Hz;
      heatmaps show the walking-vs-empty contrast; motion score ~5x.
- [x] **11. Phase 3 gate** -- threshold from the real `empty` floor; 15-30 min
      mixed session with entry/exit log; report accuracy / FPR / FNR / latency,
      walking vs sitting separately. MET 2026-09-16 (see below).
      - **3 failed 20-min attempts.** Root causes found and mostly fixed:
        1. Take 1 -- the **Mac slept** (two gaps, 837 s + 586 s). Fixed:
           `capture.py` runs `caffeinate` for the recording.
        2. Take 2 -- **receiver UART saturated**: the full 256-int8 line at
           94 Hz is ~87 KB/s = 94% of the 921600-baud link; it backs up after
           ~100 s and stalls the CSI callback. Fixed: patch emits only the
           HT-LTF half (128 int8, ~43 KB/s). Held a clean 3-min empty test.
        3. Take 3 -- got 3 min 14 s (vs ~1.5 min before), then the
           **transmitter crashed**: `csi_send` was sending at a full 100/s
           right up to a hard stop. The stock example fires `esp_now_send` to
           broadcast at 100 Hz with **no send-completion callback** -- a known
           way to deadlock ESP-NOW TX buffers under sustained load. NOT yet
           fixed (needs the tx board back on the bench to patch csi_send).
      - `capture.py` also aborts after 20 s of dead air (was: ran the full
        25 min collecting nothing) and warns below 60 Hz.
      - Partial data kept: `data/mixed_partial_los_3m9_*` -- 194 s with a sync
        wave at t~60 s and ~1 min of walking. Enough to confirm the pipeline
        (walking motion-score ~6x empty) but too short for a scored number.
      - Operator log (sync 20:38, walk 20:39-20:40) noted for the redo.

  **2026-09-16 -- Phase 3 gate MET.** Root cause of the take-3 crash turned out
  to be power, not the missing send callback: with both boards on Mac USB power
  it ran clean for 6+ min on the desk, and clean for 2 min at 3.86 m range on a
  wall adapter. No `csi_send` patch was needed. Take 4 (20 min, real 3.86 m
  link, tx on wall power, rx raised to ~4 ft) completed in full: 112,065 rows,
  93.4 Hz, only 8 malformed / 8 non-CSI out of 112k.

  Scored against the operator log (wave 14:30; walking 14:31-32 and 14:39-40;
  still 14:33-34, 14:36-37, 14:43-45; empty otherwise; threshold calibrated
  from the trailing confirmed-empty tail):

  |                     | variance-only | +respiration-assist |
  |---------------------|--------------:|---------------------:|
  | overall accuracy    | 77.3%         | 74.3%                 |
  | false positive rate | 8.6%          | 28.8%                 |
  | false negative rate | 55.4%         | 18.6%                 |
  | detection latency   | 15.6 s        | 7.4 s                 |
  | clearance latency   | 10.3 s        | 20.5 s                |
  | walking detected    | 72%           | 73%                   |
  | still detected      | 31%           | 86%                   |

  Confirms the documented pattern: variance alone is solid for walking, weak
  for a still subject; the respiration-band assist recovers most of the still
  cases at the cost of more false positives elsewhere. Ground truth is
  approximate (~1 min log precision), so this is a first real-data estimate,
  not a tight bound -- worth re-scoring with a stopwatch-precision log later.

  **Next session:** Phase 4 (Phyphox) -- phone on sternum, deep-breath sync
  event, metronome sessions at 10/12/15/18/20 bpm.
- [ ] **12. Phase 4 gate** -- Phyphox on sternum; deep-breath sync event;
      metronome sessions at 10/12/15/18/20 bpm; report MAE per rate and overall.
- [ ] **13. Phase 5 gate** -- repeat set through one interior wall, distance sweep
      1/2/3 m, fresh LOS baseline same session; `characterize.py` -> degradation
      figure.
- [ ] **14. Phase 6 gate** -- `docker compose up`; `csi-live --port ... --mqtt`;
      InfluxDB + Grafana live; state the data-reduction number; screen-record.
      ESP32 C firmware port after the host path is proven live.

## Notes for the operator

- Antennas connected **before** powering boards. u.FL: push straight down, never
  pull the cable. Both antennas vertical and parallel.
- Test the power bank for auto-shutoff (run a board off it for an hour) before a
  long recording.
- Mark every board position on the floor with tape -- reported distances must be
  reproducible.
- Dedicated ESP32 SoftAP link only for Phases 1-5, never the home router.
