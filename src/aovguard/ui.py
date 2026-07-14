from __future__ import annotations

import sys
import traceback
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, QObject, Signal, Slot, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aovguard.core.analysis import analyze
from aovguard.core.luminance import REC601, REC709
from aovguard.core.models import (
    AOVCategory,
    AnalysisOptions,
    AnalysisReport,
    FileInspection,
    Severity,
)
from aovguard.discovery.frame_discovery import discover_frames
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.json_report import write_analysis_json
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.loader import load_rule_preset
from aovguard.rules.registry import RULES

SEVERITY_COLORS = {
    Severity.ERROR: QColor(255, 225, 225),
    Severity.WARNING: QColor(255, 246, 210),
    Severity.INFO: QColor(225, 240, 255),
}

RULE_LABELS = {
    "nan_inf": "NaN / Inf",
    "empty_aov": "Empty AOV",
    "near_empty_aov": "Near-empty AOV",
    "negative_values": "Negative values",
    "constant_channel": "Constant channels",
    "missing_aov": "Missing AOVs",
    "missing_channels": "Missing channels",
    "resolution_mismatch": "Resolution consistency",
    "aov_structure_mismatch": "AOV consistency",
}


def format_inspection(inspection: FileInspection) -> str:
    lines = [
        f"EXR file: {inspection.path}",
        f"Size: {inspection.width}x{inspection.height}",
        f"Parts: {inspection.part_count}",
        f"Deep: {inspection.is_deep}",
        "",
        "Channels:",
    ]
    lines.extend(f"  - {channel}" for channel in inspection.channels)
    lines.extend(["", "Detected AOVs:"])
    lines.extend(
        f"  - {aov.name}: {aov.category.value} "
        f"({aov.category_confidence}) [{', '.join(aov.channels)}]"
        for aov in inspection.aovs
    )
    if inspection.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"  - {warning}" for warning in inspection.warnings)
    return "\n".join(lines)


def summarize_aov_categories(inspection: FileInspection) -> str:
    counts = {category: 0 for category in AOVCategory}
    for descriptor in inspection.aovs:
        counts[descriptor.category] += 1
    parts = [
        f"{counts[category]} {category.value}"
        for category in AOVCategory
        if counts[category]
    ]
    aov_label = "AOV" if len(inspection.aovs) == 1 else "AOVs"
    return f"{len(inspection.aovs)} {aov_label} detected: {', '.join(parts)}."


def build_analysis_options(
    *,
    luminance_model: str,
    rules_config: str | None,
    selected_rule_ids: set[str] | None = None,
) -> tuple[AnalysisOptions, tuple]:
    weights = REC601 if luminance_model == "Rec.601" else REC709
    if rules_config:
        preset = load_rule_preset(rules_config)
        definitions = preset.rules
        preset_name = preset.name
    else:
        definitions = default_rule_definitions()
        preset_name = None
    if selected_rule_ids is not None:
        definitions = tuple(
            replace(definition, enabled=definition.id in selected_rule_ids)
            for definition in definitions
        )

    enabled_rules = tuple(definition.id for definition in definitions if definition.enabled)
    options = AnalysisOptions(
        preset_name=preset_name,
        enabled_rules=enabled_rules,
        luminance_weights=(weights.r, weights.g, weights.b),
    )
    return options, tuple(definitions)


