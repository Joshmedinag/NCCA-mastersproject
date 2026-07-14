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

Runs the shared backend in a worker thread. The progress bar updates once each
frame has been inspected and processed.

The **Metrics** tab contains aggregated color-AOV metrics. The **Findings** tab
contains validation warnings and errors, including channel-level findings and
sequence inconsistencies.

The structure summary distinguishes color, vector, depth, mask, scalar and
unknown AOVs.

## Export JSON

Exports the canonical structured report, including frames, inspections,
metrics, executed rules and findings.
