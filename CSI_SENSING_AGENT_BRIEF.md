# Through-Wall WiFi CSI Sensing — Agent Work Order

## Context

Building a device-free RF sensing system using WiFi Channel State Information (CSI) from ESP32
boards. The system detects human presence and estimates respiration rate through an interior
drywall wall, with no camera and no wearable on the subject.

This document specifies the full scope of setup and coding work. Phases are ordered by dependency:
each assumes the previous is complete and validated. There is no schedule — work the phases in
order and stop at whatever gate fails.

The human operator handles all physical tasks: antenna connection, board placement, moving around
the space, breathing on cue, holding the phone reference.

## Hardware (in hand)

| Item | Detail |
|---|---|
| 2x ESP32-DevKitC | ESP32-WROOM-32U module, u.FL external antenna connector, micro-USB, CP210x USB-serial |
| 2x antenna | 2.4 GHz 6 dBi RP-SMA male dipole, hinged |
| 2x pigtail | u.FL/IPEX to RP-SMA female bulkhead, 20 cm RG178 |
| 1x power bank | 10000 mAh, 5V 2.4A, USB-A output |
| 2x cable | USB-A to micro-USB, 6 ft |

Two boards only. One transmitter, one receiver. No spare — avoid anything that risks bricking a
board without a recovery path.

---

## Phase 1 — Toolchain and firmware

**Gate: both boards flash, and CSI lines stream from the receiver over serial.**

### 1.1 ESP-IDF

Install ESP-IDF v5.x targeting `esp32` (not esp32s3, not esp32c3).

```bash
mkdir -p ~/esp && cd ~/esp
git clone -b v5.3.1 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf && ./install.sh esp32
```

`. ~/esp/esp-idf/export.sh` must be sourced in every new shell. Note this in the project README —
it is the most common cause of "idf.py: command not found".

On macOS, the CP210x VCP driver from Silicon Labs may be required before a serial device appears.
On Linux, the user likely needs to be in the `dialout` group, which requires a logout to take
effect.

Verify a board enumerates before proceeding:

```bash
ls /dev/tty.usbserial* /dev/ttyUSB*  2>/dev/null
```

### 1.2 esp-csi

Clone `https://github.com/espressif/esp-csi`. Work from `examples/get-started/csi_recv` or the
nearest equivalent — the tree layout has changed between revisions, so read the top-level README
rather than assuming paths.

Two firmware roles. Build and flash each to its own board. Record which board got which by MAC
address; the receiver config generally needs the sender's MAC or SSID.

Configure via `idf.py menuconfig`:

- **WiFi channel:** fixed, never auto. Default channel 6; the operator should scan first with a
  phone WiFi analyzer and pick the least congested of 1 / 6 / 11.
- **Bandwidth:** 20 MHz, not 40. HT40 changes subcarrier layout and complicates indexing.
- **Sample rate:** target 100 Hz. If packet loss is bad, step down. 50 Hz remains comfortably above
  Nyquist for respiration (0.15–0.6 Hz) and is an acceptable fallback.
- **Serial baud:** 921600. Lower rates bottleneck at 100 Hz.

Do not connect either board to the operator's home WiFi. The receiver associates with the *other
ESP32* running as SoftAP. A commodity router performs rate adaptation and beamforming that change
CSI in ways indistinguishable from motion, which would invalidate every measurement.

### 1.3 Firmware sanity check

Flash, then `idf.py monitor`. Expect CSI lines streaming continuously, each carrying 128 int8
values — 64 subcarriers as interleaved (imaginary, real) pairs.

Document the exact serial line format in the README, including field order of the `rx_ctrl` header.
The host logger depends on it and it varies between esp-csi revisions. Read the actual output; do
not assume a format from documentation.

---

## Phase 2 — Capture pipeline

**Gate: three labeled recordings on disk at a verified packet rate, with AGC normalization
validated.**

Create a Python project under the repo root. Use a venv. Dependencies: `pyserial`, `numpy`,
`pandas`, `scipy`, `matplotlib`.

### 2.1 Logger — `capture.py`

CLI tool. Arguments: serial port, duration, output path, label.

- `idf.py monitor` holds the serial port exclusively and must not be running during capture.
- Write a host wall-clock timestamp (`time.time()`, float seconds) as the first column of every row.
  Capture the ESP-side timestamp too if present, but the host timestamp is the primary time base.
