from pathlib import Path

import Imath
import numpy as np
import OpenEXR
import pytest
from PySide6.QtWidgets import QApplication

from aovguard.core.models import (
    AOVCategory,
    AOVDescriptor,
    AnalysisOptions,
    AnalysisReport,
    FileInspection,
    Finding,
    MetricSet,
    Severity,
)
from aovguard.ui import (
    AnalyzeWorker,
    MainWindow,
    build_analysis_options,
    format_inspection,
    summarize_aov_categories,
)


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


def _channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(path: Path) -> Path:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(2, 2)
    header["channels"] = {
        name: Imath.Channel(pixel_type)
        for name in ("R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B")
    }
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                "R": _channel(1.0, 2, 2),
                "G": _channel(2.0, 2, 2),
                "B": _channel(3.0, 2, 2),
                "diffuse.R": _channel(4.0, 2, 2),
                "diffuse.G": _channel(5.0, 2, 2),
                "diffuse.B": _channel(6.0, 2, 2),
            }
        )
    finally:
        output.close()
    return path


def _inspection(path: Path) -> FileInspection:
    return FileInspection(
        path=path,
        width=2,
        height=2,
        channels=("R", "G", "B"),
        aovs=(
            AOVDescriptor(
                name="beauty",
                channels=("R", "G", "B"),
                category=AOVCategory.COLOR,
                category_confidence="root_rgb_channels",
            ),
        ),
    )


def test_build_analysis_options_uses_builtin_model_and_rules() -> None:
    options, definitions = build_analysis_options(
        luminance_model="Rec.601",
        rules_config=None,
    )

    assert options.luminance_weights == (0.299, 0.587, 0.114)
    assert options.enabled_rules == (
        "nan_inf",
        "empty_aov",
        "near_empty_aov",
        "resolution_mismatch",
        "aov_structure_mismatch",
    )
    assert {definition.id for definition in definitions}.issuperset(options.enabled_rules)


def test_build_analysis_options_loads_rule_preset(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(
        "\n".join(
            [
                'preset = "gui_preset"',
                "[rules.missing_aov]",
                "enabled = true",
                'severity = "error"',
                "[rules.missing_aov.parameters]",
                'required = ["beauty"]',
            ]
        )
    )

    options, definitions = build_analysis_options(
        luminance_model="Rec.709",
        rules_config=str(path),
    )

    assert options.preset_name == "gui_preset"
    assert options.enabled_rules == ("missing_aov",)
    assert definitions[0].id == "missing_aov"


def test_format_inspection_contains_structure_details() -> None:
    text = format_inspection(_inspection(Path("shot.1001.exr")))

    assert "Size: 2x2" in text
    assert "R" in text
    assert "beauty: color" in text
    assert summarize_aov_categories(_inspection(Path("shot.1001.exr"))) == (
        "1 AOV detected: 1 color."
    )


def test_build_analysis_options_applies_gui_rule_selection() -> None:
    options, definitions = build_analysis_options(
        luminance_model="Rec.709",
        rules_config=None,
        selected_rule_ids={"nan_inf", "negative_values"},
    )

    assert options.enabled_rules == ("nan_inf", "negative_values")
    enabled = {definition.id for definition in definitions if definition.enabled}
    assert enabled == {"nan_inf", "negative_values"}


def test_analyze_worker_runs_common_backend(tmp_path: Path, app) -> None:
    _write_exr(tmp_path / "shot.1001.exr")
    worker = AnalyzeWorker(str(tmp_path))
    payloads: list[object] = []
    errors: list[tuple[str, str]] = []
    progress: list[tuple[int, str]] = []
    worker.finished.connect(payloads.append)
    worker.error.connect(lambda message, details: errors.append((message, details)))
    worker.progress.connect(lambda percent, message: progress.append((percent, message)))

    worker.run()

    assert errors == []
    assert len(payloads) == 1
    report, options = payloads[0]
    assert set(report.metrics_by_aov) == {"beauty", "diffuse"}
    assert options.enabled_rules == (
        "nan_inf",
        "empty_aov",
        "near_empty_aov",
        "resolution_mismatch",
        "aov_structure_mismatch",
    )
    assert progress[-1] == (100, "Analysis complete.")


def test_main_window_uses_automatic_backend_and_displays_results(app) -> None:
    window = MainWindow()
    path = Path("shot.1001.exr")
    report = AnalysisReport(
        source=Path("renders"),
        frames=(path,),
        inspections=(_inspection(path),),
        metrics_by_aov={
            "beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=4),
        },
        findings=(
            Finding(
                rule_id="empty_aov",
                severity=Severity.WARNING,
                message="Test finding",
                file=path,
                aov="beauty",
            ),
        ),
        rules_executed=("empty_aov",),
    )
    options = AnalysisOptions(enabled_rules=("empty_aov",))

    window.on_analysis_finished((report, options))

    assert not hasattr(window, "mode_combo")
    assert window.metrics_table.rowCount() == 1
    assert window.findings_table.rowCount() == 1
    assert window.metrics_table.item(0, 0).text() == "beauty"
    assert window.findings_table.item(0, 1).text() == "empty_aov"
    assert window.tabs.tabText(1) == "Findings (1)"
    assert "1 color" in window.structure_label.text()
    assert window.export_json_btn.isEnabled()
    assert "1 frames" in window.progress_label.text()
    assert window.rule_checkboxes["nan_inf"].isChecked()
    assert not window.rule_checkboxes["negative_values"].isChecked()
    window.close()
