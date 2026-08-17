# AOVGuard

**Current stable release: 1.0.0**

AOVGuard is a small Pipeline TD validation tool for checking EXR render outputs. It helps artists and technical directors identify whether render passes / AOVs contain useful image data or whether they are empty, nearly empty, or need manual review before the renders move further down the pipeline.

The main focus of the project is **multilayer EXR AOV validation**, especially for renders exported from DCC/rendering tools such as **Maya/Arnold** with **Merge AOVs** enabled.

---

## Project Context

In a VFX or animation pipeline, lighting artists often export multiple AOVs or render passes for compositing. Some of these passes are useful, while others may be completely black or almost empty. Empty AOVs can create unnecessary storage usage, longer transfer/review times, and confusion for compositors.

AOVGuard provides a lightweight validation step before the render is published or passed downstream.

---

## Current Version Updates

The current backend automatically inspects EXR channels, parts and AOV
structure. Users no longer select Simple or Multilayer mode in the main CLI or
GUI workflow. Each supported frame is opened once during analysis and its
colour AOVs are normalised to RGB before metrics and rules are evaluated.
Technical AOVs such as `Z`, `N` and `P` are diagnosed per channel without
being sent through a colour-luminance formula.

The canonical JSON report uses schema version `1.0`, never emits non-standard
NaN/Infinity tokens, and reports discovered, successful and failed frames
separately.

Sources can be interpreted automatically, explicitly as a numbered sequence,
or as an independent comparison set. The report records the resolved source
kind so sequence gaps are never confused with deliberate look comparisons.

---

## Features

- Automatically inspect simple and multilayer EXR channel structures.
- Detect colour, scalar, vector, mask, depth and unknown AOV categories.
- Normalise colour AOVs to an internal RGB convention.
- Calculate non-black ratio and signed/absolute luminance metrics.
- Record per-channel min/average/max, non-finite and negative-value counts for
  supported scalar, vector, mask and depth AOVs.
- Validate NaN/Inf, empty and near-empty AOVs, missing AOVs/channels,
  negative values, constant channels and sequence consistency.
- Group numbered EXR sequences and detect missing frames, duplicate frame
  numbers and inconsistent padding without decoding pixels.
- Select frames with an explicit filename pattern, optional recursive search
  and bounded folder depth.
- Load validation rules from TOML or JSON presets.
- Display progress during analysis using a UI progress bar.
- Show explicit PASS, WARNING or FAIL status and per-frame diagnostic metrics.
- Compute robust cross-frame statistics using median, median absolute deviation
  (MAD), consecutive-frame deltas and outlier samples.
- Preserve per-file evidence for aggregate empty and near-empty AOV findings.
- Compare a current analysis against a previous canonical JSON report in both
  the CLI and GUI.
- Support cooperative GUI cancellation after the current frame completes.
- Export a strict, schema-versioned JSON report.
- Export a self-contained HTML report with status, metrics, sequences,
  findings and recommendations.
- Filter GUI findings by severity, text or failed-frame status and inspect
  detailed evidence for each result.
- Use compact source-relative paths, automatic result-tab selection and
  per-frame change columns for faster comparison.
- Preserve the last source, preset, luminance and discovery settings between
  GUI sessions.
- Collapse secondary analysis settings and logs to keep the results area
  focused, while retaining contextual empty states and column controls.
- Provide contextual hover definitions for controls, validation rules, result
  tabs, table metrics and inferred AOV meanings.
- Provide a simple PySide6 graphical user interface.
- Provide a command-line interface for pipeline-style usage.
- Include automated tests with branch coverage using `pytest-cov`.

---

## Automatic EXR Structure Inspection

Regular RGB/RGBA files with channels such as the following are detected as a
`beauty` colour AOV:

```text
R
G
B
A
```

Named multilayer channels are grouped automatically, for example:

```text
albedo.R
albedo.G
albedo.B

diffuse_direct.R
diffuse_direct.G
diffuse_direct.B

specular_direct.R
specular_direct.G
specular_direct.B

emission.R
emission.G
emission.B
```

A real test was completed using a multilayer EXR exported from **Maya/Arnold**
with **Merge AOVs** enabled. AOVGuard detected the following structure:

```text
Z
P
N
albedo
diffuse_direct
specular_direct
emission
```

`N` and `P` are recognised as vectors, `Z` as depth, and colour AOVs are
analyzed using luminance rules. Deep and multipart EXRs are detected and
reported as unsupported by the MVP backend rather than silently interpreted as
ordinary files.

---

## Requirements

Recommended:

```text
Python 3.12
uv
```

Python 3.9 is not supported.

---

## Installation

### 1. Install uv

If `uv` is not installed, install it with:

```powershell
python -m pip install uv
```

Or install it from Astral:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Open the correct project folder

Make sure you are inside the folder that contains:

```text
pyproject.toml
README.md
src
tests
docs
examples
reports
```

Example:

```powershell
cd "C:\Users\josha\Downloads\aovguard_progress_final\aovguard_with_ui_polished"
```

### 3. Install Python 3.12

```powershell
uv python install 3.12
```

### 4. Install dependencies

```powershell
uv sync --python 3.12 --extra dev
```

---

## Running the Tests

Before running tests on Windows, enable OpenEXR support for OpenCV:

```powershell
$env:OPENCV_IO_ENABLE_OPENEXR="1"
```

Then run:

```powershell
uv run pytest
```

The default test configuration measures statement and branch coverage for the
`aovguard` package and prints missing lines. CI also enforces a 90% minimum:

```powershell
uv run pytest --cov-fail-under=90
```

---

## Running the UI

Run:

```powershell
uv run aovguard-ui
```

---

## How to Use the UI

1. Select an EXR file or render folder.
2. Optionally select a TOML or JSON validation preset.
3. Select Rec.709, Rec.601 or custom RGB luminance weights.
4. Under **Analysis Settings**, leave source interpretation on **Auto** or
   choose **Sequence** / **Comparison** explicitly.
5. Click **Inspect Structure** to review detected channels and AOVs.
6. Click **Analyze**.
7. Review the **Findings**, **Metrics**, **Frames/Samples**, **Technical** and
   **Sequences** tabs. The GUI opens the most relevant result automatically.
8. Filter findings; the first visible result is selected automatically and its
   evidence and recommended action are displayed.
9. Use **Median Change** and **Previous Change** to inspect variation without
   treating the first decoded frame as an unquestioned baseline.
10. Export JSON/HTML, or use **Compare Baseline** to compare the current result
    with a previously exported canonical JSON report.

The current GUI uses automatic EXR structure inspection and no longer asks the
user to choose Simple or Multilayer mode manually.

The GUI also reports the detected AOV categories and allows individual
validation rules to be enabled or disabled. Channel-level NaN/Inf, negative
values and constant-channel checks are available, together with frame-to-frame
resolution and AOV-structure consistency checks.

For folders, **Frame Pattern** filters filenames. **Recursive** includes direct
and nested matches up to **Max Depth**. Analysis stops when recursive discovery
finds multiple numbered sequences unless **Allow Multiple Sequences** is
enabled explicitly.

---

## Exporting Multilayer EXRs from Maya / Arnold

To create a multilayer EXR from Maya using Arnold:

1. Open **Render Settings**.
2. Set **Render Using** to `Arnold Renderer`.
3. Go to the **AOVs** tab.
4. Add AOVs such as:

```text
RGBA
albedo
diffuse_direct
specular_direct
emission
N
P
Z
```

5. Go to the **Common** tab.
6. Set **Image Format** to `exr`.
7. Enable **Merge AOVs**.
8. Render the frame or sequence.

The resulting EXR should contain channels such as:

```text
albedo.R
albedo.G
albedo.B
diffuse_direct.R
diffuse_direct.G
diffuse_direct.B
specular_direct.R
specular_direct.G
specular_direct.B
```

This structure is detected automatically by the current backend.

---

## Command-Line Usage

### Inspect an EXR

```powershell
uv run aovguard inspect-structure ./renders/shot.1001.exr
```

### Analyze an EXR file or folder

```powershell
uv run aovguard analyze ./renders --json ./reports/report.json --html ./reports/report.html
```

Use explicit discovery when renders are nested or a folder contains several
outputs:

```powershell
uv run aovguard analyze ./renders --frame-pattern "beauty.*.exr" --recursive --max-depth 2 --json ./reports/beauty.json
```

Add `--allow-multiple-sequences` only when combining independent numbered
sequences is intentional. Add `--fail-on-warning` in CI or publishing scripts
when warnings must fail the command. `analyze` returns `0` for PASS and, by
default, WARNING; it returns `1` for FAIL or for WARNING in strict mode.

Use `--source-mode sequence` to require numbered frames, or
`--source-mode comparison` to treat every discovered EXR as an independent
sample. The default `auto` mode resolves one file, a numbered sequence, or a
comparison set from the discovered names.

### Compare two canonical reports

```powershell
uv run aovguard compare-reports ./reports/baseline.json ./reports/candidate.json --json ./reports/comparison.json
```

The comparison records added, removed, changed and unchanged AOV metrics plus
new and resolved findings.

### Check sequence names and gaps without reading pixels

```powershell
uv run aovguard check-sequence ./renders
```

The checker recognises patterns such as `shot.1001.exr` and
`shot_1001.exr`, reports compact missing ranges, separates multiple sequences
and flags duplicate frame numbers or mixed padding widths.

### Analyze with a rule preset

```powershell
uv run aovguard analyze ./renders --rules-config ./config/rules.example.toml --json ./reports/report.json
```