- Parse and store `rx_ctrl` fields, at minimum `agc_gain`, `rssi`, `noise_floor`, as named columns.
  **Not optional.** Without `agc_gain` the amplitude data is unusable and the physical recording
  session has to be repeated.
- Write incrementally and flush periodically. Do not buffer a whole recording in memory.
- Count malformed and dropped lines. Print a summary at exit: rows written, duration, mean packet
  rate, malformed count.
- Write a sidecar `<output>.meta.json` with label, channel, board separation distance, wall present
  yes/no, subject position, start time, and firmware git SHA. Prompt for anything not passed as an
  argument. Unlabeled recordings become worthless within a day.

Report the measured packet rate prominently. A 60-second capture at 100 Hz should yield roughly
6000 rows. Substantially fewer means loss that must be fixed before continuing.

### 2.2 Parser — `csi_io.py`

Importable and separately testable.

- Load a CSV to an `(N, 64)` complex array plus a metadata DataFrame.
- Convert interleaved int8 pairs to complex. **Verify pair order empirically** — esp-csi documents
  (imaginary, real), the reverse of what most people assume. Confirm against real data.
- Provide amplitude and phase accessors. Phase is not usable for sensing on a single-antenna ESP32
  due to per-packet carrier and sampling frequency offset. Expose it; do not build on it.
- Select active subcarriers. Roughly 52 of 64 are non-null; the rest are guard bands and DC.
  **Derive the active set from the data** by finding consistently near-zero columns rather than
  hardcoding indices. Layout varies by firmware revision. Log which indices were selected.
- Provide resampling onto a uniform time grid using host timestamps. Packet arrival is jittery and
  the spectral stage requires uniform sampling.

### 2.3 AGC normalization

The ESP32 adjusts receiver gain between packets. Uncorrected, this produces amplitude steps that
look exactly like motion.

```python
amp_norm = amp / (10 ** (agc_gain / 20.0))[:, None]
```

Validate with a three-panel diagnostic plot sharing an x-axis: raw amplitude for one subcarrier,
`agc_gain` over time, normalized amplitude. On a static recording, steps in the raw trace should
align with gain changes and flatten after normalization.

If normalization does not visibly flatten them, stop and investigate the gain-to-dB scaling.
Everything downstream depends on this.

### 2.4 Heatmap — `plot_heatmap.py`

CSV in, PNG out. Amplitude, subcarrier on y-axis, time on x-axis. Apply AGC normalization. Use
per-subcarrier robust normalization (median and IQR) for display so strong subcarriers do not swamp
weak ones. Title from sidecar metadata.

Operator records three runs at 2 m separation, line of sight, boards at chest height, antennas
vertical and parallel:

1. `empty` — nobody in the room
2. `walking` — subject walks back and forth across the link
3. `sitting` — subject sits still between the boards

The walking heatmap should show clear vertical disturbance; the empty heatmap should be
comparatively flat. Generate all three and present them together.

This contrast is the project's first real result. Do not proceed to Phase 3 without it.

### 2.5 Repo hygiene

Initialize git. Commit CSV recordings alongside code — raw data is the expensive part and
re-recording costs a physical session. README covers toolchain setup, the `export.sh` requirement,
driver notes, and how to run each script.

---

## Phase 3 — Presence detection

**Gate: scored presence detection with a stated accuracy and latency on a labeled recording.**

Simpler than respiration and worth landing first — it validates the whole chain end to end.

- Compute windowed variance of normalized amplitude across active subcarriers. Motion raises it
  sharply.
- Threshold to a boolean presence signal. Set the threshold from the `empty` recording's noise
  floor rather than by eye.
- Add hysteresis or a debounce window so the output does not chatter at the boundary.
- Record a longer mixed session (15–30 minutes) with the operator logging entry and exit times, and
  score against it: accuracy, false positive rate, false negative rate, detection latency.
- Note that a still subject is much harder than a moving one. Report `sitting` performance
  separately from `walking` — collapsing them hides the interesting limitation.

---

## Phase 4 — Respiration extraction

**Gate: estimated breathing rate within a stated tolerance of ground truth across the metronome
set.**

