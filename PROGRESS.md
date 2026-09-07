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
  - [x] ESP-IDF v5.3.1 installed (`~/esp/esp-idf`); needed an `SSL_CERT_FILE`
        workaround for the framework Python -- now baked into `bootstrap_esp_idf.sh`
  - [x] esp-csi cloned (`~/esp/esp-csi`, rev 8633d67)
  - [x] Read the real `csi_recv`/`csi_send` source. Findings: the get-started
        examples use a **dedicated ESP-NOW link** (not SoftAP -- still satisfies
        the "no router" constraint), default **HT40 on channel 11**, and the
        ESP32 CSV branch **does not emit `agc_gain`**.
  - [x] `firmware/patches/0001-*.patch` (+ `apply_patches.sh`): HT20, channel 6,
        and adds `agc_gain`/`fft_gain` to the CSV while keeping CSI raw. Applies
        cleanly to rev 8633d67. **Gain-API call is unverified until the first
        build** -- fallback documented in `firmware/README.md`.
  - [x] `serial_format.FIELD_SPEC` + synth updated to the real post-patch header;
        31 tests still green.
  - [ ] boards connected, both roles flashed, MACs recorded
  - [ ] `idf.py monitor` shows a continuous CSI stream; real header line compared
        to `FIELD_SPEC`; `test_serial_format.py` re-run against real lines
  - **approval checkpoint**
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
