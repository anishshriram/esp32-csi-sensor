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

Gotchas from bring-up:
- Port name is not stable per board -- after unplug/replug the two CP210x chips
  swap between `usbserial-0001` and `usbserial-5`. Identify by chip MAC
  (`esptool.py read_mac`), not port name.
- A flaky USB port gives `Download mode detected ... TX path seems to be down`
  on flash -- try a different port.
- `csi-capture` opens without toggling DTR/RTS and waits out the boot log, so it
  will not reset or wedge the board.
- A power bank may auto-shut-off the transmitter (~100 mA draw). Use wall USB or
  a bank with a low-current mode; don't pass-through-charge the bank while it
  powers the board.

## What the patch changes (`firmware/patches/0001-dedicated-link-ht20.patch`)

| Change | Stock | Patched | Why |
|---|---|---|---|
| WiFi channel (`#define CONFIG_LESS_INTERFERENCE_CHANNEL`) | 11 | 6 | fixed; scan 1/6/11 with a phone analyzer and pick least congested |
| Bandwidth (`CONFIG_WIFI_BANDWIDTH`, `CONFIG_ESP_NOW_PHYMODE`) | HT40 | HT20 | HT40 changes subcarrier layout/indexing |
| csi_recv `wifi_csi_config_t` | `manu_scale=false`, `shift=0` | same (comment only) | `manu_scale=true, shift=9` was tried and **saturated** the payload (`-128`/`127` walls); auto-scale is stable enough on a fixed link |

Send rate stays 100 Hz (`CONFIG_SEND_FREQUENCY`). Channel/BW are `#define`s in
both `app_main.c` files, not Kconfig.

> **AGC gain: not available, and CSI amplitude is AGC-flattened.**
> `esp_csi_gain_ctrl` ships an empty lib for `esp32`/`esp32s2` (no gain readout),
> so there is no `agc_gain` field. `manu_scale`/`shift` only sets a *digital*
> left-shift of the final CSI values -- the RF front-end AGC upstream still
> normalizes amplitude, so **CSI magnitude barely tracks a person crossing the
> path** (measured: walking vs empty CSI-amplitude variance ~identical). RSSI,
> in the same line, swings ~20 dB per crossing -- that is the presence signal
> the host uses (`presence.motion_score` with `rssi=`). `manu_scale=true,
> shift=3` is kept in the patch only for a cleaner int8 range at this link's
> RSSI (~-28 dBm); `shift=9` and `shift=4` both saturated. Re-tune `shift` if
> the link RSSI changes a lot. `agc.normalize_blind` still cleans slow
> common-mode drift out of the amplitude for the respiration stage.

## menuconfig / sdkconfig

`sdkconfig.defaults.{tx,rx}` in this directory hold the Kconfig-level settings
(921600 baud, CSI enabled, RX buffers, CPU at 240 MHz). `build_firmware.sh`
merges them into the example's own `sdkconfig.defaults`. Channel and bandwidth
are **not** Kconfig here -- they come from the patch.

## Board register (fill in during bring-up)

| Role | Chip MAC | Serial port | esp-csi SHA | flashed |
|---|---|---|---|---|
| tx (csi_send) | `68:09:47:26:ee:14` | `/dev/tty.usbserial-0001` | 8633d67 | yes |
| rx (csi_recv) | `68:09:47:9e:fd:a4` | `/dev/tty.usbserial-5` | 8633d67 | yes |

Both are ESP32-D0WD-V3 rev v3.1. The esp-csi example overrides the STA MAC to
`1a:00:00:00:00:00` on both, so on-air frames carry that, not the chip MACs.

## Confirmed serial format (bench capture, boards on desk)

Header line the example prints on ESP32 (matches `FIELD_SPEC`, 24 fields + data):

```
type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,
stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,
local_timestamp,ant,sig_len,rx_format,len,first_word,data
```

Real line:
```
CSI_DATA,12719,1a:00:00:00:00:00,-1,11,1,0,0,1,1,0,0,0,0,-96,0,6,0,17122706,0,47,1,256,1,"[47,-16,2,0,-128,...]"
```

- **`len = 256`** -> 128 subcarriers: a 64-bin LLTF followed by a 64-bin HT-LTF.
  `csi_io.load(..., ltf="htltf")` (default) slices the HT-LTF half -> `(N, 64)`.
- Pair order for the HT-LTF half comes out **`re_im`** (derived, logged) --
  opposite the documented LLTF `(imag, real)`, which is exactly why we derive it.
- `first_word = 1` on many packets; the first int8 quad `47,-16,2,0` is the
  invalid first word -- it lands in the DC/guard null region and is dropped by
  the active-subcarrier derivation anyway.
- Packet rate ~82-92 Hz at the bench (sender at 100). Above the 50 Hz floor;
  retune later if it drops under load.
- A raw sample is committed at `data/REAL_probe_raw.txt`.

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
