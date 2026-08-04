# UI Guide

AOVGuard uses automatic EXR structure inspection. The user no longer selects
Simple or Multilayer mode manually.

## EXR Source

Use **File** to select one EXR or **Folder** to select an EXR sequence.

## Rule Preset

The default validation rules run when no preset is selected. Use **Browse** to
load an optional TOML or JSON rule preset.

Individual rules can be enabled or disabled using the validation-rule
checkboxes. NaN/Inf, empty AOV and sequence consistency checks are enabled by
default. Negative-value and constant-channel checks are optional because their
meaning can depend on the AOV and production.

## Luminance

Choose Rec.709 or Rec.601 for color AOV luminance metrics.

## Inspect Structure

Inspects the first discovered EXR and displays dimensions, channels, inferred
AOVs, approximate AOV categories, part count and deep-data status.

## Analyze

Runs the shared backend in a worker thread. Structure and pixels are obtained
from one OpenEXR file object per supported frame. The progress bar reports each
attempt and the final status distinguishes successful and failed frames.

The **Metrics** tab contains aggregated color-AOV metrics. The **Findings** tab
contains validation warnings and errors, including channel-level findings and
sequence inconsistencies.

The structure summary distinguishes color, vector, depth, mask, scalar and
unknown AOVs.

## Export JSON

Exports strict JSON schema version `1.0`, including discovered/successful/failed
frames, inspections, metrics, executed rules and findings. Non-finite numeric
metrics are represented as `null`, with their counts retained separately.