The legacy `inspect`, `analyze-simple` and `analyze-multilayer` commands remain
available temporarily for comparison and backward compatibility. Their output
schema and classification model are not the canonical AOVGuard 2.0 workflow.

---

## Legacy Classification Meaning

The following labels belong to the temporary legacy commands. The canonical
backend reports metrics and rule findings instead.

### Active

The AOV contains clear image information and is likely useful.

### Review Recommended

The AOV contains some data, but the contribution is weak or limited. This does not always mean the AOV is wrong, but it should be checked manually.

### Nearly Empty

The AOV contains very little information and may not be useful.

### Empty

The AOV appears to contain no meaningful information. For example, an `emission` AOV may be empty if the scene has no emissive materials.

---

## Evidence

The current AOVGuard 2.0 interface is shown here:

```text
website/assets/aovguard-current-ui.png
```

The documentation also retains two historical screenshots from the original
prototype. They demonstrate successful tests with real EXR files, but their
manual Simple/Multilayer controls and table layout are not the current 2.0 UI:

```text
docs/images/01_real_maya_multilayer_result.png
docs/images/04_real_simple_exr_result.png
```

No EXR image data is generated or bundled with the project. The `examples/`
directory is intentionally empty so that authorised real production or test
renders can be copied there when needed. EXRs can also be selected directly
from any location through the CLI or GUI without copying them into the project.

---

## Project Structure

```text
aovguard_with_ui_polished/
  README.md
  pyproject.toml
  src/
    aovguard/
      __init__.py
      analysis_core.py
      cli.py
      config.py
      simple.py
      multilayer.py
      ui.py
      sequence/
        sequence_checker.py
      reports/
        json_report.py
        html_report.py
  tests/
  docs/
  examples/
  reports/
  config/
```

---

## Troubleshooting

### `pip: command not found`

Use:

```powershell
python -m pip install uv
```

### Python 3.9 is not supported

Install Python 3.12 using uv:

```powershell
uv python install 3.12
uv sync --python 3.12 --extra dev
```

### `OpenEXR codec is disabled`

Set this environment variable before running tests or the app:

```powershell
$env:OPENCV_IO_ENABLE_OPENEXR="1"
```

### `No RGB AOV groups found in the EXR files`

This means the selected EXR does not contain multilayer RGB AOV groups.

Try one of the following:

- check that **Merge AOVs** was enabled when exporting from Maya/Arnold;
- use **Inspect Structure** to see what channels and AOVs exist in the file.

### `0 AOVs analyzed`

This usually means that no files matched the selected frame pattern, or that
the relevant nested folder is deeper than the configured discovery depth.

---

## Limitations

- Luminance metrics apply only to colour AOVs. Supported technical passes such
  as `Z`, `N`, and `P` receive objective per-channel statistics and NaN/Inf
  validation, but not yet renderer-specific semantic rules.
- Deep and multipart files are detected but not analyzed by the MVP backend.
- Thresholds are conservative and may need adjustment per project.
- Sequence inference uses the final numeric block in each EXR filename. The
  filename glob and recursion depth are configurable, but show-specific token
  parsers are not implemented.
- The tool does not replace artistic judgement; it is designed as a validation aid.
- Unreal EXRs may export as simple RGBA files unless render passes are configured separately.

---

## Future Improvements

Possible future improvements include:

- renderer-aware rules for technical AOVs;
- configurable thresholds in the UI;
- clearer visual previews;
- packaged executable using PyInstaller;
- automated Sphinx documentation;
- Docker-based deployment for reproducible environments.

---

## Project Evidence and References

- [Technical references](docs/references.md) provides annotated primary sources
  for EXR, OpenEXR, OpenImageIO, luminance standards, testing and VFX platform
  compatibility.
- [Project management](docs/project_management.md) records milestones,
  architectural decisions, risks and the definition of done.
- [Architecture](docs/architecture.md) describes the shared backend and data
  flow used by the CLI and GUI.
- [Evaluation plan](docs/evaluation_plan.md) defines correctness, performance,
  coverage and usability evidence.
- [Benchmark results](docs/benchmark_results.md) compare AOV-first and
  frame-first processing using a controlled benchmark dataset. Final project
  evaluation should additionally record results from authorised real EXRs.
- [Changelog](CHANGELOG.md) records release-level changes.
- [Citation metadata](CITATION.cff) and the [MIT licence](LICENSE) describe how
  to cite and reuse the software.
- [Project website](website/index.html), [video script](docs/demo_script.md),
  [presentation outline](docs/presentation_outline.md) and
  [submission checklist](docs/submission_checklist.md) support the final MSc
  delivery.

Create a clean submission archive without virtual environments or caches.
Only EXRs deliberately placed under `examples/` are included:

```powershell
uv run python scripts/create_release.py
```
