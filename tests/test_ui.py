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
    SequenceCheckResult,
    SequenceDescriptor,
    Severity,
)
from aovguard.ui import (
    AnalyzeWorker,
    MainWindow,
    build_analysis_options,
    format_inspection,
    summarize_analysis_scope,
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


def test_format_inspection_includes_reader_warnings() -> None:
    inspection = FileInspection(
        path=Path("unsupported.exr"),
        width=2,
        height=2,
        channels=("R", "G", "B"),
        aovs=(),
        warnings=("Multipart data is only partially supported.",),
    )

    text = format_inspection(inspection)

    assert "Warnings:" in text
    assert "Multipart data is only partially supported." in text
    assert summarize_aov_categories(inspection) == "0 AOVs detected."


def test_summarize_analysis_scope_explains_excluded_technical_passes() -> None:
    inspection = FileInspection(
        path=Path("technical.exr"),
        width=2,
        height=2,
        channels=("R", "G", "B", "N.X", "N.Y", "N.Z", "Z"),
        aovs=(
            AOVDescriptor(
                name="beauty",
                channels=("R", "G", "B"),
                category=AOVCategory.COLOR,
            ),
            AOVDescriptor(
                name="N",
                channels=("N.X", "N.Y", "N.Z"),
                category=AOVCategory.VECTOR,
            ),
            AOVDescriptor(
                name="Z",
                channels=("Z",),
                category=AOVCategory.DEPTH,
            ),
        ),
    )

    summary = summarize_analysis_scope(inspection, {"beauty"})

    assert "3 AOVs detected: 1 color, 1 vector, 1 depth" in summary
    assert "1 color AOV analyzed" in summary
    assert "2 technical passes excluded from luminance (1 vector, 1 depth)" in summary


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


def test_analyze_worker_reports_backend_errors(tmp_path: Path, app) -> None:
    worker = AnalyzeWorker(str(tmp_path))
    errors: list[tuple[str, str]] = []
    worker.error.connect(lambda message, details: errors.append((message, details)))

    worker.run()

    assert len(errors) == 1
    assert "No EXR files" in errors[0][0]
    assert "Traceback" in errors[0][1]


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
    assert "1 color AOV analyzed" in window.structure_label.text()
    assert window.export_json_btn.isEnabled()
    assert "1/1 frames processed" in window.progress_label.text()
    assert "1 color AOV analyzed" in window.progress_label.text()
    assert window.rule_checkboxes["nan_inf"].isChecked()
    assert not window.rule_checkboxes["negative_values"].isChecked()
    window.close()


def test_main_window_browse_actions_and_rule_preset(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.1001.exr"
    source.touch()
    preset = tmp_path / "rules.toml"
    preset.write_text(
        "\n".join(
            [
                'preset = "gui_selected"',
                "[rules.negative_values]",
                "enabled = true",
                'severity = "warning"',
            ]
        ),
        encoding="utf-8",
    )
    window = MainWindow()

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *args: (str(source), "EXR Files (*.exr)"),
    )
    window.browse_file()
    assert window.source_edit.text() == str(source)

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getExistingDirectory",
        lambda *args: str(tmp_path),
    )
    window.browse_folder()
    assert window.source_edit.text() == str(tmp_path)

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *args: (str(preset), "Rule Presets (*.toml *.json)"),
    )
    window.browse_rules()
    assert window.rules_edit.text() == str(preset)
    assert window.rule_checkboxes["negative_values"].isChecked()
    assert not window.rule_checkboxes["nan_inf"].isChecked()
    window.close()


