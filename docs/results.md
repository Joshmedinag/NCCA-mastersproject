# Results Evidence

The repository includes screenshots showing AOVGuard working with real EXR files.

## Real Maya/Arnold multilayer result

File: `docs/images/01_real_maya_multilayer_result.png`

This shows a real multilayer EXR exported from Maya/Arnold using Merge AOVs. The tool detected AOVs such as:

```text
Z
specular_direct
P
N
emission
diffuse_direct
albedo
```

Most AOVs were classified as `Active`, while `emission` was classified as `Empty`.

## Real simple EXR result

File: `docs/images/04_real_simple_exr_result.png`

This shows a real simple EXR being analyzed in Simple mode. The render was classified as `Active`, showing that AOVGuard can also validate regular RGBA EXR renders.

## Large EXR note

The real multilayer EXR file is not included in the repository because it is too large. The screenshots are included as evidence of the successful test.
