from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from aovguard.core.models import AnalysisOptions, AnalysisReport, FileInspection, Finding


def _version() -> str:
    try:
        return metadata.version("aovguard")
    except metadata.PackageNotFoundError:
        return "unknown"


def _inspection_to_dict(inspection: FileInspection) -> dict[str, Any]:
    return {
        "path": str(inspection.path),
        "width": inspection.width,
        "height": inspection.height,
        "channels": list(inspection.channels),
        "aovs": [
            {
                "name": aov.name,
                "channels": list(aov.channels),
                "category": aov.category.value,
                "category_confidence": aov.category_confidence,
            }
            for aov in inspection.aovs
        ],
        "part_count": inspection.part_count,
        "is_deep": inspection.is_deep,
        "warnings": list(inspection.warnings),
    }


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,
        "message": finding.message,
        "file": str(finding.file) if finding.file is not None else None,
        "aov": finding.aov,
        "channel": finding.channel,
        "metrics": dict(finding.metrics),
    }


def _options_to_dict(options: AnalysisOptions | None) -> dict[str, Any] | None:
    if options is None:
        return None
    return {
        "preset_name": options.preset_name,
        "enabled_rules": list(options.enabled_rules),
        "luminance_weights": list(options.luminance_weights),
        "non_black_threshold": options.non_black_threshold,
    }


def build_analysis_report_payload(
    report: AnalysisReport,
    *,
    options: AnalysisOptions | None = None,
) -> dict[str, Any]:
    """Build the canonical JSON payload for the new backend analysis report."""

    severity_summary: dict[str, int] = {}
    for finding in report.findings:
        key = finding.severity.value
        severity_summary[key] = severity_summary.get(key, 0) + 1
    category_summary: dict[str, int] = {}
    if report.inspections:
        for descriptor in report.inspections[0].aovs:
            key = descriptor.category.value
            category_summary[key] = category_summary.get(key, 0) + 1

    return {
        "metadata": {
            "tool": "AOVGuard",
            "version": _version(),
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(report.source),
            "frames_processed": report.frame_count,
            "aovs_detected": sum(category_summary.values()),
            "aovs_analyzed": len(report.metrics_by_aov),
            "summary_by_aov_category": category_summary,
            "rules_executed": list(report.rules_executed),
            "summary_by_severity": severity_summary,
            "options": _options_to_dict(options),
        },
        "frames": [str(frame) for frame in report.frames],
        "warnings": list(report.warnings),
        "inspections": [_inspection_to_dict(inspection) for inspection in report.inspections],
        "metrics_by_aov": {
            name: asdict(metrics)
            for name, metrics in report.metrics_by_aov.items()
        },
        "channel_metrics_by_aov": {
            aov_name: {
                channel_name: asdict(metrics)
                for channel_name, metrics in channel_metrics.items()
            }
            for aov_name, channel_metrics in report.channel_metrics_by_aov.items()
        },
        "findings": [_finding_to_dict(finding) for finding in report.findings],
    }


def write_analysis_json(
    report: AnalysisReport,
    output_path: str | Path,
    *,
    options: AnalysisOptions | None = None,
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_analysis_report_payload(report, options=options)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