class AnalyzeWorker(QObject):
    finished = Signal(object)
    error = Signal(str, str)
    log = Signal(str)
    progress = Signal(int, str)

    def __init__(
        self,
        source: str,
        *,
        rules_config: str | None = None,
        luminance_model: str = "Rec.709",
        selected_rule_ids: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.rules_config = rules_config
        self.luminance_model = luminance_model
        self.selected_rule_ids = selected_rule_ids

    def _on_progress(self, current: int, total: int, message: str) -> None:
        percent = int((current / total) * 100) if total > 0 else 0
        self.progress.emit(max(0, min(100, percent)), message)

    @Slot()
    def run(self) -> None:
        try:
            self.log.emit(f"Analyzing source: {self.source}")
            self.progress.emit(0, "Preparing analysis...")
            options, definitions = build_analysis_options(
                luminance_model=self.luminance_model,
                rules_config=self.rules_config,
                selected_rule_ids=self.selected_rule_ids,
            )
            report = analyze(
                self.source,
                options,
                OpenEXRReader(),
                rule_definitions=definitions,
                progress_callback=self._on_progress,
            )
            self.progress.emit(100, "Analysis complete.")
            self.finished.emit((report, options))
        except Exception as exc:
            self.error.emit(str(exc), traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AOVGuard")
        self.resize(1100, 720)
        self.setStyleSheet('QWidget { font-family: "Segoe UI"; font-size: 10pt; }')

        self.report: AnalysisReport | None = None
        self.options: AnalysisOptions | None = None
        self.thread: QThread | None = None
        self.worker: AnalyzeWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        source_row = QHBoxLayout()
        layout.addLayout(source_row)
        source_row.addWidget(QLabel("EXR Source:"))
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Select an EXR file or render folder...")
        source_row.addWidget(self.source_edit, 1)
        self.browse_file_btn = QPushButton("File")
        self.browse_file_btn.clicked.connect(self.browse_file)
        source_row.addWidget(self.browse_file_btn)
        self.browse_folder_btn = QPushButton("Folder")
        self.browse_folder_btn.clicked.connect(self.browse_folder)
        source_row.addWidget(self.browse_folder_btn)

        config_row = QHBoxLayout()
        layout.addLayout(config_row)
        config_row.addWidget(QLabel("Rule Preset:"))
        self.rules_edit = QLineEdit()
        self.rules_edit.setPlaceholderText("Default rules")
        config_row.addWidget(self.rules_edit, 1)
        self.browse_rules_btn = QPushButton("Browse")
        self.browse_rules_btn.clicked.connect(self.browse_rules)
        config_row.addWidget(self.browse_rules_btn)
        config_row.addWidget(QLabel("Luminance:"))
        self.luminance_combo = QComboBox()
        self.luminance_combo.addItems(["Rec.709", "Rec.601"])
        config_row.addWidget(self.luminance_combo)

        rules_group = QGroupBox("Validation Rules")
        rules_layout = QGridLayout(rules_group)
        default_states = {
            definition.id: definition.enabled
            for definition in default_rule_definitions()
        }
        self.rule_checkboxes: dict[str, QCheckBox] = {}
        for index, rule_id in enumerate(RULES):
            checkbox = QCheckBox(RULE_LABELS.get(rule_id, rule_id))
            checkbox.setChecked(default_states.get(rule_id, False))
            self.rule_checkboxes[rule_id] = checkbox
            rules_layout.addWidget(checkbox, index // 5, index % 5)
        layout.addWidget(rules_group)

        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.inspect_btn = QPushButton("Inspect Structure")
        self.inspect_btn.clicked.connect(self.inspect_source)
        actions.addWidget(self.inspect_btn)
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.clicked.connect(self.start_analysis)
        actions.addWidget(self.analyze_btn)
        self.export_json_btn = QPushButton("Export JSON")
        self.export_json_btn.clicked.connect(self.export_json)
        self.export_json_btn.setEnabled(False)
        actions.addWidget(self.export_json_btn)

        self.structure_label = QLabel("Structure not inspected.")
        layout.addWidget(self.structure_label)

        self.progress_label = QLabel("Ready.")
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.metrics_table = QTableWidget(0, 6)
        self.metrics_table.setHorizontalHeaderLabels(
            [
                "AOV",
                "Category",
                "Non-black Ratio",
                "Average Luminance",
                "Max Luminance",
                "Channels",
            ]
        )
        header = self.metrics_table.horizontalHeader()
        for column in (0, 1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.metrics_table.setSortingEnabled(True)
        self.metrics_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.metrics_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabs.addTab(self.metrics_table, "Metrics")

        self.findings_table = QTableWidget(0, 6)
        self.findings_table.setHorizontalHeaderLabels(
            ["Severity", "Rule", "AOV", "Channel", "Message", "File"]
        )
        findings_header = self.findings_table.horizontalHeader()
        for column in (0, 1, 2, 3):
            findings_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        findings_header.setSectionResizeMode(4, QHeaderView.Stretch)
        findings_header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.findings_table.setColumnWidth(5, 240)
        self.findings_table.setSortingEnabled(True)
        self.findings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.findings_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabs.addTab(self.findings_table, "Findings (0)")

        # Temporary compatibility alias for external code written against the
        # original single-table GUI.
        self.table = self.metrics_table

        layout.addWidget(QLabel("Log"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.analyze_btn,
            self.browse_file_btn,
            self.browse_folder_btn,
            self.browse_rules_btn,
            self.inspect_btn,
            self.source_edit,
            self.rules_edit,
            self.luminance_combo,
            *self.rule_checkboxes.values(),
        ):
            widget.setEnabled(not busy)
        self.export_json_btn.setEnabled((not busy) and self.report is not None)

    def browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select EXR File", "", "EXR Files (*.exr)")
        if path:
            self.source_edit.setText(path)

    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select EXR Folder")
        if folder:
            self.source_edit.setText(folder)

    def browse_rules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Rule Preset",
            "",
            "Rule Presets (*.toml *.json)",
        )
        if path:
            self.rules_edit.setText(path)
            try:
                preset = load_rule_preset(path)
            except Exception as exc:
                QMessageBox.warning(self, "AOVGuard", f"Could not load rule preset: {exc}")
                return
            enabled = {
                definition.id
                for definition in preset.rules
                if definition.enabled
            }
            for rule_id, checkbox in self.rule_checkboxes.items():
                checkbox.setChecked(rule_id in enabled)

    def _source(self) -> Path | None:
        value = self.source_edit.text().strip()
        if not value:
            QMessageBox.warning(self, "AOVGuard", "Please choose an EXR file or folder first.")
            return None
        source = Path(value)
        if not source.exists():
            QMessageBox.warning(self, "AOVGuard", "The selected source does not exist.")
            return None
        return source

    def inspect_source(self) -> None:
        source = self._source()
        if source is None:
            return
        try:
            discovery = discover_frames(source)
            if not discovery.frames:
                raise FileNotFoundError(f"No EXR files found in {source}")
            inspection = OpenEXRReader().inspect(discovery.frames[0])
        except Exception as exc:
            QMessageBox.critical(self, "Inspect Error", str(exc))
            return

        self.structure_label.setText(
            f"{len(inspection.channels)} channels. {summarize_aov_categories(inspection)}"
        )
        box = QMessageBox(self)
        box.setWindowTitle("EXR Structure")
        box.setText("Automatic EXR structure inspection completed.")
        box.setDetailedText(format_inspection(inspection))
        box.exec()

    def start_analysis(self) -> None:
        source = self._source()
        if source is None:
            return

        rules_config = self.rules_edit.text().strip() or None
        if rules_config and not Path(rules_config).is_file():
            QMessageBox.warning(self, "AOVGuard", "The selected rule preset does not exist.")
            return

        self.report = None
        self.options = None
        self.metrics_table.setSortingEnabled(False)
        self.metrics_table.setRowCount(0)
        self.findings_table.setSortingEnabled(False)
        self.findings_table.setRowCount(0)
        self.tabs.setTabText(1, "Findings (0)")
        self.export_json_btn.setEnabled(False)
        self.set_busy(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting analysis...")
        self.append_log("Starting automatic EXR analysis...")

        self.thread = QThread(self)
        self.worker = AnalyzeWorker(
            str(source),
            rules_config=rules_config,
            luminance_model=self.luminance_combo.currentText(),
            selected_rule_ids={
                rule_id
                for rule_id, checkbox in self.rule_checkboxes.items()
                if checkbox.isChecked()
            },
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.on_progress)

        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def _add_row(
        self,
        table: QTableWidget,
        values: list[str],
        *,
        numeric_columns: tuple[int, ...] = (),
        color: QColor | None = None,
    ) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column in numeric_columns:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if color is not None:
                item.setBackground(color)
            table.setItem(row, column, item)

    def on_analysis_finished(self, payload: object) -> None:
        report, options = payload
        self.report = report
        self.options = options
        self.metrics_table.setSortingEnabled(False)
        self.metrics_table.setRowCount(0)
        self.findings_table.setSortingEnabled(False)
        self.findings_table.setRowCount(0)

        categories = {}
        channels = {}
        if report.inspections:
            for descriptor in report.inspections[0].aovs:
                categories[descriptor.name] = descriptor.category.value
                channels[descriptor.name] = ", ".join(descriptor.channels)

        for aov_name, metrics in report.metrics_by_aov.items():
            self._add_row(
                self.metrics_table,
                [
                    aov_name,
                    categories.get(aov_name, "unknown"),
                    f"{metrics.non_black_ratio:.5f}",
                    f"{metrics.avg_luminance:.6f}",
                    f"{metrics.max_luminance:.6f}",
                    channels.get(aov_name, ""),
                ],
                numeric_columns=(2, 3, 4),
                color=SEVERITY_COLORS[Severity.INFO],
            )

        for finding in report.findings:
            self._add_row(
                self.findings_table,
                [
                    finding.severity.value,
                    finding.rule_id,
                    finding.aov or "",
                    finding.channel or "",
                    finding.message,
                    str(finding.file or report.source),
                ],
                color=SEVERITY_COLORS.get(finding.severity),
            )

        self.metrics_table.setSortingEnabled(True)
        self.findings_table.setSortingEnabled(True)
        self.tabs.setTabText(1, f"Findings ({len(report.findings)})")
        self.set_busy(False)
        self.export_json_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        finding_label = "finding" if len(report.findings) == 1 else "findings"
        self.progress_label.setText(
            f"Analysis complete. {report.frame_count} frames, "
            f"{len(report.metrics_by_aov)} AOVs, {len(report.findings)} {finding_label}."
        )
        self.append_log(self.progress_label.text())
        if report.inspections:
            first = report.inspections[0]
            self.structure_label.setText(
                f"{len(first.channels)} channels. {summarize_aov_categories(first)}"
            )
        for warning in report.warnings:
            self.append_log(f"Warning: {warning}")

    def on_analysis_error(self, message: str, details: str) -> None:
        self.set_busy(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Analysis failed.")
        self.append_log("Analysis failed.")
        self.append_log(details)
        QMessageBox.critical(self, "Analysis Error", message)

    def export_json(self) -> None:
        if self.report is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            "aovguard_report.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        write_analysis_json(self.report, path, options=self.options)
        self.append_log(f"JSON report written to: {path}")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
    QGridLayout,
    QGroupBox,
