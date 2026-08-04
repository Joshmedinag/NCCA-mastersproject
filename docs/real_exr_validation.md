# Real EXR Validation Checklist

Before using AOVGuard on production-style renders, check:

- Are the EXRs readable by OpenEXR or OpenCV?
- Are the AOV channel names consistent across frames?
- Do multilayer AOVs use the pattern `aovName.R`, `aovName.G`, `aovName.B`?
- Are thresholds appropriate for the show, colour pipeline and renderer?
- Does the discovered frame list match the intended sequence? AOVGuard sorts
  numeric frame tokens naturally, but automatic gap detection is not yet part
  of the MVP.
- Are output report paths writable?

For best results, start with a short sequence, tune thresholds, then run on a larger render folder.
