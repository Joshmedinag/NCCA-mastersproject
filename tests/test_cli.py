import json
from pathlib import Path

import Imath
import numpy as np
import OpenEXR
import pytest

from aovguard.cli import main


def _channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(path: Path, width: int, height: int, channels: dict[str, float]) -> None:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {name: Imath.Channel(pixel_type) for name in channels}
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                name: _channel(value, width, height)
                for name, value in channels.items()
            }
        )
    finally:
        output.close()


def _test_exr(path: Path) -> Path:
    _write_exr(
        path,
        2,
        2,
        {
            "R": 1.0,
            "G": 2.0,
            "B": 3.0,
            "diffuse.R": 4.0,
            "diffuse.G": 5.0,
            "diffuse.B": 6.0,
            "Z": 10.0,
        },
    )
    return path


def test_cli_help_keeps_legacy_commands(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "analyze-simple" in out
    assert "analyze-multilayer" in out
    assert "inspect" in out
    assert "inspect-structure" in out
    assert "analyze" in out


def test_cli_inspect_structure_prints_detected_aovs(tmp_path: Path, capsys) -> None:
    exr_path = _test_exr(tmp_path / "shot.1001.exr")

    main(["inspect-structure", str(exr_path)])

    out = capsys.readouterr().out
    assert "Detected AOVs" in out
    assert "beauty: color" in out
    assert "diffuse: color" in out
    assert "Z: depth" in out


def test_cli_analyze_writes_new_json_report(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.1001.exr")
    report_path = tmp_path / "report.json"

    main(
        [
            "analyze",
            str(tmp_path),
            "--json",
            str(report_path),
            "--preset",
            "lighting_delivery",
            "--luminance-model",
            "rec601",
        ]
    )

    out = capsys.readouterr().out
    assert "Frames processed: 1" in out
    assert "beauty" in out
    assert "diffuse" in out
    payload = json.loads(report_path.read_text())
    assert payload["metadata"]["frames_processed"] == 1
    assert payload["metadata"]["aovs_detected"] == 3
    assert payload["metadata"]["aovs_analyzed"] == 2
    assert payload["metadata"]["summary_by_aov_category"] == {
        "color": 2,
        "depth": 1,
    }
    assert payload["metadata"]["options"]["preset_name"] == "lighting_delivery"
    assert payload["metadata"]["options"]["luminance_weights"] == [0.299, 0.587, 0.114]
    assert set(payload["metrics_by_aov"]) == {"beauty", "diffuse"}
    assert set(payload["channel_metrics_by_aov"]["beauty"]) == {"R", "G", "B"}


def test_cli_analyze_rejects_invalid_custom_weights(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.1001.exr")

    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", str(tmp_path), "--luminance-weights", "0", "0", "0"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "positive sum" in err


def test_cli_analyze_reports_missing_source_without_traceback(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", str(tmp_path / "missing")])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "aovguard analyze: error:" in err
    assert "Traceback" not in err


def test_cli_analyze_loads_rules_config_and_writes_findings(
    tmp_path: Path,
    capsys,
) -> None:
    renders = tmp_path / "renders"
    renders.mkdir()
    _test_exr(renders / "shot.1001.exr")
    rules_path = tmp_path / "rules.toml"
    rules_path.write_text(
        "\n".join(
            [
                'preset = "required_delivery"',
                "[rules.missing_aov]",
                "enabled = true",
                'severity = "error"',
                "[rules.missing_aov.parameters]",
                'required = ["beauty", "emission"]',
                "[rules.empty_aov]",
                "enabled = false",
            ]
        )
    )
    report_path = tmp_path / "report.json"

    main(
        [
            "analyze",
            str(renders),
            "--rules-config",
            str(rules_path),
            "--json",
            str(report_path),
        ]
    )

    out = capsys.readouterr().out
    assert "[error] missing_aov" in out
    payload = json.loads(report_path.read_text())
    assert payload["metadata"]["options"]["preset_name"] == "required_delivery"
    assert payload["metadata"]["options"]["enabled_rules"] == ["missing_aov"]
    assert payload["metadata"]["rules_executed"] == ["missing_aov"]
    assert payload["metadata"]["summary_by_severity"] == {"error": 1}
    assert payload["findings"][0]["rule_id"] == "missing_aov"
    assert payload["findings"][0]["aov"] == "emission"
