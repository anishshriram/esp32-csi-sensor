#!/usr/bin/env bash
# Regenerate the synthetic demo dataset in data/SYNTH_* and figures in results/.
# These are git-ignored (regenerable); real recordings are committed.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"

mkdir -p data results

for s in empty walking sitting; do
  "$PY" -m csi_sensing.synth --scenario "$s" --duration 180 --bpm 15 \
      --out "data/SYNTH_${s}_los_2m.csv" --meta
done
"$PY" -m csi_sensing.synth --scenario mixed --duration 360 --bpm 14 \
    --out data/SYNTH_mixed_los_2m.csv --meta
for b in 10 12 15 18 20; do
  "$PY" -m csi_sensing.synth --scenario sitting --duration 160 --bpm "$b" \
      --out "data/SYNTH_metronome_${b}bpm.csv" --meta
done
for s in empty sitting; do
  "$PY" -m csi_sensing.synth --scenario "$s" --duration 160 --bpm 15 --wall \
      --out "data/SYNTH_${s}_wall_2m.csv" --meta
done

for s in empty walking sitting; do
  "$PY" -m csi_sensing.plots.plot_heatmap "data/SYNTH_${s}_los_2m.csv" \
      --out "results/heatmap_${s}.png"
done
"$PY" -m csi_sensing.plots.plot_diagnostic data/SYNTH_sitting_los_2m.csv --out results/agc_diagnostic.png
"$PY" -m csi_sensing.plots.plot_respiration data/SYNTH_metronome_15bpm.csv --truth-bpm 15 \
    --out results/respiration_15bpm.png
"$PY" -m analysis.characterize analysis/SYNTH_manifest.csv --outdir results

echo "done -- data/SYNTH_*  results/*"
