# Usage

## UI workflow

Start the interface:

```powershell
uv run aovguard-ui
```

1. Select an EXR file or folder.
2. Optionally select a TOML or JSON rule preset.
3. Select Rec.709 or Rec.601 luminance.
4. Use **Inspect Structure** to review detected channels and AOVs.
5. Click **Analyze**.
6. Review metrics and findings.
7. Export the canonical JSON report.

The GUI automatically inspects the EXR structure and does not require manual
Simple or Multilayer selection.

## CLI workflow

Inspect an EXR structure:

```powershell
uv run aovguard inspect-structure ./renders/shot.1001.exr
```

Analyze a file or folder:

```powershell
uv run aovguard analyze ./renders --json ./reports/report.json
```

Analyze with a rule preset:

```powershell
uv run aovguard analyze ./renders --rules-config ./config/rules.example.toml --json ./reports/report.json
```

The legacy `analyze-simple`, `analyze-multilayer` and `inspect` commands remain
available temporarily for compatibility.
