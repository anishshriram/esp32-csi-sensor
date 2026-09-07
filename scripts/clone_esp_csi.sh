#!/usr/bin/env bash
# Phase 1.2 -- clone esp-csi. The tree layout changes between revisions, so read
# the top-level README rather than assuming example paths.
set -euo pipefail

ESP_DIR="${ESP_DIR:-$HOME/esp}"
mkdir -p "$ESP_DIR"
cd "$ESP_DIR"

if [ ! -d "$ESP_DIR/esp-csi/.git" ]; then
  git clone https://github.com/espressif/esp-csi.git
else
  echo "esp-csi already cloned"; cd esp-csi && git pull --ff-only || true
fi

echo
echo "esp-csi at $ESP_DIR/esp-csi"
echo "Read:   $ESP_DIR/esp-csi/README.md"
echo "Start from the CSI receive example (commonly examples/get-started/csi_recv"
echo "or examples/esp-radar/*). Confirm the path in the README before building."
echo
echo "Set ESP_CSI_DIR so capture.py can record the firmware git SHA:"
echo "    export ESP_CSI_DIR=$ESP_DIR/esp-csi"
