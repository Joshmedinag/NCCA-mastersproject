# Evaluation Plan

The tool should be evaluated with real EXR outputs from DCC/rendering software.

## Simple EXR evaluation

1. Export or collect a normal RGB/RGBA EXR.
2. Place the file inside a test folder.
3. Run AOVGuard in Simple mode.
4. Confirm that the file appears in the table and is classified correctly.

## Multilayer EXR evaluation

1. Export a multilayer EXR from Maya/Arnold with Merge AOVs enabled.
2. Include AOVs such as `albedo`, `diffuse_direct`, `specular_direct`, and `emission`.
3. Run **Inspect First EXR** to confirm the channel structure.
4. Run the analysis in Multilayer mode.
5. Check that active AOVs are detected and empty AOVs are flagged.

## Documentation evidence

Screenshots of successful tests are included in `docs/images/`.
