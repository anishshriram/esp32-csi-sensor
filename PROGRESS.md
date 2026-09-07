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
- [ ] **10. Phase 2 gate** -- three labeled recordings (`empty` / `walking` /
      `sitting`, 2 m LOS); verify packet rate; AGC diagnostic flattens; three
      heatmaps show the walking-vs-empty contrast.
- [ ] **11. Phase 3 gate** -- threshold from the real `empty` floor; 15-30 min
      mixed session with entry/exit log; report accuracy / FPR / FNR / latency,
      walking vs sitting separately.
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
