from __future__ import annotations

import sys
import traceback
from collections.abc import Collection
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QUrl, Qt
from PySide6.QtGui import QAction, QColor, QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aovguard.core.findings import finding_recommendation
from aovguard.core.luminance import REC709
from aovguard.core.models import (
    AOVCategory,
    AnalysisOptions,
    AnalysisReport,
    FileInspection,
    Finding,
    Severity,
    SourceKind,
    SourceMode,
)
from aovguard.core.status import analysis_status, severity_counts
from aovguard.discovery.frame_discovery import discover_frames
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.json_report import write_analysis_json
from aovguard.reports.json_report import build_analysis_report_payload
from aovguard.reports.html_report import write_analysis_html
from aovguard.reports.comparison import (
    compare_report_payloads,
    load_report_payload,
)
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.loader import load_rule_preset
from aovguard.rules.registry import RULES
from aovguard.sequence.sequence_checker import format_frame_ranges
from aovguard.ui_components import CollapsibleSection, EmptyStateTable
from aovguard.gui.presentation import (
    display_path,
    finding_source_label,
    format_percentage_change,
)
from aovguard.gui.help_text import (
    LUMINANCE_MODEL_TOOLTIPS,
    SEVERITY_TOOLTIPS,
    STATUS_TOOLTIPS,
    TABLE_HEADER_TOOLTIPS,
    TABLE_VIEW_TOOLTIPS,
    TAB_TOOLTIPS,
    aov_tooltip,
    category_tooltip,
)
from aovguard.gui.worker import AnalyzeWorker, build_analysis_options

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

RULE_TOOLTIPS = {
    "nan_inf": "Detect NaN and positive or negative infinity values.",
    "empty_aov": "Report color AOVs with no visible contribution.",
    "near_empty_aov": "Report color AOVs whose visible contribution is below the preset threshold.",
    "negative_values": "Report negative values in supported color AOVs.",
    "constant_channel": "Report supported channels that contain one constant value.",
    "missing_aov": "Check required AOV names defined by the selected preset.",
    "missing_channels": "Check required channels defined by the selected preset.",
    "resolution_mismatch": "Check that every decoded frame has the same resolution.",
    "aov_structure_mismatch": "Check that AOV and channel structure remains consistent between frames.",
}

TAB_FINDINGS = 0
TAB_METRICS = 1
TAB_FRAMES = 2
TAB_TECHNICAL = 3
TAB_SEQUENCES = 4
TAB_COMPARISON = 5
FULL_PATH_ROLE = int(Qt.UserRole) + 1


def _help_label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setToolTip(tooltip)
    return label


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key: object | None = None) -> None:
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.sort_key
        right = getattr(other, "sort_key", None)
        if left is not None and right is not None:
            return left < right
        return self.text().casefold() < other.text().casefold()


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
    category_summary = f": {', '.join(parts)}" if parts else ""
    return f"{len(inspection.aovs)} {aov_label} detected{category_summary}."


def summarize_analysis_scope(
    inspection: FileInspection,
    analyzed_aovs: Collection[str],
    diagnosed_aovs: Collection[str] = (),
) -> str:
    analyzed_names = set(analyzed_aovs)
    diagnosed_names = set(diagnosed_aovs)
    analyzed_descriptors = [
        descriptor for descriptor in inspection.aovs if descriptor.name in analyzed_names
    ]
    excluded_descriptors = [
        descriptor for descriptor in inspection.aovs if descriptor.name not in analyzed_names
    ]

    analyzed_count = len(analyzed_names)
    all_analyzed_are_color = (
        analyzed_count > 0
        and len(analyzed_descriptors) == analyzed_count
        and all(
            descriptor.category is AOVCategory.COLOR
            for descriptor in analyzed_descriptors
        )
    )
    analyzed_kind = "color AOV" if all_analyzed_are_color else "AOV"
    analyzed_label = analyzed_kind if analyzed_count == 1 else f"{analyzed_kind}s"
    message = (
        f"{summarize_aov_categories(inspection)} "
        f"Luminance scope: {analyzed_count} {analyzed_label} analyzed"
    )

    if excluded_descriptors:
        counts = {category: 0 for category in AOVCategory}
        for descriptor in excluded_descriptors:
            counts[descriptor.category] += 1
        breakdown = ", ".join(
            f"{counts[category]} {category.value}"
            for category in AOVCategory
            if counts[category]
        )
        excluded_count = len(excluded_descriptors)
        all_excluded_are_technical = all(
            descriptor.category is not AOVCategory.COLOR
            for descriptor in excluded_descriptors
        )
        if all_excluded_are_technical:
            excluded_label = (
                "technical pass" if excluded_count == 1 else "technical passes"
            )
        else:
            excluded_label = "AOV" if excluded_count == 1 else "AOVs"
        message += (
            f"; {excluded_count} {excluded_label} excluded from luminance "
            f"({breakdown})"
        )
        diagnosed_count = len(
            {descriptor.name for descriptor in excluded_descriptors}
            & diagnosed_names
        )
        if diagnosed_count:
            diagnosed_label = (
                "technical AOV" if diagnosed_count == 1 else "technical AOVs"
            )
            message += f"; {diagnosed_count} {diagnosed_label} diagnosed per channel"

    return f"{message}."


