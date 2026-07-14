# Limitations

AOVGuard is a prototype Pipeline TD tool, not a replacement for a full studio render validation system.

Current limitations:

- The analysis uses luminance statistics, so it cannot understand artistic intent.
- Thresholds should be calibrated for real shows and render settings.
- The multilayer reader expects RGB groups named `aovName.R`, `aovName.G`, `aovName.B`.
- Sequence results are aggregated per AOV. A future version should include per-frame warnings.
- The UI is intentionally simple and does not yet expose every advanced CLI option.
