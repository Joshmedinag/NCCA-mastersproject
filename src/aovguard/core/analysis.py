from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np

from aovguard.core.luminance import LuminanceWeights, compute_luminance
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    ChannelMetricSet,
    Finding,
    FileInspection,
    MetricSet,
    Severity,
)
from aovguard.discovery.frame_discovery import discover_frames
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.engine import execute_rules
from aovguard.sequence.sequence_checker import check_sequences, sequence_findings

if TYPE_CHECKING:
    from aovguard.io.protocol import EXRReader

ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class _MetricAccumulator:
    non_black_threshold: float
    luminance_weights: LuminanceWeights
    pixel_count: int = 0
    finite_count: int = 0
    non_black_count: int = 0
    luminance_sum: float = 0.0
    abs_luminance_sum: float = 0.0
    max_luminance: float = float("-inf")
    max_abs_luminance: float = float("-inf")
    nan_count: int = 0
    posinf_count: int = 0
    neginf_count: int = 0

    def update(self, pixels: np.ndarray) -> None:
        luminance = compute_luminance(pixels, self.luminance_weights)
        self.pixel_count += int(luminance.size)
        self.nan_count += int(np.count_nonzero(np.isnan(luminance)))
        self.posinf_count += int(np.count_nonzero(np.isposinf(luminance)))
        self.neginf_count += int(np.count_nonzero(np.isneginf(luminance)))

        finite = luminance[np.isfinite(luminance)]
        if finite.size == 0:
            return

        self.finite_count += int(finite.size)
        absolute = np.abs(finite)
        self.non_black_count += int(
            np.count_nonzero(absolute > self.non_black_threshold)
        )
        self.luminance_sum += float(np.sum(finite, dtype=np.float64))
        self.abs_luminance_sum += float(np.sum(absolute, dtype=np.float64))
        self.max_luminance = max(self.max_luminance, float(np.max(finite)))
        self.max_abs_luminance = max(
            self.max_abs_luminance,
            float(np.max(absolute)),
        )

    def finalize(self) -> MetricSet:
        if self.finite_count:
            avg_luminance = self.luminance_sum / self.finite_count
            avg_abs_luminance = self.abs_luminance_sum / self.finite_count
            max_luminance = self.max_luminance
            max_abs_luminance = self.max_abs_luminance
        else:
            avg_luminance = float("nan")
            avg_abs_luminance = float("nan")
            max_luminance = float("nan")
            max_abs_luminance = float("nan")

        non_black_ratio = 0.0
        if self.pixel_count:
            non_black_ratio = self.non_black_count / self.pixel_count

        return MetricSet(
            non_black_ratio=non_black_ratio,
            avg_luminance=avg_luminance,
            max_luminance=max_luminance,
            pixel_count=self.pixel_count,
            nan_count=self.nan_count,
            posinf_count=self.posinf_count,
            neginf_count=self.neginf_count,
            avg_abs_luminance=avg_abs_luminance,
            max_abs_luminance=max_abs_luminance,
        )


@dataclass(slots=True)
class _ChannelMetricAccumulator:
    pixel_count: int = 0
    finite_count: int = 0
    value_sum: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    nan_count: int = 0
    posinf_count: int = 0
    neginf_count: int = 0
    negative_count: int = 0

    def update(self, values: np.ndarray) -> None:
        array = np.asarray(values, dtype=np.float32)
        self.pixel_count += int(array.size)
        self.nan_count += int(np.count_nonzero(np.isnan(array)))
        self.posinf_count += int(np.count_nonzero(np.isposinf(array)))
        self.neginf_count += int(np.count_nonzero(np.isneginf(array)))
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            return
        self.finite_count += int(finite.size)
        self.value_sum += float(np.sum(finite))
        self.min_value = min(self.min_value, float(np.min(finite)))
        self.max_value = max(self.max_value, float(np.max(finite)))
        self.negative_count += int(np.count_nonzero(finite < 0))

    def finalize(self) -> ChannelMetricSet:
        if self.finite_count:
            avg_value = self.value_sum / self.finite_count
            min_value = self.min_value
            max_value = self.max_value
        else:
            avg_value = float("nan")
            min_value = float("nan")
            max_value = float("nan")
        return ChannelMetricSet(
            pixel_count=self.pixel_count,
            avg_value=avg_value,
            min_value=min_value,
            max_value=max_value,
            nan_count=self.nan_count,
            posinf_count=self.posinf_count,
            neginf_count=self.neginf_count,
            negative_count=self.negative_count,
        )


