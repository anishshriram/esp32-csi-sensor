#!/usr/bin/env bash
# Apply the CSI firmware patches to a cloned esp-csi tree.
#
#   firmware/apply_patches.sh              # uses $ESP_DIR/esp-csi or ~/esp/esp-csi
#   firmware/apply_patches.sh <esp-csi>    # explicit path
#
# Patches target esp-csi rev 8633d67. If `git apply` rejects them (the tree
# moved), redo the changes by hand from firmware/README.md -- they are small.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ESP_CSI="${1:-${ESP_CSI_DIR:-${ESP_DIR:-$HOME/esp}/esp-csi}}"

[ -d "$ESP_CSI/.git" ] || { echo "not an esp-csi checkout: $ESP_CSI" >&2; exit 1; }

cd "$ESP_CSI"
HAVE_REV="$(git rev-parse --short HEAD)"
[ "$HAVE_REV" = "8633d67" ] || echo "warning: esp-csi is at $HAVE_REV, patches were made against 8633d67"

for p in "$REPO_ROOT"/firmware/patches/*.patch; do
  echo "applying $(basename "$p")"
  git apply --check "$p" && git apply "$p"
done

echo
echo "patched. Build:"
echo "  scripts/build_firmware.sh $ESP_CSI/examples/get-started/csi_send <tx port> tx"
echo "  scripts/build_firmware.sh $ESP_CSI/examples/get-started/csi_recv <rx port> rx"
echo "To revert:  git -C $ESP_CSI checkout -- ."