def test_main_window_rejects_invalid_preset(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = tmp_path / "invalid.toml"
    preset.write_text("not valid = [", encoding="utf-8")
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *args: (str(preset), "Rule Presets (*.toml *.json)"),
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()

    window.browse_rules()

    assert warnings and "Could not load rule preset" in warnings[0]
    window.close()


def test_main_window_validates_source(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()

    assert window._source() is None
    window.source_edit.setText(str(tmp_path / "missing.exr"))
    assert window._source() is None
    window.source_edit.setText(str(tmp_path))
    assert window._source() == tmp_path

    assert warnings == [
        "Please choose an EXR file or folder first.",
        "The selected source does not exist.",
    ]
    window.close()


def test_main_window_inspects_exr_and_reports_inspection_errors(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_exr(tmp_path / "shot.1001.exr")
    monkeypatch.setattr("aovguard.ui.QMessageBox.exec", lambda _self: 0)
    critical: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: critical.append(message),
    )
    window = MainWindow()
    window.source_edit.setText(str(source))

    window.inspect_source()

    assert "6 channels" in window.structure_label.text()
    assert "2 AOVs detected" in window.structure_label.text()

    empty = tmp_path / "empty"
    empty.mkdir()
    window.source_edit.setText(str(empty))
    window.inspect_source()
    assert critical and "No EXR files found" in critical[0]
    window.close()


class _SignalStub:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)


class _ThreadStub:
    def __init__(self, *_args: object) -> None:
        self.started = _SignalStub()
        self.finished = _SignalStub()
        self.was_started = False

    def start(self) -> None:
        self.was_started = True

    def quit(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


def test_main_window_starts_worker_with_selected_options(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.1001.exr"
    source.touch()
    monkeypatch.setattr("aovguard.ui.QThread", _ThreadStub)
    monkeypatch.setattr(
        "aovguard.ui.AnalyzeWorker.moveToThread",
        lambda _worker, _thread: None,
    )
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.rule_checkboxes["nan_inf"].setChecked(True)
    window.rule_checkboxes["empty_aov"].setChecked(False)

    window.start_analysis()

    assert isinstance(window.thread, _ThreadStub)
    assert window.thread.was_started
    assert window.worker is not None
    assert "nan_inf" in window.worker.selected_rule_ids
    assert "empty_aov" not in window.worker.selected_rule_ids
    assert not window.analyze_btn.isEnabled()
    assert window.progress_label.text() == "Starting analysis..."
    assert "Starting automatic EXR analysis" in window.log_output.toPlainText()
    window.close()


def test_main_window_rejects_missing_rule_preset_before_starting(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.1001.exr"
    source.touch()
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.rules_edit.setText(str(tmp_path / "missing.toml"))

    window.start_analysis()

    assert window.thread is None
    assert warnings == ["The selected rule preset does not exist."]
    window.close()


def test_main_window_progress_error_and_json_export(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: errors.append(message),
    )
    window = MainWindow()

    window.on_progress(45, "Reading frame 2 of 4")
    assert window.progress_bar.value() == 45
    assert window.progress_label.text() == "Reading frame 2 of 4"

    window.set_busy(True)
    window.on_analysis_error("Broken EXR", "reader traceback")
    assert window.analyze_btn.isEnabled()
    assert window.progress_bar.value() == 0
    assert window.progress_label.text() == "Analysis failed."
    assert "reader traceback" in window.log_output.toPlainText()
    assert errors == ["Broken EXR"]

    window.export_json()
    report = AnalysisReport(
        source=tmp_path,
        frames=(),
        inspections=(),
        metrics_by_aov={"unknown": MetricSet(0.0, 0.0, 0.0, pixel_count=0)},
        warnings=("No frames were processed.",),
    )
    window.on_analysis_finished((report, AnalysisOptions()))
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *args: (str(output), "JSON Files (*.json)"),
    )

    window.export_json()

    assert output.is_file()
    assert '"schema_version": "1.0"' in output.read_text(encoding="utf-8")
    assert "Warning: No frames were processed." in window.log_output.toPlainText()
    assert window.metrics_table.item(0, 1).text() == "unknown"
    assert window.progress_label.text().endswith("0 findings.")
    window.close()


def test_main_window_filters_findings_shows_details_and_sequences(
    tmp_path: Path,
    app,
) -> None:
    frame_a = tmp_path / "shot.1001.exr"
    frame_b = tmp_path / "shot.1003.exr"
    sequence = SequenceDescriptor(
        directory=tmp_path,
        prefix="shot.",
        suffix="",
        padding=4,
        frame_numbers=(1001, 1003),
        files=(frame_a, frame_b),
        missing_ranges=((1002, 1002),),
        padding_widths=(4,),
    )
    report = AnalysisReport(
        source=tmp_path,
        frames=(frame_a, frame_b),
        successful_frames=(frame_a,),
        failed_frames=(frame_b,),
        inspections=(),
        metrics_by_aov={},
        findings=(
            Finding(
                rule_id="read_frame",
                severity=Severity.ERROR,
                message="Could not read frame.",
                file=frame_b,
            ),
            Finding(
                rule_id="sequence_gap",
                severity=Severity.WARNING,
                message="Missing frame 1002.",
                file=tmp_path,
                metrics={"missing_frame": 1002},
            ),
            Finding(
                rule_id="constant_channel",
                severity=Severity.INFO,
                message="Channel is constant.",
                file=frame_a,
                aov="beauty",
                channel="R",
            ),
        ),
        sequence_check=SequenceCheckResult(source=tmp_path, sequences=(sequence,)),
    )
    window = MainWindow()

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.findings_table.rowCount() == 3
    assert window.findings_table.item(0, 0).text() == "error"
    assert window.findings_table.item(1, 0).text() == "warning"
    assert window.findings_table.item(2, 0).text() == "info"
    assert window.sequence_table.rowCount() == 1
    assert window.sequence_table.item(0, 0).text() == "shot.####.exr"
    assert window.sequence_table.item(0, 4).text() == "1002"

    window.severity_filter.setCurrentIndex(window.severity_filter.findData("warning"))
    assert window.findings_table.rowCount() == 1
    assert window.findings_table.item(0, 1).text() == "sequence_gap"

    window.severity_filter.setCurrentIndex(0)
    window.finding_search.setText("beauty")
    assert window.findings_table.rowCount() == 1
    assert window.findings_table.item(0, 1).text() == "constant_channel"

    window.finding_search.clear()
    window.failed_only_checkbox.setChecked(True)
    assert window.findings_table.rowCount() == 1
    assert window.findings_table.item(0, 1).text() == "read_frame"
    window.findings_table.setCurrentCell(0, 0)
    app.processEvents()
    assert "Could not read frame" in window.finding_details.toPlainText()
    assert "Verify that the file exists" in window.finding_details.toPlainText()
    assert window.copy_path_btn.isEnabled()
    window.copy_finding_path()
    assert QApplication.clipboard().text() == str(frame_b)
    window.close()


def test_main_window_exports_html(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    window.report = AnalysisReport(
        source=tmp_path,
        frames=(),
        inspections=(),
        metrics_by_aov={},
    )
    output = tmp_path / "report.html"
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *args: (str(output), "HTML Files (*.html)"),
    )

    window.export_html()

    assert output.is_file()
    assert "AOVGuard Analysis Report" in output.read_text(encoding="utf-8")
    assert "HTML report written" in window.log_output.toPlainText()
    window.close()


def test_main_window_multiple_metrics_do_not_leave_controls_disabled(app) -> None:
    window = MainWindow()
    window.set_busy(True)
    report = AnalysisReport(
        source=Path("renders"),
        frames=(Path("shot.1001.exr"),),
        inspections=(),
        metrics_by_aov={
            name: MetricSet(1.0, float(index), float(index), pixel_count=4)
            for index, name in enumerate(
                ("albedo", "beauty", "diffuse", "emission", "specular"),
                start=1,
            )
        },
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.metrics_table.rowCount() == 5
    assert window.source_edit.isEnabled()
    assert window.analyze_btn.isEnabled()
    assert window.export_json_btn.isEnabled()
    assert window.export_html_btn.isEnabled()
    assert "5 color AOVs analyzed" in window.progress_label.text()
    window.close()


def test_main_window_recovers_when_result_display_fails(
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: errors.append(message),
    )
    window = MainWindow()
    window.set_busy(True)

    def fail_display(_report: AnalysisReport) -> None:
        raise RuntimeError("table rendering failed")

    monkeypatch.setattr(window, "_display_analysis_results", fail_display)
    report = AnalysisReport(
        source=Path("renders"),
        frames=(),
        inspections=(),
        metrics_by_aov={},
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.source_edit.isEnabled()
    assert window.analyze_btn.isEnabled()
    assert window.export_json_btn.isEnabled()
    assert window.export_html_btn.isEnabled()
    assert window.progress_label.text() == (
        "Analysis completed, but results could not be displayed."
    )
    assert "table rendering failed" in window.log_output.toPlainText()
    assert errors == ["table rendering failed"]
    window.close()
