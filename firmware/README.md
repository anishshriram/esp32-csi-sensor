# Firmware (Phase 1)

Two ESP32-WROOM-32U boards. One runs a **SoftAP** (transmitter), the other
associates to it as a **STA** and reports CSI over serial (receiver). They never
touch the operator's home WiFi -- a commodity router does rate adaptation and
beamforming that change CSI in ways indistinguishable from motion.

## Bring-up order

```bash
scripts/bootstrap_esp_idf.sh          # ESP-IDF v5.3.1, esp32 target
. ~/esp/esp-idf/export.sh              # <-- every new shell
scripts/clone_esp_csi.sh
export ESP_CSI_DIR=~/esp/esp-csi

# read ~/esp/esp-csi/README.md, find the CSI receive example, then:
scripts/build_firmware.sh <example_dir> /dev/tty.SLAB_USBtoUART tx   # board 1
scripts/build_firmware.sh <example_dir> /dev/tty.usbserial-XXXX  rx   # board 2
```

Antennas must be connected **before** powering the boards (transmitting into a
bare u.FL socket stresses the PA). u.FL is press-fit: push straight down until it
clicks, never pull the cable. Both antennas vertical and parallel.

## menuconfig matrix

| Setting | Value | Why |
|---|---|---|
| WiFi channel | **fixed**, never auto. Default 6; scan 1/6/11 with a phone WiFi analyzer, pick least congested | a hopping channel invalidates every measurement |
| Bandwidth | **20 MHz** (HT20), not HT40 | HT40 changes subcarrier layout and indexing |
| Sample rate | target **100 Hz**, fall back to 50 Hz if packet loss is bad | 50 Hz is still >> Nyquist for respiration (0.15-0.6 Hz) |
| Serial baud | **921600** | lower rates bottleneck at 100 Hz |
| STA target | the **other ESP32's** SoftAP SSID/MAC | never the home router |

`sdkconfig.defaults.tx` / `sdkconfig.defaults.rx` in this directory capture these;
`build_firmware.sh` copies the right one in. Field names vary between esp-csi
revisions -- if a key is rejected, set it via `idf.py menuconfig` and update the
defaults file.

## Board register (fill in during bring-up)

| Role | MAC | Serial port | Flashed SHA |
|---|---|---|---|
| tx (SoftAP) | `??:??:??:??:??:??` | | |
| rx (STA)    | `??:??:??:??:??:??` | | |

## Serial line format  (VERIFY AGAINST REAL OUTPUT -- Phase 1.3)

`idf.py monitor` the receiver. Expect continuous CSI lines, each carrying **128
int8** values = 64 subcarriers as interleaved pairs. esp-csi documents the pair
order as **(imag, real)** -- the reverse of what most people assume. `csi_io`
derives the order from the data and logs it; this note is just the expectation.

The host logger parses through **one place**: `FIELD_SPEC` in
`csi_sensing/serial_format.py`. Its current default matches the `csi_recv`
example of espressif/esp-csi for ESP-IDF v5.3.x:

```
CSI_DATA, seq, mac, rssi, rate, sig_mode, mcs, bandwidth, smoothing,
not_sounding, aggregation, stbc, fec_coding, sgi, noise_floor, ampdu_cnt,
channel, secondary_channel, local_timestamp, ant, sig_len, rx_state,
agc_gain, fft_gain, len, first_word_invalid, "[<128 space-separated int8>]"
```

Steps:
1. `csi-capture --port <rx port> --duration 5 --out /tmp/probe.csv --label probe --dump-raw /tmp/raw.txt`
2. Open `/tmp/raw.txt`, compare one real line field-by-field to the list above.
3. If it differs, edit `FIELD_SPEC` (order + which fields exist). Nothing else
   changes.
4. `pytest tests/test_serial_format.py` and re-capture to confirm 0 malformed.

**`agc_gain` must be present and correct.** Without it the amplitude data is
unusable and the physical recording session has to be repeated.
