# Architecture

AOVGuard now uses a shared backend for CLI and GUI analysis.

## Main flow

```text
EXR file or folder
  -> frame discovery
  -> one OpenEXR.File read per supported frame
  -> structure inspection from the same read
  -> canonical RGB color AOV data
  -> incremental AOV and per-channel metrics
  -> configurable validation rules
  -> AnalysisReport
  -> CLI / GUI / JSON report
```

## Main modules

- `core/models.py` defines inspections, AOV descriptors, metrics, findings,
  options and reports.
- `core/luminance.py` provides Rec.709, Rec.601 and custom luminance weights.
- `core/analysis.py` coordinates discovery, reading, incremental metrics and
  rule execution.
- `discovery/frame_discovery.py` provides the exact frame list used for
  analysis and reporting.
- `io/inspector.py` infers AOV structure and approximate categories from
  channel names.
- `io/reader.py` implements the current OpenEXR backend.
- `rules/` contains configurable rule definitions, loading, registration and
  isolated execution. Built-in checks include channel NaN/Inf, negative values,
  constant channels, empty AOVs, resolution mismatch and AOV-structure mismatch.
- `reports/json_report.py` writes the canonical JSON report.
- `cli.py` provides the new `analyze` and `inspect-structure` commands while
  retaining legacy commands temporarily.
- `ui.py` provides the PySide6 interface over the same backend.

## Progress feedback

The shared analysis API accepts an optional progress callback. The GUI worker
runs in a `QThread` and updates the progress bar after each frame.

`FrameData` carries its `FileInspection`, so analysis does not perform a second
header read. Reports distinguish discovered, successfully processed and failed
frames. The JSON schema converts non-finite metric values to `null` while
preserving NaN/Inf counts in the associated metrics and findings.
