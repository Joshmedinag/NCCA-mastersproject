# Results Evidence

The repository includes screenshots showing AOVGuard working with real EXR files.

## Real Maya/Arnold multilayer result

File: `docs/images/01_real_maya_multilayer_result.png`

This shows a real multilayer EXR exported from Maya/Arnold using Merge AOVs.
The current backend detects 25 channels and 8 AOV descriptors:

```text
Z
specular_direct
P
N
emission
diffuse_direct
albedo
```

`beauty`, `albedo`, `diffuse_direct`, `specular_direct`, and `emission` are
analysed as colour. `N` and `P` are recognised as vectors and `Z` as depth.
The `empty_aov` rule reports `emission`; the technical passes are not subjected
to colour luminance rules.

## Real simple EXR result

File: `docs/images/04_real_simple_exr_result.png`

This shows a real simple EXR from the earlier interface. The current automatic
backend detects the root RGB/RGBA channels as a `beauty` colour AOV without a
manual mode selection.

## Large EXR note

The real multilayer EXR file is not included in the repository because it is too large. The screenshots are included as evidence of the successful test.
