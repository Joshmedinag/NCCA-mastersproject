# Troubleshooting

## `pip: command not found`

Use:

```powershell
python -m pip install uv
```

or install uv with:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Python 3.9 is not supported

Install Python 3.12 using uv:

```powershell
uv python install 3.12
uv sync --python 3.12 --extra dev
```

## `OpenEXR codec is disabled`

Set this environment variable before running tests or the app:

```powershell
$env:OPENCV_IO_ENABLE_OPENEXR="1"
```

Then run:

```powershell
uv run pytest
```

or:

```powershell
uv run aovguard-ui
```

## `No RGB AOV groups found in the EXR files`

This means the selected EXR does not contain multilayer RGB AOV groups.

Try one of the following:

- use **Simple Mode** if the EXR only has `R`, `G`, `B`, `A`;
- check that **Merge AOVs** was enabled when exporting from Maya/Arnold;
- use **Inspect First EXR** to see what channels exist in the file.

## `0 AOVs analyzed`

This usually means that no `.exr` files were found directly inside the selected folder or in one-level subfolders.

## The UI freezes or seems slow

The analysis now runs in a worker thread and updates a progress bar. Large EXRs can still take time to read, especially multilayer files, but the progress indicator should show that the tool is working.
