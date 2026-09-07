#!/usr/bin/env bash
# Phase 1.1 -- install ESP-IDF v5.3.1 for the esp32 target (NOT s3 / c3).
# Idempotent: safe to re-run.
set -euo pipefail

ESP_DIR="${ESP_DIR:-$HOME/esp}"
IDF_TAG="v5.3.1"

mkdir -p "$ESP_DIR"
cd "$ESP_DIR"

if [ ! -d "$ESP_DIR/esp-idf/.git" ]; then
  git clone -b "$IDF_TAG" --recursive https://github.com/espressif/esp-idf.git
else
  echo "esp-idf already cloned at $ESP_DIR/esp-idf"
fi

cd "$ESP_DIR/esp-idf"
git fetch --tags --quiet
git checkout "$IDF_TAG"
git submodule update --init --recursive

# macOS python.org framework builds ship without a usable CA bundle, so the IDF
# tool downloads fail with CERTIFICATE_VERIFY_FAILED. Point urllib at certifi's
# bundle for the install (scoped -- no system change).
if [ -z "${SSL_CERT_FILE:-}" ]; then
  CERTIFI_PEM="$(python3 -m certifi 2>/dev/null || true)"
  if [ -n "$CERTIFI_PEM" ] && [ -f "$CERTIFI_PEM" ]; then
    export SSL_CERT_FILE="$CERTIFI_PEM"
    echo "using SSL_CERT_FILE=$SSL_CERT_FILE for tool downloads"
  fi
fi

./install.sh esp32

cat <<'EOF'

--------------------------------------------------------------------
ESP-IDF installed.

Source this in EVERY new shell before using idf.py:

    . ~/esp/esp-idf/export.sh

macOS: if no /dev/tty.usbserial* or /dev/tty.SLAB_USBtoUART appears
when a board is plugged in, install the Silicon Labs CP210x VCP
driver and reboot.

Next: scripts/clone_esp_csi.sh
--------------------------------------------------------------------
EOF