class MainWindow(QMainWindow):
    def __init__(self, *, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or QSettings()
        self.setWindowTitle("AOVGuard")
        self.resize(1180, 760)
        self.setStyleSheet(
            'QWidget { font-family: "Segoe UI"; font-size: 10pt; } '
            "QTableWidget::item:selected { background: #1469a8; color: white; } "
            "QToolTip { background: #fffde8; color: #20262d; "
            "border: 1px solid #8a929a; padding: 6px; }"
        )

        self.report: AnalysisReport | None = None
        self.options: AnalysisOptions | None = None
        self.thread: QThread | None = None
        self.worker: AnalyzeWorker | None = None
        self.selected_finding: Finding | None = None
        self._table_default_widths: dict[QTableWidget, tuple[int, ...]] = {}

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        source_row = QHBoxLayout()
        layout.addLayout(source_row)
        self.source_label = _help_label(
            "EXR Source:",
            "EXR file or folder to inspect. A folder can represent a numbered "
            "sequence or a set of independent EXR samples.",
        )
        source_row.addWidget(self.source_label)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Select an EXR file or render folder...")
        self.source_edit.setToolTip(
            "Path to the real EXR file or folder that AOVGuard will analyze."
        )
        source_row.addWidget(self.source_edit, 1)
        self.browse_file_btn = QPushButton("File")
        self.browse_file_btn.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        self.browse_file_btn.setToolTip("Select one EXR file")
        self.browse_file_btn.clicked.connect(self.browse_file)
        source_row.addWidget(self.browse_file_btn)
        self.browse_folder_btn = QPushButton("Folder")
        self.browse_folder_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.browse_folder_btn.setToolTip("Select a render folder")
        self.browse_folder_btn.clicked.connect(self.browse_folder)
        source_row.addWidget(self.browse_folder_btn)

        config_row = QHBoxLayout()
        layout.addLayout(config_row)
        self.rules_label = _help_label(
            "Rule Preset:",
            "Optional TOML or JSON file defining enabled rules, severities and parameters.",
        )
        config_row.addWidget(self.rules_label)
        self.rules_edit = QLineEdit()
        self.rules_edit.setPlaceholderText("Default rules")
        self.rules_edit.setToolTip(
            "Leave empty to use AOVGuard defaults, or enter a TOML/JSON preset path."
        )
        config_row.addWidget(self.rules_edit, 1)
        self.browse_rules_btn = QPushButton("Browse")
        self.browse_rules_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.browse_rules_btn.setToolTip("Load a TOML or JSON validation preset")
        self.browse_rules_btn.clicked.connect(self.browse_rules)
        config_row.addWidget(self.browse_rules_btn)
        self.luminance_label = _help_label(
            "Luminance:",
            "RGB weighting formula used to convert color AOV pixels into luminance values.",
        )
        config_row.addWidget(self.luminance_label)
        self.luminance_combo = QComboBox()
        self.luminance_combo.addItems(["Rec.709", "Rec.601", "Custom"])
        self.luminance_combo.setToolTip(LUMINANCE_MODEL_TOOLTIPS["Rec.709"])
        self.luminance_combo.currentTextChanged.connect(
            self._update_custom_weights_visibility
        )
        config_row.addWidget(self.luminance_combo)

        self.custom_weights_widget = QWidget()
        custom_weights_layout = QHBoxLayout(self.custom_weights_widget)
        custom_weights_layout.setContentsMargins(0, 0, 0, 0)
        custom_weights_layout.setSpacing(4)
        self.custom_weight_spins: list[QDoubleSpinBox] = []
        for label, value in zip(("R", "G", "B"), (REC709.r, REC709.g, REC709.b)):
            weight_label = _help_label(
                label,
                f"Custom contribution assigned to the {label} color channel.",
            )
            custom_weights_layout.addWidget(weight_label)
            spin = QDoubleSpinBox()
            spin.setRange(-10.0, 10.0)
            spin.setDecimals(4)
            spin.setSingleStep(0.01)
            spin.setValue(value)
            spin.setFixedWidth(76)
            spin.setToolTip(
                f"Custom {label} luminance weight. The three weights are validated together."
            )
            self.custom_weight_spins.append(spin)
            custom_weights_layout.addWidget(spin)
        self.custom_weights_widget.setVisible(False)
        config_row.addWidget(self.custom_weights_widget)

        self.analysis_settings_section = CollapsibleSection(
            "Analysis Settings", expanded=False
        )
        self.analysis_settings_section.toggle_button.setToolTip(
            "Show or hide source interpretation and file-discovery options."
        )
        source_mode_row = QHBoxLayout()
        self.source_mode_label = _help_label(
            "Interpret Source As:",
            "Controls whether discovered EXRs are treated automatically, as a numbered "
            "sequence or as independent comparison samples.",
        )
        source_mode_row.addWidget(self.source_mode_label)
        self.source_mode_group = QButtonGroup(self)
        self.source_mode_group.setExclusive(True)
        self.source_mode_buttons: dict[SourceMode, QToolButton] = {}
        for mode, label, tooltip in (
            (
                SourceMode.AUTO,
                "Auto",
                "Infer a single file, numbered sequence or comparison set.",
            ),
            (
                SourceMode.SEQUENCE,
                "Sequence",
                "Require numbered EXR frames and enable sequence checks.",
            ),
            (
                SourceMode.COMPARISON,
                "Comparison",
                "Treat every discovered EXR as an independent comparison sample.",
            ),
        ):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setMinimumWidth(96)
            self.source_mode_group.addButton(button)
            self.source_mode_buttons[mode] = button
            source_mode_row.addWidget(button)
        self.source_mode_buttons[SourceMode.AUTO].setChecked(True)
        source_mode_row.addStretch(1)
        self.analysis_settings_section.content_layout.addLayout(source_mode_row)
        discovery_row = QHBoxLayout()
        self.frame_pattern_label = _help_label(
            "Frame Pattern:",
            "Filename wildcard used to discover EXRs, for example *.exr or shot.*.exr.",
        )
        discovery_row.addWidget(self.frame_pattern_label)
        self.frame_pattern_edit = QLineEdit("*.exr")
        self.frame_pattern_edit.setPlaceholderText("*.exr")
        self.frame_pattern_edit.setToolTip("Filename pattern used to discover EXR frames")
        discovery_row.addWidget(self.frame_pattern_edit, 1)
        self.recursive_checkbox = QCheckBox("Recursive")
        self.recursive_checkbox.setToolTip("Include matching EXRs in nested folders")
        discovery_row.addWidget(self.recursive_checkbox)
        self.max_depth_label = _help_label(
            "Max Depth:",
            "Maximum number of nested directory levels searched when Recursive is enabled.",
        )
        discovery_row.addWidget(self.max_depth_label)
        self.max_depth_spin = QSpinBox()
        self.max_depth_spin.setRange(0, 20)
        self.max_depth_spin.setValue(1)
        self.max_depth_spin.setEnabled(False)
        self.max_depth_spin.setToolTip("Maximum nested folder depth to inspect")
        self.recursive_checkbox.toggled.connect(self.max_depth_spin.setEnabled)
        discovery_row.addWidget(self.max_depth_spin)
        self.allow_multiple_sequences_checkbox = QCheckBox("Allow Multiple Sequences")
        self.allow_multiple_sequences_checkbox.setToolTip(
            "Analyze more than one numbered sequence in the selected source"
        )
        discovery_row.addWidget(self.allow_multiple_sequences_checkbox)
        self.analysis_settings_section.content_layout.addLayout(discovery_row)
        layout.addWidget(self.analysis_settings_section)

        self.rules_section = CollapsibleSection("Validation Rules", expanded=True)
        self.rules_section.toggle_button.setToolTip(
            "Show or hide the validation checks that will run during analysis."
        )
        rule_actions = QHBoxLayout()
        self.select_all_rules_btn = QPushButton("Select All")
        self.select_all_rules_btn.setToolTip("Enable every available validation rule.")
        self.select_all_rules_btn.clicked.connect(self.select_all_rules)
        rule_actions.addWidget(self.select_all_rules_btn)
        self.clear_rules_btn = QPushButton("Clear")
        self.clear_rules_btn.setToolTip("Disable every validation rule.")
        self.clear_rules_btn.clicked.connect(self.clear_rules)
        rule_actions.addWidget(self.clear_rules_btn)
        self.restore_rules_btn = QPushButton("Restore Preset")
        self.restore_rules_btn.setToolTip(
            "Restore enabled rules from the selected preset or built-in defaults."
        )
        self.restore_rules_btn.clicked.connect(self.restore_rule_selection)
        rule_actions.addWidget(self.restore_rules_btn)
        rule_actions.addStretch(1)
        self.rules_section.content_layout.addLayout(rule_actions)

        rules_widget = QWidget()
        rules_layout = QGridLayout(rules_widget)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        default_states = {
            definition.id: definition.enabled
            for definition in default_rule_definitions()
        }
        self.rule_checkboxes: dict[str, QCheckBox] = {}
        for index, rule_id in enumerate(RULES):
            checkbox = QCheckBox(RULE_LABELS.get(rule_id, rule_id))
            checkbox.setChecked(default_states.get(rule_id, False))
            checkbox.setToolTip(RULE_TOOLTIPS.get(rule_id, ""))
            self.rule_checkboxes[rule_id] = checkbox
            rules_layout.addWidget(checkbox, index // 5, index % 5)
        self.rules_section.content_layout.addWidget(rules_widget)
        layout.addWidget(self.rules_section)

        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.inspect_btn = QPushButton("Inspect Structure")
        self.inspect_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        )
        self.inspect_btn.clicked.connect(self.inspect_source)
        self.inspect_btn.setToolTip(
            "Read EXR metadata, channels and inferred AOV structure without running validation rules."
        )
        actions.addWidget(self.inspect_btn)
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.analyze_btn.clicked.connect(self.start_analysis)
        self.analyze_btn.setToolTip(
            "Discover files, read their AOVs, calculate metrics and execute the enabled rules."
        )
        actions.addWidget(self.analyze_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.cancel_btn.clicked.connect(self.cancel_analysis)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip(
            "Request cooperative cancellation after the currently processed frame finishes."
        )
        actions.addWidget(self.cancel_btn)
        self.export_json_btn = QPushButton("Export JSON")
        self.export_json_btn.setIcon(
            self.style().standardIcon(QStyle.SP_DialogSaveButton)
        )
        self.export_json_btn.clicked.connect(self.export_json)
        self.export_json_btn.setEnabled(False)
        self.export_json_btn.setToolTip(
            "Export the complete machine-readable analysis report as canonical JSON."
        )
        actions.addWidget(self.export_json_btn)
        self.export_html_btn = QPushButton("Export HTML")
        self.export_html_btn.setIcon(
            self.style().standardIcon(QStyle.SP_DialogSaveButton)
        )
        self.export_html_btn.clicked.connect(self.export_html)
        self.export_html_btn.setEnabled(False)
        self.export_html_btn.setToolTip(
            "Export a self-contained HTML report for human review."
        )
        actions.addWidget(self.export_html_btn)
        self.compare_json_btn = QPushButton("Compare Baseline")
        self.compare_json_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.compare_json_btn.setToolTip(
            "Compare the current analysis with a canonical AOVGuard JSON report"
        )
        self.compare_json_btn.clicked.connect(self.compare_baseline_json)
        self.compare_json_btn.setEnabled(False)
        actions.addWidget(self.compare_json_btn)

        self.structure_label = QLabel("Structure not inspected.")
        self.structure_label.setWordWrap(True)
        self.structure_label.setToolTip(
            "Summary of detected channels, AOV categories and luminance-analysis scope."
        )
        layout.addWidget(self.structure_label)

        self.status_label = QLabel("NOT ANALYZED")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumHeight(30)
        layout.addWidget(self.status_label)
        self._set_status("NOT ANALYZED", "neutral")

        self.progress_label = QLabel("Ready.")
        self.progress_label.setToolTip(
            "Current analysis stage and final count of processed or failed files."
        )
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setToolTip("Percentage of discovered EXR files processed.")
        layout.addWidget(self.progress_bar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        findings_widget = QWidget()
        findings_layout = QVBoxLayout(findings_widget)
        findings_layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        findings_layout.addLayout(filters)
        self.search_label = _help_label(
            "Search:",
            "Filter findings by rule, AOV, channel, message or file path.",
        )
        filters.addWidget(self.search_label)
        self.finding_search = QLineEdit()
        self.finding_search.setPlaceholderText("Rule, AOV, channel, message or file")
        self.finding_search.setToolTip(
            "Type text to show only findings containing that term."
        )
        self.finding_search.textChanged.connect(self.apply_finding_filters)
        filters.addWidget(self.finding_search, 1)
        self.severity_label = _help_label(
            "Severity:",
            "Filter findings by error, warning or informational severity."
        )
        filters.addWidget(self.severity_label)
        self.severity_filter = QComboBox()
        self.severity_filter.addItem("All", None)
        self.severity_filter.addItem("Errors", Severity.ERROR.value)
        self.severity_filter.addItem("Warnings", Severity.WARNING.value)
        self.severity_filter.addItem("Info", Severity.INFO.value)
        self.severity_filter.setToolTip(
            "Choose which finding severity levels are visible in the table."
        )
        self.severity_filter.currentIndexChanged.connect(self.apply_finding_filters)
        filters.addWidget(self.severity_filter)
        self.failed_only_checkbox = QCheckBox("Failed frames only")
        self.failed_only_checkbox.setToolTip(
            "Show only findings associated with EXR files that could not be processed."
        )
        self.failed_only_checkbox.toggled.connect(self.apply_finding_filters)
        filters.addWidget(self.failed_only_checkbox)

        self.findings_table = QTableWidget(0, 6)
        self.findings_table.setHorizontalHeaderLabels(
            ["Severity", "Rule", "AOV", "Channel", "Message", "File"]
        )
        findings_header = self.findings_table.horizontalHeader()
        for column in (0, 1, 2, 3):
            findings_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        findings_header.setSectionResizeMode(4, QHeaderView.Stretch)
        findings_header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.findings_table.setColumnWidth(5, 220)
        self._prepare_table(self.findings_table, TABLE_VIEW_TOOLTIPS["findings"])
        self.findings_table.setSelectionMode(QTableWidget.SingleSelection)
        self.findings_table.currentCellChanged.connect(self.show_finding_details)
        self.findings_table.cellDoubleClicked.connect(
            lambda _row, _column: self.open_finding_location()
        )
        self.findings_panel = EmptyStateTable(
            self.findings_table,
            "No validation findings. Run an analysis to populate this view.",
        )
        findings_layout.addWidget(self.findings_panel, 1)

        self.finding_details_group = QGroupBox("Finding Details")
        self.finding_details_group.setToolTip(
            "Detailed evidence, affected files and recommended response for the selected finding."
        )
        details_layout = QVBoxLayout(self.finding_details_group)
        self.finding_details = QPlainTextEdit()
        self.finding_details.setReadOnly(True)
        self.finding_details.setToolTip(
            "Select a finding above to review its evidence and recommendation."
        )
        self.finding_details.setMaximumHeight(150)
        self.finding_details.setPlaceholderText(
            "Select a finding to inspect its evidence and recommendation."
        )
        details_layout.addWidget(self.finding_details)
        detail_actions = QHBoxLayout()
        details_layout.addLayout(detail_actions)
        detail_actions.addStretch(1)
        self.copy_path_btn = QPushButton("Copy Path")
        self.copy_path_btn.setToolTip(
            "Copy the selected finding's file path or affected-file list."
        )
        self.copy_path_btn.clicked.connect(self.copy_finding_path)
        self.copy_path_btn.setEnabled(False)
        detail_actions.addWidget(self.copy_path_btn)
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.open_folder_btn.clicked.connect(self.open_finding_location)
        self.open_folder_btn.setToolTip(
            "Open the folder containing the selected finding's EXR file."
        )
        self.open_folder_btn.setEnabled(False)
        detail_actions.addWidget(self.open_folder_btn)
        self.finding_details_group.setVisible(False)
        findings_layout.addWidget(self.finding_details_group)
        self.tabs.addTab(findings_widget, "Findings (0)")

        self.metrics_table = QTableWidget(0, 9)
        self.metrics_table.setHorizontalHeaderLabels(
            [
                "AOV",
                "Category",
                "Non-black Ratio",
                "Average Luminance",
                "Max Luminance",
                "Median",
                "MAD",
                "Outliers",
                "Channels",
            ]
        )
        header = self.metrics_table.horizontalHeader()
        for column in range(8):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        self._prepare_table(self.metrics_table, TABLE_VIEW_TOOLTIPS["metrics"])
        self.metrics_panel = EmptyStateTable(
            self.metrics_table,
            "No color AOV metrics are available for this source.",
        )
        self.tabs.addTab(self.metrics_panel, "Metrics")

        self.frame_table = QTableWidget(0, 10)
        self.frame_table.setHorizontalHeaderLabels(
            [
                "File",
                "AOV",
                "Non-black Ratio",
                "Average Luminance",
                "Max Luminance",
                "NaN",
                "+Inf",
                "-Inf",
                "Median Change",
                "Previous Change",
            ]
        )
        frame_header = self.frame_table.horizontalHeader()
        frame_header.setSectionResizeMode(0, QHeaderView.Stretch)
        frame_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for column in range(2, 10):
            frame_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._prepare_table(self.frame_table, TABLE_VIEW_TOOLTIPS["frames"])
        self.frame_table.cellDoubleClicked.connect(self.open_table_path)
        self.frame_panel = EmptyStateTable(
            self.frame_table,
            "No per-frame metrics are available.",
        )
        self.tabs.addTab(self.frame_panel, "Frames (0)")

        self.technical_table = QTableWidget(0, 10)
        self.technical_table.setHorizontalHeaderLabels(
            [
                "AOV",
                "Category",
                "Channel",
                "Minimum",
                "Average",
                "Maximum",
                "NaN",
                "+Inf",
                "-Inf",
                "Negative",
            ]
        )
        technical_header = self.technical_table.horizontalHeader()
        technical_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        technical_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        technical_header.setSectionResizeMode(2, QHeaderView.Stretch)
        for column in range(3, 10):
            technical_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._prepare_table(self.technical_table, TABLE_VIEW_TOOLTIPS["technical"])
        self.technical_panel = EmptyStateTable(
            self.technical_table,
            "No technical, vector, scalar or depth AOV diagnostics are available.",
        )
        self.tabs.addTab(self.technical_panel, "Technical (0)")

        self.sequence_table = QTableWidget(0, 7)
        self.sequence_table.setHorizontalHeaderLabels(
            ["Pattern", "Directory", "Range", "Present", "Missing", "Duplicates", "Padding"]
        )
        sequence_header = self.sequence_table.horizontalHeader()
        sequence_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        sequence_header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3, 4, 5, 6):
            sequence_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._prepare_table(self.sequence_table, TABLE_VIEW_TOOLTIPS["sequences"])
        self.sequence_table.cellDoubleClicked.connect(self.open_table_path)
        self.sequence_panel = EmptyStateTable(
            self.sequence_table,
            "No numbered EXR sequence has been detected.",
        )
        self.tabs.addTab(self.sequence_panel, "Sequences (0)")

        comparison_widget = QWidget()
        comparison_layout = QVBoxLayout(comparison_widget)
        comparison_layout.setContentsMargins(0, 0, 0, 0)
        self.comparison_summary_label = QLabel(
            "Analyze a source, then compare it with a baseline JSON report."
        )
        self.comparison_summary_label.setWordWrap(True)
        self.comparison_summary_label.setToolTip(
            "Summary of status, changed AOVs, new findings and resolved findings "
            "relative to the selected baseline report."
        )
        comparison_layout.addWidget(self.comparison_summary_label)
        self.comparison_table = QTableWidget(0, 5)
        self.comparison_table.setHorizontalHeaderLabels(
            ["AOV", "Status", "Average Delta", "Activity Delta", "Maximum Delta"]
        )
        comparison_header = self.comparison_table.horizontalHeader()
        comparison_header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 5):
            comparison_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._prepare_table(self.comparison_table, TABLE_VIEW_TOOLTIPS["comparison"])
        self.comparison_panel = EmptyStateTable(
            self.comparison_table,
            "Analyze a source, then compare it with a baseline JSON report.",
        )
        comparison_layout.addWidget(self.comparison_panel, 1)
        self.tabs.addTab(comparison_widget, "Comparison")

        for index, key in enumerate(
            ("findings", "metrics", "frames", "technical", "sequences", "comparison")
        ):
            self.tabs.setTabToolTip(index, TAB_TOOLTIPS[key])

        # Temporary compatibility alias for external code written against the
        # original single-table GUI.
        self.table = self.metrics_table

        self.log_section = CollapsibleSection("Log", expanded=False)
        self.log_section.toggle_button.setToolTip(
            "Show or hide processing messages, warnings and diagnostic errors."
        )
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setToolTip(
            "Chronological record of the current analysis session."
        )
        self.log_output.setMinimumHeight(120)
        self.log_output.setMaximumHeight(190)
        self.log_section.content_layout.addWidget(self.log_output)
        layout.addWidget(self.log_section)

        self._restore_preferences()

    def _prepare_table(self, table: QTableWidget, tooltip: str) -> None:
        table.setToolTip(tooltip)
        table.setSortingEnabled(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setToolTip(
            "Hover over a column name for its definition. Right-click to hide or restore columns."
        )
        for column in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(
                    TABLE_HEADER_TOOLTIPS.get(
                        header_item.text(),
                        f"Values shown in the {header_item.text()} column.",
                    )
                )
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(
            lambda position, target=table: self._show_column_menu(target, position)
        )
        self._table_default_widths[table] = tuple(
            table.columnWidth(column) for column in range(table.columnCount())
        )

    def _show_column_menu(self, table: QTableWidget, position: object) -> None:
        menu = QMenu(self)
        for column in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(column)
            label = header_item.text() if header_item is not None else f"Column {column + 1}"
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(column))
            action.toggled.connect(
                lambda visible, target=table, index=column: target.setColumnHidden(
                    index, not visible
                )
            )
            menu.addAction(action)
        menu.addSeparator()
        restore_action = menu.addAction("Restore Columns")
        restore_action.triggered.connect(lambda: self.restore_table_columns(table))
        header = table.horizontalHeader()
        menu.exec(header.mapToGlobal(position))

    def restore_table_columns(self, table: QTableWidget) -> None:
        for column in range(table.columnCount()):
            table.setColumnHidden(column, False)
        widths = self._table_default_widths.get(table, ())
        for column, width in enumerate(widths):
            if width > 0:
                table.setColumnWidth(column, width)

    def select_all_rules(self) -> None:
        for checkbox in self.rule_checkboxes.values():
            checkbox.setChecked(True)

    def clear_rules(self) -> None:
        for checkbox in self.rule_checkboxes.values():
            checkbox.setChecked(False)

    def restore_rule_selection(self, *, silent: bool = False) -> None:
        preset_path = self.rules_edit.text().strip()
        try:
            definitions = (
                load_rule_preset(preset_path).rules
                if preset_path
                else default_rule_definitions()
            )
        except Exception as exc:
            if not silent:
                QMessageBox.warning(
                    self, "AOVGuard", f"Could not restore rule preset: {exc}"
                )
            return
        enabled = {definition.id for definition in definitions if definition.enabled}
        for rule_id, checkbox in self.rule_checkboxes.items():
            checkbox.setChecked(rule_id in enabled)

    def _dialog_start_directory(self, value: str = "") -> str:
        candidate = Path(value or self.source_edit.text().strip())
        if candidate.is_file():
            return str(candidate.parent)
        if candidate.is_dir():
            return str(candidate)
        return str(candidate.parent) if str(candidate.parent) != "." else ""

    def _restore_preferences(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.source_edit.setText(str(self.settings.value("analysis/source", "")))
        self.rules_edit.setText(str(self.settings.value("analysis/preset", "")))
        luminance = str(self.settings.value("analysis/luminance", "Rec.709"))
        if self.luminance_combo.findText(luminance) >= 0:
            self.luminance_combo.setCurrentText(luminance)
        self.frame_pattern_edit.setText(
            str(self.settings.value("analysis/frame_pattern", "*.exr"))
        )
        self.recursive_checkbox.setChecked(
            self.settings.value("analysis/recursive", False, type=bool)
        )
        self.max_depth_spin.setValue(
            self.settings.value("analysis/max_depth", 1, type=int)
        )
        self.allow_multiple_sequences_checkbox.setChecked(
            self.settings.value("analysis/allow_multiple_sequences", False, type=bool)
        )
        stored_source_mode = str(
            self.settings.value("analysis/source_mode", SourceMode.AUTO.value)
        )
        try:
            self.source_mode_buttons[SourceMode(stored_source_mode)].setChecked(True)
        except ValueError:
            self.source_mode_buttons[SourceMode.AUTO].setChecked(True)
        weight_text = str(
            self.settings.value(
                "analysis/custom_weights", f"{REC709.r},{REC709.g},{REC709.b}"
            )
        )
        try:
            weights = tuple(float(value) for value in weight_text.split(","))
        except ValueError:
            weights = ()
        if len(weights) == 3:
            for spin, value in zip(self.custom_weight_spins, weights):
                spin.setValue(value)
        self.analysis_settings_section.set_expanded(
            self.settings.value("sections/analysis", False, type=bool)
        )
        self.rules_section.set_expanded(
            self.settings.value("sections/rules", True, type=bool)
        )
        self.log_section.set_expanded(
            self.settings.value("sections/log", False, type=bool)
        )
        selected_rules = str(self.settings.value("analysis/enabled_rules", ""))
        if selected_rules:
            enabled = {rule_id for rule_id in selected_rules.split(",") if rule_id}
            for rule_id, checkbox in self.rule_checkboxes.items():
                checkbox.setChecked(rule_id in enabled)
        elif self.rules_edit.text().strip():
            self.restore_rule_selection(silent=True)
        self._update_custom_weights_visibility(self.luminance_combo.currentText())

    def _save_preferences(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("analysis/source", self.source_edit.text().strip())
        self.settings.setValue("analysis/preset", self.rules_edit.text().strip())
        self.settings.setValue("analysis/luminance", self.luminance_combo.currentText())
        self.settings.setValue("analysis/frame_pattern", self.frame_pattern_edit.text().strip())
        self.settings.setValue("analysis/recursive", self.recursive_checkbox.isChecked())
        self.settings.setValue("analysis/max_depth", self.max_depth_spin.value())
        self.settings.setValue(
            "analysis/allow_multiple_sequences",
            self.allow_multiple_sequences_checkbox.isChecked(),
        )
        self.settings.setValue("analysis/source_mode", self._selected_source_mode().value)
        self.settings.setValue(
            "analysis/custom_weights",
            ",".join(str(spin.value()) for spin in self.custom_weight_spins),
        )
        enabled_rules = [
            rule_id
            for rule_id, checkbox in self.rule_checkboxes.items()
            if checkbox.isChecked()
        ]
        self.settings.setValue("analysis/enabled_rules", ",".join(enabled_rules))
        self.settings.setValue(
            "sections/analysis", self.analysis_settings_section.is_expanded()
        )
        self.settings.setValue("sections/rules", self.rules_section.is_expanded())
        self.settings.setValue("sections/log", self.log_section.is_expanded())
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_preferences()
        super().closeEvent(event)

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def _update_custom_weights_visibility(self, model: str) -> None:
        self.custom_weights_widget.setVisible(model == "Custom")
        self.luminance_combo.setToolTip(
            LUMINANCE_MODEL_TOOLTIPS.get(
                model,
                "Select the RGB weighting model used for color-AOV luminance.",
            )
        )

    def _set_status(self, text: str, status: str) -> None:
        colors = {
            "pass": ("#d7f2df", "#145c2c"),
            "warning": ("#fff0bd", "#704f00"),
            "fail": ("#ffdcdc", "#8b1e1e"),
            "running": ("#dcecff", "#174f82"),
            "cancelled": ("#e8ebee", "#424b55"),
            "neutral": ("#eef1f4", "#424b55"),
        }
        background, foreground = colors[status]
        self.status_label.setText(text)
        self.status_label.setToolTip(
            STATUS_TOOLTIPS.get(status, "Current overall analysis status.")
        )
        self.status_label.setStyleSheet(
            f"QLabel {{ background: {background}; color: {foreground}; "
            "font-weight: 700; border-radius: 4px; padding: 5px; }}"
        )

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
            self.frame_pattern_edit,
            self.recursive_checkbox,
            self.allow_multiple_sequences_checkbox,
            self.select_all_rules_btn,
            self.clear_rules_btn,
            self.restore_rules_btn,
            self.compare_json_btn,
            *self.source_mode_buttons.values(),
            *self.custom_weight_spins,
            *self.rule_checkboxes.values(),
        ):
            widget.setEnabled(not busy)
        self.max_depth_spin.setEnabled((not busy) and self.recursive_checkbox.isChecked())
        self.cancel_btn.setEnabled(busy)
        self.export_json_btn.setEnabled((not busy) and self.report is not None)
        self.export_html_btn.setEnabled((not busy) and self.report is not None)
        self.compare_json_btn.setEnabled((not busy) and self.report is not None)

    def browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select EXR File",
            self._dialog_start_directory(),
            "EXR Files (*.exr *.EXR);;All Files (*)",
        )
        if path:
            self.source_edit.setText(path)
            self._save_preferences()

    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select EXR Folder", self._dialog_start_directory()
        )
        if folder:
            self.source_edit.setText(folder)
            self._save_preferences()

    def browse_rules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Rule Preset",
            self._dialog_start_directory(self.rules_edit.text().strip()),
            "Rule Presets (*.toml *.json)",
        )
        if path:
            self.rules_edit.setText(path)
            try:
                preset = load_rule_preset(path)
            except Exception as exc:
                QMessageBox.warning(self, "AOVGuard", f"Could not load rule preset: {exc}")
                return
            enabled = {definition.id for definition in preset.rules if definition.enabled}
            for rule_id, checkbox in self.rule_checkboxes.items():
                checkbox.setChecked(rule_id in enabled)
            self._save_preferences()

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

    def _selected_source_mode(self) -> SourceMode:
        return next(
            (
                mode
                for mode, button in self.source_mode_buttons.items()
                if button.isChecked()
            ),
            SourceMode.AUTO,
        )

    def inspect_source(self) -> None:
        source = self._source()
        if source is None:
            return
        try:
            discovery = discover_frames(
                source,
                pattern=self.frame_pattern_edit.text().strip() or "*.exr",
                recursive=self.recursive_checkbox.isChecked(),
                max_depth=self.max_depth_spin.value(),
            )
            if not discovery.frames:
                raise FileNotFoundError(f"No EXR files found in {source}")
            inspection = OpenEXRReader().inspect(discovery.frames[0])
        except Exception as exc:
            QMessageBox.critical(self, "Inspect Error", str(exc))
            return

        self.structure_label.setText(
            f"{len(inspection.channels)} channels. {summarize_aov_categories(inspection)}"
        )
        self.structure_label.setToolTip(format_inspection(inspection))
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
        for widget in (self.finding_search, self.severity_filter, self.failed_only_checkbox):
            widget.blockSignals(True)
        self.finding_search.clear()
        self.severity_filter.setCurrentIndex(0)
        self.failed_only_checkbox.setChecked(False)
        for widget in (self.finding_search, self.severity_filter, self.failed_only_checkbox):
            widget.blockSignals(False)
        self.log_output.clear()
        self.log_section.set_expanded(True)
        self.metrics_table.setSortingEnabled(False)
        self.metrics_table.setRowCount(0)
        self.findings_table.setSortingEnabled(False)
        self.findings_table.setRowCount(0)
        self.sequence_table.setSortingEnabled(False)
        self.sequence_table.setRowCount(0)
        self.frame_table.setSortingEnabled(False)
        self.frame_table.setRowCount(0)
        self.technical_table.setSortingEnabled(False)
        self.technical_table.setRowCount(0)
        self.comparison_table.setSortingEnabled(False)
        self.comparison_table.setRowCount(0)
        self.tabs.setTabText(TAB_FINDINGS, "Findings (0)")
        self.tabs.setTabText(TAB_METRICS, "Metrics")
        self.tabs.setTabText(TAB_FRAMES, "Frames (0)")
        self.tabs.setTabText(TAB_TECHNICAL, "Technical (0)")
        self.tabs.setTabText(TAB_SEQUENCES, "Sequences (0)")
        self.tabs.setTabText(TAB_COMPARISON, "Comparison")
        self.findings_panel.show_empty(
            "Analysis is running. Findings will appear here when available."
        )
        self.metrics_panel.show_empty("Analysis is running.")
        self.frame_panel.show_empty("Analysis is running.")
        self.technical_panel.show_empty("Analysis is running.")
        self.sequence_panel.show_empty("Analysis is running.")
        self.comparison_panel.show_empty(
            "Analyze a source, then compare it with a baseline JSON report."
        )
        self.comparison_summary_label.setText(
            "Analyze a source, then compare it with a baseline JSON report."
        )
        self.selected_finding = None
        self.finding_details.clear()
        self.finding_details_group.setVisible(False)
        self.copy_path_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
        self.export_json_btn.setEnabled(False)
        self.export_html_btn.setEnabled(False)
        self.compare_json_btn.setEnabled(False)
        self.set_busy(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting analysis...")
        self._set_status("RUNNING", "running")
        self.append_log("Starting automatic EXR analysis...")
        self._save_preferences()

        self.thread = QThread(self)
        self.worker = AnalyzeWorker(
            str(source),
            rules_config=rules_config,
            luminance_model=self.luminance_combo.currentText(),
            custom_luminance_weights=tuple(
                spin.value() for spin in self.custom_weight_spins
            ),
            selected_rule_ids={
                rule_id
                for rule_id, checkbox in self.rule_checkboxes.items()
                if checkbox.isChecked()
            },
            frame_pattern=self.frame_pattern_edit.text().strip() or "*.exr",
            recursive=self.recursive_checkbox.isChecked(),
            max_depth=self.max_depth_spin.value(),
            allow_multiple_sequences=self.allow_multiple_sequences_checkbox.isChecked(),
            source_mode=self._selected_source_mode(),
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.cancelled.connect(self.on_analysis_cancelled)
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.on_progress)

        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.worker.deleteLater)
        self.worker.cancelled.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def cancel_analysis(self) -> None:
        if self.worker is None:
            return
        self.worker.request_cancel()
        self.cancel_btn.setEnabled(False)
        self.progress_label.setText("Cancelling after the current frame...")
        self._set_status("CANCELLING", "cancelled")
        self.append_log("Cancellation requested; finishing the current frame.")

    def on_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def _aov_help(self, name: str | None) -> str:
        if not name:
            return "This finding is not associated with one specific AOV."
        if self.report is not None:
            for inspection in self.report.inspections:
                for descriptor in inspection.aovs:
                    if descriptor.name == name:
                        return aov_tooltip(
                            descriptor.name,
                            descriptor.category,
                            descriptor.channels,
                        )
        return aov_tooltip(name)

    def _add_row(
        self,
        table: QTableWidget,
        values: list[str],
        *,
        numeric_columns: tuple[int, ...] = (),
        color: QColor | None = None,
        sort_keys: dict[int, object] | None = None,
        tooltips: dict[int, str] | None = None,
        user_data: dict[int, object] | None = None,
        icons: dict[int, QIcon] | None = None,
    ) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            sort_key = sort_keys.get(column) if sort_keys is not None else None
            item = SortableTableWidgetItem(value, sort_key)
            tooltip = tooltips.get(column) if tooltips is not None else None
            if tooltip:
                item.setToolTip(tooltip)
            else:
                header_item = table.horizontalHeaderItem(column)
                definition = header_item.toolTip() if header_item is not None else ""
                displayed = value or "No value"
                item.setToolTip(
                    f"{definition}\n\nDisplayed value: {displayed}"
                    if definition
                    else displayed
                )
            if user_data is not None and column in user_data:
                item.setData(FULL_PATH_ROLE, user_data[column])
            if icons is not None and column in icons:
                item.setIcon(icons[column])
            if column in numeric_columns:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if color is not None:
                item.setBackground(color)
            table.setItem(row, column, item)

    def _severity_icon(self, severity: Severity) -> QIcon:
        pixmaps = {
            Severity.ERROR: QStyle.SP_MessageBoxCritical,
            Severity.WARNING: QStyle.SP_MessageBoxWarning,
            Severity.INFO: QStyle.SP_MessageBoxInformation,
        }
        return self.style().standardIcon(pixmaps[severity])

    def open_table_path(self, row: int, _column: int) -> None:
        table = self.sender()
        if not isinstance(table, QTableWidget) or row < 0:
            return
        raw_path = None
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is not None and item.data(FULL_PATH_ROLE):
                raw_path = item.data(FULL_PATH_ROLE)
                break
        if raw_path is None:
            return
        path = Path(str(raw_path))
        location = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(location.resolve())))

    def apply_finding_filters(self, *_args: object) -> None:
        self.findings_table.setSortingEnabled(False)
        self.findings_table.setRowCount(0)
        self.selected_finding = None
        self.finding_details.clear()
        self.finding_details_group.setVisible(False)
        self.copy_path_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
        if self.report is None:
            self.tabs.setTabText(TAB_FINDINGS, "Findings (0)")
            self.findings_panel.show_empty(
                "No validation findings. Run an analysis to populate this view."
            )
            self.findings_table.setSortingEnabled(True)
            return

        severity = self.severity_filter.currentData()
        query = self.finding_search.text().strip().casefold()
        failed_only = self.failed_only_checkbox.isChecked()
        failed_frames = set(self.report.failed_frames)
        severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        indexed_findings = sorted(
            enumerate(self.report.findings),
            key=lambda item: (
                severity_order[item[1].severity],
                item[1].rule_id,
                str(item[1].file or ""),
            ),
        )
        visible_count = 0
        for finding_index, finding in indexed_findings:
            if severity is not None and finding.severity.value != severity:
                continue
            if failed_only and not (
                finding.file in failed_frames
                or any(path in failed_frames for path in finding.affected_files)
            ):
                continue
            searchable = " ".join(
                (
                    finding.severity.value,
                    finding.rule_id,
                    finding.aov or "",
                    finding.channel or "",
                    finding.message,
                    str(finding.file or self.report.source),
                    " ".join(str(path) for path in finding.affected_files),
                )
            ).casefold()
            if query and query not in searchable:
                continue
            finding_path = finding.file or self.report.source
            source_label = finding_source_label(
                len(finding.affected_files), finding.file is not None
            )
            file_label = source_label or display_path(
                finding_path, self.report.source
            )
            file_tooltip = (
                "\n".join(str(path) for path in finding.affected_files)
                if finding.affected_files
                else str(finding_path)
            )
            path_user_data = str(finding.file) if finding.file is not None else None
            self._add_row(
                self.findings_table,
                [
                    finding.severity.value,
                    finding.rule_id,
                    finding.aov or "",
                    finding.channel or "",
                    finding.message,
                    file_label,
                ],
                color=SEVERITY_COLORS.get(finding.severity),
                sort_keys={0: severity_order[finding.severity]},
                tooltips={
                    0: SEVERITY_TOOLTIPS[finding.severity.value],
                    1: RULE_TOOLTIPS.get(
                        finding.rule_id,
                        f"Validation rule identifier: {finding.rule_id}.",
                    ),
                    2: self._aov_help(finding.aov),
                    3: (
                        f"EXR channel associated with this finding: {finding.channel}."
                        if finding.channel
                        else "This finding is not limited to one EXR channel."
                    ),
                    5: file_tooltip,
                },
                user_data={5: path_user_data} if path_user_data else None,
                icons={0: self._severity_icon(finding.severity)},
            )
            row = self.findings_table.rowCount() - 1
            self.findings_table.item(row, 0).setData(Qt.UserRole, finding_index)
            visible_count += 1

        self.findings_table.setSortingEnabled(True)
        self.findings_table.sortItems(0, Qt.AscendingOrder)
        total = len(self.report.findings)
        label = f"Findings ({total})" if visible_count == total else f"Findings ({visible_count}/{total})"
        self.tabs.setTabText(TAB_FINDINGS, label)
        if visible_count:
            self.findings_panel.show_table()
            self.findings_table.setCurrentCell(0, 0)
        elif total:
            self.findings_panel.show_empty("No findings match the current filters.")
        else:
            self.findings_panel.show_empty(
                "No validation findings were produced for the selected rules."
            )

    def show_finding_details(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if self.report is None or current_row < 0:
            return
        item = self.findings_table.item(current_row, 0)
        if item is None:
            return
        finding_index = item.data(Qt.UserRole)
        if finding_index is None:
            return
        finding = self.report.findings[int(finding_index)]
        self.selected_finding = finding
        self.finding_details_group.setVisible(True)
        path = finding.file or self.report.source
        lines = [
            f"Severity: {finding.severity.value}",
            f"Rule: {finding.rule_id}",
            f"AOV: {finding.aov or '-'}",
            f"Channel: {finding.channel or '-'}",
            f"File: {path}",
            "",
            finding.message,
            "",
            f"Recommendation: {finding_recommendation(finding)}",
        ]
        if finding.affected_files:
            lines.extend(["", "Affected files:"])
            lines.extend(f"  {affected}" for affected in finding.affected_files)
        if finding.metrics:
            lines.extend(["", "Evidence:"])
            lines.extend(f"  {key}: {value}" for key, value in finding.metrics.items())
        self.finding_details.setPlainText("\n".join(lines))
        self.copy_path_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(True)

    def copy_finding_path(self) -> None:
        if self.selected_finding is None or self.report is None:
            return
        if self.selected_finding.affected_files:
            value = "\n".join(
                str(path) for path in self.selected_finding.affected_files
            )
        else:
            value = str(self.selected_finding.file or self.report.source)
        QApplication.clipboard().setText(value)

    def open_finding_location(self) -> None:
        if self.selected_finding is None or self.report is None:
            return
        path = Path(
            self.selected_finding.file
            or next(iter(self.selected_finding.affected_files), self.report.source)
        )
        location = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(location.resolve())))

    def on_analysis_finished(self, payload: object) -> None:
        report, options = payload
        self.report = report
        self.options = options
        self.set_busy(False)
        try:
            self._display_analysis_results(report)
        except Exception as exc:
            details = traceback.format_exc()
            self.progress_label.setText("Analysis completed, but results could not be displayed.")
            self.append_log(f"Result display failed: {exc}")
            self.append_log(details)
            QMessageBox.critical(self, "Display Error", str(exc))

    def _display_analysis_results(self, report: AnalysisReport) -> None:
        self.metrics_table.setSortingEnabled(False)
        self.metrics_table.setRowCount(0)
        self.findings_table.setSortingEnabled(False)
        self.findings_table.setRowCount(0)
        self.sequence_table.setSortingEnabled(False)
        self.sequence_table.setRowCount(0)
        self.frame_table.setSortingEnabled(False)
        self.frame_table.setRowCount(0)
        self.technical_table.setSortingEnabled(False)
        self.technical_table.setRowCount(0)

        categories = {}
        channels = {}
        channel_names = {}
        if report.inspections:
            for descriptor in report.inspections[0].aovs:
                categories[descriptor.name] = descriptor.category.value
                channels[descriptor.name] = ", ".join(descriptor.channels)
                channel_names[descriptor.name] = descriptor.channels

        for aov_name, metrics in report.metrics_by_aov.items():
            series = report.series_metrics_by_aov.get(aov_name)
            self._add_row(
                self.metrics_table,
                [
                    aov_name,
                    categories.get(aov_name, "unknown"),
                    f"{metrics.non_black_ratio:.5f}",
                    f"{metrics.avg_luminance:.6f}",
                    f"{metrics.max_luminance:.6f}",
                    f"{series.median_luminance:.6f}" if series else "-",
                    f"{series.mad_luminance:.6f}" if series else "-",
                    str(len(series.outlier_frames)) if series else "0",
                    channels.get(aov_name, ""),
                ],
                numeric_columns=(2, 3, 4, 5, 6, 7),
                color=SEVERITY_COLORS[Severity.INFO],
                tooltips={
                    0: aov_tooltip(
                        aov_name,
                        categories.get(aov_name, "unknown"),
                        channel_names.get(aov_name, ()),
                    ),
                    1: category_tooltip(categories.get(aov_name, "unknown")),
                },
            )
        if report.metrics_by_aov:
            self.metrics_panel.show_table()
        else:
            self.metrics_panel.show_empty(
                "No color AOV metrics are available for this source."
            )

        for aov_name, channel_metrics in report.channel_metrics_by_aov.items():
            if aov_name in report.metrics_by_aov:
                continue
            for channel_name, metrics in channel_metrics.items():
                self._add_row(
                    self.technical_table,
                    [
                        aov_name,
                        categories.get(aov_name, "unknown"),
                        channel_name,
                        f"{metrics.min_value:.6f}",
                        f"{metrics.avg_value:.6f}",
                        f"{metrics.max_value:.6f}",
                        str(metrics.nan_count),
                        str(metrics.posinf_count),
                        str(metrics.neginf_count),
                        str(metrics.negative_count),
                    ],
                    numeric_columns=(3, 4, 5, 6, 7, 8, 9),
                    color=SEVERITY_COLORS[Severity.INFO],
                    tooltips={
                        0: aov_tooltip(
                            aov_name,
                            categories.get(aov_name, "unknown"),
                            channel_names.get(aov_name, ()),
                        ),
                        1: category_tooltip(categories.get(aov_name, "unknown")),
                        2: (
                            f"Named EXR component {channel_name} belonging to the "
                            f"{aov_name} AOV."
                        ),
                    },
                )
        if report.technical_aov_count:
            self.technical_panel.show_table()
        else:
            self.technical_panel.show_empty(
                "No technical, vector, scalar or depth AOV diagnostics are available."
            )

        for sequence in report.sequence_check.sequences:
            frame_range = (
                f"{sequence.start_frame}-{sequence.end_frame}"
                if sequence.start_frame != sequence.end_frame
                else str(sequence.start_frame)
            )
            self._add_row(
                self.sequence_table,
                [
                    sequence.pattern,
                    display_path(sequence.directory, report.source),
                    frame_range,
                    str(sequence.frame_count),
                    format_frame_ranges(sequence.missing_ranges) or "-",
                    ", ".join(map(str, sequence.duplicate_frames)) or "-",
                    ", ".join(map(str, sequence.padding_widths)),
                ],
                numeric_columns=(3,),
                tooltips={1: str(sequence.directory)},
                user_data={1: str(sequence.directory)},
            )

        if report.sequence_check.sequences:
            self.sequence_panel.show_table()
        else:
            standalone_count = len(report.sequence_check.unnumbered_files)
            if standalone_count:
                noun = "file" if standalone_count == 1 else "files"
                if report.source_kind is SourceKind.COMPARISON_SET:
                    self.sequence_panel.show_empty(
                        f"Comparison set: {standalone_count} independent EXR {noun} analyzed."
                    )
                else:
                    self.sequence_panel.show_empty(
                        f"No numbered EXR sequence detected. {standalone_count} standalone "
                        f"EXR {noun} analyzed."
                    )
            else:
                self.sequence_panel.show_empty(
                    "No numbered EXR sequence has been detected."
                )

        previous_metrics = {}
        for frame_path, aov_metrics in report.frame_metrics.items():
            for aov_name, metrics in aov_metrics.items():
                series = report.series_metrics_by_aov.get(aov_name)
                median = series.median_luminance if series else metrics.avg_luminance
                previous = previous_metrics.get(aov_name, metrics)
                self._add_row(
                    self.frame_table,
                    [
                        display_path(frame_path, report.source),
                        aov_name,
                        f"{metrics.non_black_ratio:.5f}",
                        f"{metrics.avg_luminance:.6f}",
                        f"{metrics.max_luminance:.6f}",
                        str(metrics.nan_count),
                        str(metrics.posinf_count),
                        str(metrics.neginf_count),
                        format_percentage_change(
                            metrics.avg_luminance, median
                        ),
                        format_percentage_change(
                            metrics.avg_luminance, previous.avg_luminance
                        ),
                    ],
                    numeric_columns=(2, 3, 4, 5, 6, 7, 8, 9),
                    color=SEVERITY_COLORS[Severity.INFO],
                    tooltips={
                        0: str(frame_path),
                        1: aov_tooltip(
                            aov_name,
                            categories.get(aov_name, "unknown"),
                            channel_names.get(aov_name, ()),
                        ),
                    },
                    user_data={0: str(frame_path)},
                )
                previous_metrics[aov_name] = metrics

        if report.frame_metrics:
            self.frame_panel.show_table()
        else:
            self.frame_panel.show_empty("No per-frame metrics are available.")

        self.metrics_table.setSortingEnabled(True)
        self.sequence_table.setSortingEnabled(True)
        self.frame_table.setSortingEnabled(True)
        self.technical_table.setSortingEnabled(True)
        self.metrics_table.sortItems(0, Qt.AscendingOrder)
        self.sequence_table.sortItems(0, Qt.AscendingOrder)
        self.frame_table.sortItems(0, Qt.AscendingOrder)
        self.technical_table.sortItems(0, Qt.AscendingOrder)
        standalone_count = len(report.sequence_check.unnumbered_files)
        if report.source_kind is SourceKind.COMPARISON_SET:
            sequence_label = f"Discovery | {report.discovered_frame_count} samples"
        elif report.source_kind is SourceKind.SINGLE_FILE:
            sequence_label = "Discovery | Single EXR"
        else:
            sequence_label = f"Sequences ({len(report.sequence_check.sequences)})"
            if standalone_count:
                sequence_label += f" | Standalone ({standalone_count})"
        self.tabs.setTabText(TAB_SEQUENCES, sequence_label)
        sample_label = (
            "Samples"
            if report.source_kind is SourceKind.COMPARISON_SET
            else "Frames"
        )
        self.tabs.setTabText(
            TAB_FRAMES, f"{sample_label} ({len(report.frame_metrics)})"
        )
        self.tabs.setTabText(TAB_TECHNICAL, f"Technical ({report.technical_aov_count})")
        self.apply_finding_filters()
        self.set_busy(False)
        self.export_json_btn.setEnabled(True)
        self.export_html_btn.setEnabled(True)
        self.compare_json_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        finding_label = "finding" if len(report.findings) == 1 else "findings"
        analyzed_aov_count = len(report.metrics_by_aov)
        analyzed_aov_label = (
            "color AOV" if analyzed_aov_count == 1 else "color AOVs"
        )
        technical_aov_label = (
            "technical AOV"
            if report.technical_aov_count == 1
            else "technical AOVs"
        )
        item_label = "samples" if report.source_kind is SourceKind.COMPARISON_SET else "frames"
        self.progress_label.setText(
            f"Analysis complete. {report.frame_count}/{report.discovered_frame_count} "
            f"{item_label} processed, {report.failed_frame_count} failed, "
            f"{analyzed_aov_count} {analyzed_aov_label} analyzed, "
            f"{report.technical_aov_count} {technical_aov_label} diagnosed, "
            f"{len(report.findings)} {finding_label}."
        )
        self.append_log(self.progress_label.text())
        status = analysis_status(report)
        counts = severity_counts(report)
        self._set_status(
            f"{status.value.upper()} | {counts[Severity.ERROR]} errors | "
            f"{counts[Severity.WARNING]} warnings | {counts[Severity.INFO]} info",
            status.value,
        )
        if report.inspections:
            first = report.inspections[0]
            source_kind_label = {
                SourceKind.SINGLE_FILE: "Single EXR",
                SourceKind.NUMBERED_SEQUENCE: "Numbered sequence",
                SourceKind.COMPARISON_SET: "Comparison set",
            }[report.source_kind]
            self.structure_label.setText(
                f"{source_kind_label}. {len(first.channels)} channels. "
                f"{summarize_analysis_scope(first, report.metrics_by_aov, report.channel_metrics_by_aov)}"
            )
            self.structure_label.setToolTip(format_inspection(first))
        for warning in report.warnings:
            self.append_log(f"Warning: {warning}")
        if report.findings:
            self.tabs.setCurrentIndex(TAB_FINDINGS)
        elif report.failed_frames:
            self.tabs.setCurrentIndex(TAB_FRAMES)
        elif report.metrics_by_aov:
            self.tabs.setCurrentIndex(TAB_METRICS)
        elif report.technical_aov_count:
            self.tabs.setCurrentIndex(TAB_TECHNICAL)
        else:
            self.tabs.setCurrentIndex(TAB_SEQUENCES)
        if not report.failed_frames:
            self.log_section.set_expanded(False)

    def on_analysis_error(self, message: str, details: str) -> None:
        self.set_busy(False)
        self.log_section.set_expanded(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Analysis failed.")
        self._set_status("FAIL | ANALYSIS ERROR", "fail")
        self.append_log("Analysis failed.")
        self.append_log(f"Error: {message}")
        if details.strip():
            self.append_log(details)
        QMessageBox.critical(self, "Analysis Error", message)

    def on_analysis_cancelled(self) -> None:
        self.set_busy(False)
        self.log_section.set_expanded(True)
        self.progress_label.setText("Analysis cancelled after the current frame.")
        self._set_status("CANCELLED", "cancelled")
        self.append_log("Analysis cancelled after the current frame.")

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

    def export_html(self) -> None:
        if self.report is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export HTML",
            "aovguard_report.html",
            "HTML Files (*.html)",
        )
        if not path:
            return
        write_analysis_html(self.report, path, options=self.options)
        self.append_log(f"HTML report written to: {path}")

    def compare_baseline_json(self) -> None:
        if self.report is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Baseline AOVGuard Report",
            self._dialog_start_directory(),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            baseline = load_report_payload(path)
            candidate = build_analysis_report_payload(
                self.report,
                options=self.options,
            )
            comparison = compare_report_payloads(baseline, candidate)
        except Exception as exc:
            QMessageBox.critical(self, "Comparison Error", str(exc))
            return

        self.comparison_table.setSortingEnabled(False)
        self.comparison_table.setRowCount(0)
        for delta in comparison.metric_deltas:
            def format_delta(value: float | None) -> str:
                if value is None:
                    return "-"
                normalized = 0.0 if abs(value) < 5e-13 else value
                return f"{normalized:+.6f}"

            color = (
                SEVERITY_COLORS[Severity.INFO]
                if delta.status == "unchanged"
                else SEVERITY_COLORS[Severity.WARNING]
            )
            self._add_row(
                self.comparison_table,
                [
                    delta.aov,
                    delta.status,
                    format_delta(delta.average_luminance_delta),
                    format_delta(delta.non_black_ratio_delta),
                    format_delta(delta.max_luminance_delta),
                ],
                numeric_columns=(2, 3, 4),
                color=color,
                tooltips={
                    0: self._aov_help(delta.aov),
                    1: (
                        f"Baseline comparison status for {delta.aov}: {delta.status}."
                    ),
                },
            )
        self.comparison_table.setSortingEnabled(True)
        self.comparison_table.sortItems(0, Qt.AscendingOrder)
        if comparison.metric_deltas:
            self.comparison_panel.show_table()
        else:
            self.comparison_panel.show_empty("No color AOV metrics were available to compare.")
        self.tabs.setTabText(
            TAB_COMPARISON,
            f"Comparison ({comparison.changed_aov_count} changed)",
        )
        self.comparison_summary_label.setText(
            f"Baseline status: {comparison.baseline_status.upper()} | "
            f"Current status: {comparison.candidate_status.upper()} | "
            f"{comparison.changed_aov_count} changed AOVs | "
            f"{len(comparison.new_findings)} new findings | "
            f"{len(comparison.resolved_findings)} resolved findings"
        )
        self.tabs.setCurrentIndex(TAB_COMPARISON)
        self.append_log(
            "Report comparison complete: "
            f"{comparison.changed_aov_count} changed AOVs, "
            f"{len(comparison.new_findings)} new findings, "
            f"{len(comparison.resolved_findings)} resolved findings."
        )


def main() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName("AOVGuard")
    app.setApplicationName("AOVGuard")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
