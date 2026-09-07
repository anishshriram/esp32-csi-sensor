"""Through-wall WiFi CSI sensing toolkit.

Package layout:
    serial_format  -- parse one esp-csi serial line into a dict
    synth          -- synthetic CSI generator (ground-truth known)
    capture        -- host-side serial logger (CLI)
    csi_io         -- load a capture CSV into a complex CSI array + metadata
    agc            -- AGC gain normalization
    presence       -- Phase 3 presence detection
    respiration    -- Phase 4 respiration-rate extraction
    reference      -- Phyphox ground-truth loader + clock alignment
    metrics        -- scoring helpers (presence accuracy/latency, respiration MAE)
    plots/         -- diagnostic and result figures
    deploy/        -- live pipeline + MQTT publisher
"""
from csi_sensing.serial_format import FIELD_SPEC

__version__ = "0.1.0"

# Capture CSV schema: host wall-clock first, then every parsed esp-csi field
# (nothing from rx_ctrl is dropped at capture time), then the raw int8 payload.
CAPTURE_COLUMNS = ["host_ts", *[name for name, _ in FIELD_SPEC], "data"]

# Fields the analysis pipeline depends on being present and correct.
REQUIRED_FIELDS = ("host_ts", "agc_gain", "rssi", "noise_floor", "data")
