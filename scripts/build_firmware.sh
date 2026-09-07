#!/usr/bin/env bash
# Phase 1.2/1.3 -- build + flash one esp-csi role to one board, then print its MAC.
#
#   scripts/build_firmware.sh <example_dir> <port> [tx|rx]
#
# <example_dir> is an esp-csi example project (e.g. .../get-started/csi_recv).
# Run firmware/apply_patches.sh first (HT20 + channel + agc_gain).
set -euo pipefail

EXAMPLE_DIR="${1:?usage: build_firmware.sh <example_dir> <port> [tx|rx]}"
PORT="${2:?need serial port, e.g. /dev/tty.SLAB_USBtoUART}"
ROLE="${3:-rx}"

if ! command -v idf.py >/dev/null; then
  echo "idf.py not found -- run:  . ~/esp/esp-idf/export.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$EXAMPLE_DIR"

# merge our Kconfig defaults into the example's own (append; our keys win)
DEF="$REPO_ROOT/firmware/sdkconfig.defaults.$ROLE"
if [ -f "$DEF" ] && ! grep -q "csi-sensor merged" sdkconfig.defaults 2>/dev/null; then
  { echo ""; echo "# --- csi-sensor merged ---"; cat "$DEF"; } >> sdkconfig.defaults
  rm -f sdkconfig
  echo "merged $DEF into sdkconfig.defaults"
fi

idf.py set-target esp32
idf.py build
idf.py -p "$PORT" flash

echo
echo "Flashed $ROLE to $PORT. Reading MAC:"
idf.py -p "$PORT" monitor | sed -n '1,40p' &
MON=$!
sleep 8 || true
kill "$MON" 2>/dev/null || true
echo
echo "Record this board's MAC + role in firmware/README.md."