Pipeline order matters; each stage assumes the previous.

1. **Hampel filter** per subcarrier to remove single-packet outliers.
2. **Resample** onto a uniform time grid (from `csi_io`).
3. **PCA background subtraction** across active subcarriers. Discard the first principal component
   — it carries static multipath from walls, furniture, and the direct path. Retain components 2–4.
4. **Band-pass**, 4th-order Butterworth, 0.15–0.6 Hz, zero-phase via `filtfilt`.
5. **Subcarrier selection** by band-power SNR — energy in the respiration band over total energy.
   Rank and fuse the top 5–10. Sensitivity varies wildly across subcarriers because of multipath
   nulls; some show nothing at all.
6. **Rate estimation** from the spectral peak over a sliding window (30–60 s). Emit a confidence
   value from peak prominence.

### Ground truth

Phone strapped to the subject's sternum running Phyphox, logging accelerometer with timestamps,
exported to CSV. Write a loader and an alignment routine — clock offset between phone and host must
be corrected, most easily by having the operator produce a sharp shared event (a few deliberate
deep breaths) at the start of each recording.

Also run metronome-paced sessions at 10, 12, 15, 18, and 20 bpm. These give exact known rates and
are the cleanest possible scoring set.

Report error as mean absolute error in breaths/min, per rate and overall.

---

## Phase 5 — Through-wall characterization

**Gate: a measured degradation figure between line-of-sight and through-wall.**

Everything to this point is line of sight in one room. This phase earns the project's name.

- Re-run the full recording set with a single interior wall between transmitter and receiver.
  Operator marks floor positions with tape so geometry is reproducible.
- Sweep distance: at minimum 1 m, 2 m, 3 m subject-to-link. Find where respiration estimation
  breaks down and report that boundary honestly.
- Re-run the line-of-sight baseline in the same session, not from old data — ambient conditions
  drift.
- Produce a comparison table: configuration, distance, presence accuracy, respiration MAE.

The degradation number is more valuable than the headline accuracy. "±1.4 bpm line of sight, ±2.3
bpm through drywall at 2 m" is a stronger claim than either figure alone because it shows the
limits were measured rather than avoided.

### Optional extension

If time allows, repeat active-mode capture against the operator's ordinary home router instead of
the dedicated link, and report the additional degradation. This demonstrates the technique
generalizes to hardware not under the experimenter's control. Do this only after the dedicated-link
results are complete — router rate adaptation makes it a poor debugging environment.

---

## Phase 6 — Deployment

**Gate: metrics publishing over MQTT from the device, rendered live.**

- Port the pipeline to run on the ESP32 rather than the host.
- Publish `{presence, bpm, confidence, timestamp}` over MQTT to a Mosquitto broker.
- Quantify the data reduction: roughly 52 subcarriers at 100 Hz down to about 4 metrics per second.
  This is a headline number worth stating precisely.
- Dashboard: InfluxDB plus Grafana. Capture a short screen recording of the live view for the
  project README.

---

## Constraints

- Do not use the operator's home WiFi as the transmitter for any measurement in Phases 1–5.
  Dedicated ESP32 SoftAP link only.
- Do not build anything on CSI phase.
- Do not hardcode subcarrier indices or I/Q pair ordering. Derive both from data and log what was
  derived.
- Do not discard `rx_ctrl` fields at parse time.
- Do not skip a phase gate. A failure at a gate means the problem is in that phase, and it will be
  far harder to localize once later stages are stacked on top.
- Heart rate is out of scope. Cardiac motion at 2.4 GHz on a single-antenna receiver is roughly an
  order of magnitude below respiration and usually buried. Do not attempt it, and do not claim it.

## Notes for the operator (surface these when relevant)

- Antennas must be connected before powering the boards. Transmitting into a bare u.FL socket is a
  bad impedance match and stresses the power amplifier.
- u.FL is press-fit and fragile. Push straight down until it clicks; never pull the cable to remove.
- Both antennas vertical and parallel. A tilted dipole costs cross-polarization loss that reads as
  inexplicably bad data.
- Test the power bank for auto-shutoff before trusting it with a long recording. Run a board off it
  for an hour and confirm it stays up.
- Mark board positions on the floor with tape. Every reported distance must be reproducible.
