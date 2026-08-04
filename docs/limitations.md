# Limitations

AOVGuard is a prototype Pipeline TD tool, not a replacement for a full studio render validation system.

Current limitations:

- The analysis uses luminance statistics, so it cannot understand artistic intent.
- Thresholds should be calibrated for real shows and render settings.
- Colour analysis expects identifiable RGB channel roles. Technical AOVs are
  inspected but do not yet have pass-specific pixel validation.
- Deep and multipart structures are detected but intentionally rejected by the
  MVP analysis backend.
- Sequence metrics are aggregated per AOV. Resolution and AOV-structure
  differences identify the affected frame, but aggregate pixel findings do not
  yet provide full per-frame metric histories.
- Frame discovery uses direct EXRs when present and ignores nested EXRs with a
  warning. Advanced multi-sequence selection and gap detection remain future work.
- The UI is intentionally simple and does not yet expose every advanced CLI option.
