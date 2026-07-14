from pathlib import Path
from types import MappingProxyType

import numpy as np

from aovguard.core.models import (
    AOVCategory,
    AOVDescriptor,
    AnalysisReport,
    ChannelMetricSet,
    FileInspection,
    Finding,
    FrameData,
    MetricSet,
    Severity,
)


def test_file_inspection_reports_unsupported_deep_exr() -> None:
    inspection = FileInspection(
        path=Path("deep.exr"),
        width=16,
        height=16,
        channels=("R", "G", "B"),
        aovs=(),
        is_deep=True,
    )

    assert inspection.unsupported_reason == "Deep EXR data is not supported by the MVP backend."


def test_file_inspection_reports_unsupported_multipart_exr() -> None:
    inspection = FileInspection(
        path=Path("multi.exr"),
        width=16,
        height=16,
        channels=("R", "G", "B"),
        aovs=(),
        part_count=2,
    )

    assert "Multipart EXR" in inspection.unsupported_reason


def test_frame_data_freezes_aov_mapping() -> None:
    frame = FrameData(
        path=Path("frame.exr"),
        width=1,
        height=1,
        aovs={"beauty": np.zeros((1, 1, 3), dtype=np.float32)},
    )

    assert isinstance(frame.aovs, MappingProxyType)
    assert tuple(frame.aovs) == ("beauty",)


def test_finding_freezes_metrics_mapping() -> None:
    finding = Finding(
        rule_id="nan_inf",
        severity=Severity.ERROR,
        message="Non-finite values",
        metrics={"nan_count": 1},
    )

    assert isinstance(finding.metrics, MappingProxyType)
    assert finding.metrics["nan_count"] == 1


def test_analysis_report_frame_count_and_frozen_metrics() -> None:
    report = AnalysisReport(
        source=Path("renders"),
        frames=(Path("renders/shot.1001.exr"),),
        inspections=(),
        metrics_by_aov={
            "beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=10),
        },
        channel_metrics_by_aov={
            "beauty": {
                "R": ChannelMetricSet(10, 0.5, 0.0, 1.0),
            }
        },
    )

    assert report.frame_count == 1
    assert isinstance(report.metrics_by_aov, MappingProxyType)
    assert isinstance(report.channel_metrics_by_aov, MappingProxyType)
    assert isinstance(report.channel_metrics_by_aov["beauty"], MappingProxyType)


def test_channel_metric_properties() -> None:
    constant = ChannelMetricSet(4, 0.5, 0.5, 0.5)
    invalid = ChannelMetricSet(4, 0.0, 0.0, 0.0, nan_count=1)

    assert constant.is_constant
    assert not constant.has_non_finite
    assert invalid.has_non_finite
    assert not invalid.is_constant


def test_aov_descriptor_defaults_to_unknown_category() -> None:
    descriptor = AOVDescriptor(name="custom", channels=("custom.X",))

    assert descriptor.category is AOVCategory.UNKNOWN
    assert descriptor.category_confidence == "unknown"
