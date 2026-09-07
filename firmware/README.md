# Firmware (Phase 1)

Two ESP32-WROOM-32U boards on a **dedicated ESP-NOW link** -- no router, no
association, no rate adaptation. This is what the current esp-csi get-started
examples use, and it satisfies the brief's "dedicated ESP32 link only"
constraint better than a SoftAP would.

- `csi_send` -> transmitter. Broadcasts ESP-NOW packets at 100 Hz.
- `csi_recv` -> receiver. Filters on the sender's fixed MAC (`1a:00:00:00:00:00`,
  set by the example) and prints one CSI line per packet over serial.

Cloned esp-csi revision: **8633d67**. The tree layout changes between revisions
-- if paths below are wrong, read `~/esp/esp-csi/README.md`.

## Bring-up

```bash
scripts/bootstrap_esp_idf.sh          # ESP-IDF v5.3.1, esp32 target
. ~/esp/esp-idf/export.sh              # <-- every new shell
scripts/clone_esp_csi.sh
export ESP_CSI_DIR=~/esp/esp-csi

firmware/apply_patches.sh              # HT20 + fixed channel 6 + agc_gain output

CSI=~/esp/esp-csi/examples/get-started
scripts/build_firmware.sh $CSI/csi_send /dev/tty.SLAB_USBtoUART  tx   # board 1
scripts/build_firmware.sh $CSI/csi_recv /dev/tty.usbserial-XXXX  rx   # board 2
```

Antennas connected **before** power (a bare u.FL socket stresses the PA). u.FL is
press-fit: push straight down until it clicks, never pull the cable. Both
antennas vertical and parallel.

> **macOS cert note:** a python.org framework Python fails the IDF tool downloads
> with `CERTIFICATE_VERIFY_FAILED`. `bootstrap_esp_idf.sh` handles it by exporting
> `SSL_CERT_FILE` from `certifi`; by hand: `export SSL_CERT_FILE=$(python3 -m certifi)`.

## What the patch changes (`firmware/patches/0001-*.patch`)

| Change | Stock | Patched | Why |
|---|---|---|---|
| WiFi channel (`#define CONFIG_LESS_INTERFERENCE_CHANNEL`) | 11 | 6 | fixed; scan 1/6/11 with a phone analyzer and pick least congested |
| Bandwidth (`CONFIG_WIFI_BANDWIDTH`, `CONFIG_ESP_NOW_PHYMODE`) | HT40 | HT20 | HT40 changes subcarrier layout/indexing; HT20 = clean 64 subcarriers / 128 int8 |
| CSI CSV (csi_recv, ESP32 branch) | no gain fields | adds `agc_gain`, `fft_gain`; CSI stays **raw** (`compensate_gain` = 1.0) | the host normalizes amplitude and validates it (Phase 2.3) -- impossible if firmware pre-compensates |

Send rate stays 100 Hz (`CONFIG_SEND_FREQUENCY`). To change the channel later,
edit the `#define` in both `app_main.c` files (it is not a Kconfig option).

> **Unverified until the first build:** `esp_csi_gain_ctrl_get_rx_gain()` is only
> exercised by the stock example on S3/C3/C6. If it does not compile or link for
> the plain `esp32` target, fall back to enabling `CONFIG_GAIN_CONTROL` for esp32
> (add `|| CONFIG_IDF_TARGET_ESP32` at line ~47) and accept firmware-side gain
> compensation -- then the host AGC step becomes validation-only. Note which path
> you took here.

## menuconfig / sdkconfig

`sdkconfig.defaults.{tx,rx}` in this directory hold the Kconfig-level settings
(921600 baud, CSI enabled, RX buffers, CPU at 240 MHz). `build_firmware.sh`
merges them into the example's own `sdkconfig.defaults`. Channel and bandwidth
are **not** Kconfig here -- they come from the patch.

## Board register (fill in during bring-up)

| Role | Board MAC | Serial port | esp-csi SHA | gain path (patched call / CONFIG_GAIN_CONTROL) |
|---|---|---|---|---|
| tx (csi_send) | `??:??:??:??:??:??` | | 8633d67 | n/a |
| rx (csi_recv) | `??:??:??:??:??:??` | | 8633d67 | |

Note: `csi_recv` filters on the **sender payload id**, not the real sender MAC --
both boards set their STA MAC to `1a:00:00:00:00:00` in the example. Record the
real chip MACs anyway (`esptool.py read_mac`).

## Serial line format  (VERIFY -- Phase 1.3)

Expect continuous CSI lines, each carrying **128 int8** = 64 subcarriers as
interleaved pairs. esp-csi buffers are **(imag, real)** order; `csi_io` derives
this from the data and logs it -- this note is just the expectation.

The host parses through **one place**: `FIELD_SPEC` in
`csi_sensing/serial_format.py`. Post-patch it expects this header:

```
type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,
aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,
local_timestamp,ant,sig_len,rx_format,agc_gain,fft_gain,len,first_word,
"[<128 space/comma-separated int8>]"
```

Steps:
1. `csi-capture --port <rx port> --duration 5 --out /tmp/probe.csv --label probe --dump-raw /tmp/raw.txt`
2. Open `/tmp/raw.txt`; the example prints its own header line first -- compare it
   to the list above field-by-field.
3. If it differs, edit `FIELD_SPEC` (order + which fields exist). Nothing else
   changes.
4. `pytest tests/test_serial_format.py` and re-capture; confirm 0 malformed.

**`agc_gain` must be present and correct.** Without it the amplitude data is
unusable and the recording session has to be repeated.
