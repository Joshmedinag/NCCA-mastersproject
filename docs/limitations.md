# Limitations

AOVGuard is a prototype Pipeline TD tool, not a replacement for a full studio render validation system.

Current limitations:

- The analysis uses luminance statistics, so it cannot understand artistic intent.
- Thresholds should be calibrated for real shows and render settings.
- Colour analysis expects identifiable RGB channel roles. Supported technical
  AOVs receive objective channel statistics and NaN/Inf checks, but do not yet
  have renderer-specific semantic validation.
- Deep and multipart structures are detected but intentionally rejected by the
  MVP analysis backend.
- Sequence metrics are aggregated per AOV. Resolution and AOV-structure
  differences identify the affected frame, but aggregate pixel findings do not
  yet provide full per-frame metric histories.
- Default frame discovery uses direct EXRs when present and ignores nested EXRs
  with a warning. Optional recursive discovery, filename patterns and bounded
  depth are available. The sequence checker detects gaps, duplicate frame numbers, and
  inconsistent padding by interpreting the final numeric token in each filename.
  Show-specific naming parsers and a visual sequence picker remain future work.