def _rgb_channel_names(inspection: FileInspection, aov_name: str) -> tuple[str, str, str]:
    descriptor = next(
        (aov for aov in inspection.aovs if aov.name == aov_name),
        None,
    )
    if descriptor is None:
        return tuple(f"{aov_name}.{suffix}" for suffix in ("R", "G", "B"))
    by_suffix = {
        channel.rsplit(".", 1)[-1].upper(): channel
        for channel in descriptor.channels
    }
    return tuple(by_suffix.get(suffix, f"{aov_name}.{suffix}") for suffix in ("R", "G", "B"))


def analyze(
    source: str | Path,
    options: AnalysisOptions,
    reader: "EXRReader",
    rule_definitions: Sequence[RuleDefinition] | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> AnalysisReport:
    """Analyze EXR source data through the backend-independent reader protocol."""

    discovery = discover_frames(source)
    if not discovery.frames:
        raise FileNotFoundError(f"No EXR files found in {discovery.source}")
    sequence_check = check_sequences(discovery.frames, source=discovery.source)
    weights = LuminanceWeights.from_values(options.luminance_weights)
    accumulators: dict[str, _MetricAccumulator] = {}
    channel_accumulators: dict[str, dict[str, _ChannelMetricAccumulator]] = {}
    findings = list(sequence_findings(sequence_check))
    inspections: list[FileInspection] = []
    successful_frames: list[Path] = []
    failed_frames: list[Path] = []

    total_frames = len(discovery.frames)
    for frame_index, frame_path in enumerate(discovery.frames, start=1):
        try:
            frame = reader.read_frame(frame_path)
        except Exception as exc:
            failed_frames.append(frame_path)
            findings.append(
                Finding(
                    rule_id="read_frame",
                    severity=Severity.ERROR,
                    message=f"Could not read EXR frame: {exc}",
                    file=frame_path,
                )
            )
            if progress_callback is not None:
                progress_callback(frame_index, total_frames, f"Read failed: {frame_path.name}")
            continue

        inspection = frame.inspection
        inspections.append(inspection)
        unsupported_reason = inspection.unsupported_reason
        if unsupported_reason is not None:
            failed_frames.append(frame_path)
            findings.append(
                Finding(
                    rule_id="unsupported_structure",
                    severity=Severity.ERROR,
                    message=unsupported_reason,
                    file=frame_path,
                )
            )
            if progress_callback is not None:
                progress_callback(frame_index, total_frames, f"Unsupported EXR: {frame_path.name}")
            continue

        for aov_name, pixels in frame.aovs.items():
            accumulator = accumulators.setdefault(
                aov_name,
                _MetricAccumulator(
                    non_black_threshold=options.non_black_threshold,
                    luminance_weights=weights,
                ),
            )
            accumulator.update(pixels)
            if pixels.ndim >= 3 and pixels.shape[-1] >= 3:
                channel_names = _rgb_channel_names(inspection, aov_name)
                per_aov = channel_accumulators.setdefault(aov_name, {})
                for channel_index, channel_name in enumerate(channel_names):
                    channel_accumulator = per_aov.setdefault(
                        channel_name,
                        _ChannelMetricAccumulator(),
                    )
                    channel_accumulator.update(pixels[..., channel_index])
        successful_frames.append(frame_path)
        if progress_callback is not None:
            progress_callback(frame_index, total_frames, f"Processed {frame_path.name}")

    metrics_by_aov = {
        aov_name: accumulator.finalize()
        for aov_name, accumulator in sorted(accumulators.items())
    }
    channel_metrics_by_aov = {
        aov_name: {
            channel_name: accumulator.finalize()
            for channel_name, accumulator in sorted(channel_accumulators.items())
        }
        for aov_name, channel_accumulators in sorted(channel_accumulators.items())
    }

    definitions = default_rule_definitions() if rule_definitions is None else tuple(rule_definitions)
    if options.enabled_rules is not None:
        selected_rule_ids = set(options.enabled_rules)
        definitions = tuple(
            replace(definition, enabled=definition.id in selected_rule_ids)
            for definition in definitions
        )
    enabled_rule_ids = tuple(definition.id for definition in definitions if definition.enabled)
    report = AnalysisReport(
        source=discovery.source,
        frames=discovery.frames,
        inspections=tuple(inspections),
        metrics_by_aov=metrics_by_aov,
        successful_frames=tuple(successful_frames),
        failed_frames=tuple(failed_frames),
        findings=tuple(findings),
        warnings=discovery.warnings + sequence_check.warnings,
        rules_executed=enabled_rule_ids,
        sequence_check=sequence_check,
        channel_metrics_by_aov=channel_metrics_by_aov,
    )
    rule_findings = execute_rules(report, definitions)
    if not rule_findings:
        return report
    return replace(report, findings=report.findings + rule_findings)
