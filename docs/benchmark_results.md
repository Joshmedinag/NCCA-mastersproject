# Frame-first Benchmark Results

## Recorded run

- Date (UTC): 2026-08-08
- Platform: Windows 11
- Python: 3.12.12
- NumPy: 2.4.6
- OpenEXR: 3.4.12
- Dataset: 12 frames, 5 colour AOVs, 320 x 180 pixels
- Repetitions: 3 per strategy

| Measure | AOV-first | Frame-first | Change |
| --- | ---: | ---: | ---: |
| Application-level read calls | 60 | 12 | 5.00x fewer |
| Median elapsed time | 0.3255 s | 0.0800 s | 4.07x faster |
| Minimum elapsed time | 0.3228 s | 0.0794 s | 4.06x faster |
| Median Python peak memory | 5,577,044 B | 11,084,492 B | 1.99x higher |
| Pixel checksum | 5,365,412.4943 | 5,365,412.4943 | Identical |

## Interpretation

The deterministic result is the reduction from `frames x AOVs` reader calls to
one reader call per frame. The matching checksum confirms that both strategies
consumed equivalent decoded pixel values for this fixture.

On this run, frame-first processing was also about four times faster. It held
all five AOV arrays for the current frame at once, which explains the higher
Python-tracked peak memory. It still does not retain the complete sequence.
This is a useful trade-off: memory scales primarily with one frame's requested
AOVs rather than with every frame in the sequence.

Timing and memory are contextual rather than universal. Filesystem caching,
compression, disk speed, resolution and AOV count can change the result.
`tracemalloc` excludes native allocations inside OpenEXR. The exact raw output
is stored in `experiments/benchmark_results.json`; the method and limitations
are defined in `docs/benchmark_methodology.md`.
