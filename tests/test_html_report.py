from pathlib import Path

from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    ChannelMetricSet,
    Finding,
    MetricSet,
    SequenceCheckResult,
    SequenceDescriptor,
    Severity,
)
from aovguard.reports.html_report import build_analysis_html, write_analysis_html


def _report(tmp_path: Path, *, severity: Severity = Severity.WARNING) -> AnalysisReport:
    frame = tmp_path / "shot.1001.exr"
    sequence = SequenceDescriptor(
        directory=tmp_path,
        prefix="shot.",
        suffix="",
        padding=4,
        frame_numbers=(1001, 1003),
        files=(frame, tmp_path / "shot.1003.exr"),
        missing_ranges=((1002, 1002),),
        padding_widths=(4,),
    )
    return AnalysisReport(
        source=tmp_path,
        frames=sequence.files,
        inspections=(),
        metrics_by_aov={"beauty<script>": MetricSet(1.0, 0.5, 2.0, pixel_count=4)},
        frame_metrics={
            frame: {"beauty<script>": MetricSet(1.0, 0.5, 2.0, pixel_count=4)},
        },
        channel_metrics_by_aov={
            "Z<depth>": {
                "Z": ChannelMetricSet(4, 2.5, 1.0, 4.0, negative_count=1),
            }
        },
        findings=(
            Finding(
                rule_id="sequence_gap",
                severity=severity,
                message="Missing <frame> & delivery.",
                file=tmp_path,
                metrics={"missing": 1002},
            ),
        ),
        sequence_check=SequenceCheckResult(source=tmp_path, sequences=(sequence,)),
    )


def test_html_report_contains_summary_sequences_and_recommendations(tmp_path: Path) -> None:
    report = _report(tmp_path)

    document = build_analysis_html(
        report,
        options=AnalysisOptions(preset_name="lighting_delivery"),
    )

    assert "AOVGuard Analysis Report" in document
    assert "WARNING" in document
    assert "shot.####.exr" in document
    assert "1002" in document
    assert "Locate or rerender" in document
    assert "lighting_delivery" in document
    assert "beauty&lt;script&gt;" in document
    assert "Per-frame Diagnostics" in document
    assert "Technical AOV Diagnostics" in document
    assert "Z&lt;depth&gt;" in document
    assert "Missing &lt;frame&gt; &amp; delivery." in document
    assert "beauty<script>" not in document


def test_html_report_writes_fail_status_for_error(tmp_path: Path) -> None:
    output = tmp_path / "reports" / "analysis.html"

    write_analysis_html(_report(tmp_path, severity=Severity.ERROR), output)

    text = output.read_text(encoding="utf-8")
    assert output.is_file()
    assert "status-fail" in text
    assert ">FAIL<" in text
