from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AOVCategory(StrEnum):
    COLOR = "color"
    SCALAR = "scalar"
    VECTOR = "vector"
    MASK = "mask"
    DEPTH = "depth"
    UNKNOWN = "unknown"


class SourceMode(StrEnum):
    """User-selected interpretation policy for a discovered EXR source."""

    AUTO = "auto"
    SEQUENCE = "sequence"
    COMPARISON = "comparison"


class SourceKind(StrEnum):
    """Resolved meaning of the files included in an analysis."""

    SINGLE_FILE = "single_file"
    NUMBERED_SEQUENCE = "numbered_sequence"
    COMPARISON_SET = "comparison_set"


@dataclass(frozen=True, slots=True)
class AOVDescriptor:
    name: str
    channels: tuple[str, ...]
    category: AOVCategory = AOVCategory.UNKNOWN
    category_confidence: str = "unknown"


@dataclass(frozen=True, slots=True)
class FileInspection:
    path: Path
    width: int
    height: int
    channels: tuple[str, ...]
    aovs: tuple[AOVDescriptor, ...]
    part_count: int = 1
    is_deep: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def unsupported_reason(self) -> str | None:
        if self.is_deep:
            return "Deep EXR data is not supported by the MVP backend."
        if self.part_count > 1:
            return "Multipart EXR data is detected but not fully supported by the MVP backend."
        return None


@dataclass(frozen=True, slots=True)
class FrameData:
    path: Path
    width: int
    height: int
    inspection: FileInspection
    aovs: Mapping[str, np.ndarray]
    channels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "aovs", MappingProxyType(dict(self.aovs)))


@dataclass(frozen=True, slots=True)
class MetricSet:
    non_black_ratio: float
    avg_luminance: float
    max_luminance: float
    pixel_count: int
    nan_count: int = 0
    posinf_count: int = 0
    neginf_count: int = 0
    avg_abs_luminance: float | None = None
    max_abs_luminance: float | None = None

    def __post_init__(self) -> None:
        if self.avg_abs_luminance is None:
            object.__setattr__(self, "avg_abs_luminance", abs(self.avg_luminance))
        if self.max_abs_luminance is None:
            object.__setattr__(self, "max_abs_luminance", abs(self.max_luminance))

    @property
    def has_non_finite(self) -> bool:
        return (self.nan_count + self.posinf_count + self.neginf_count) > 0


@dataclass(frozen=True, slots=True)
class ChannelMetricSet:
    pixel_count: int
    avg_value: float
    min_value: float
    max_value: float
    nan_count: int = 0
    posinf_count: int = 0
    neginf_count: int = 0
    negative_count: int = 0

    @property
    def has_non_finite(self) -> bool:
        return (self.nan_count + self.posinf_count + self.neginf_count) > 0

    @property
    def is_constant(self) -> bool:
        return (
            not self.has_non_finite
            and self.pixel_count > 0
            and self.min_value == self.max_value
        )


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str
    file: Path | None = None
    aov: str | None = None
    channel: str | None = None
    metrics: Mapping[str, object] = field(default_factory=dict)
    affected_files: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(
            self,
            "affected_files",
            tuple(Path(path) for path in self.affected_files),
        )


@dataclass(frozen=True, slots=True)
class AnalysisOptions:
    preset_name: str | None = None
    enabled_rules: tuple[str, ...] | None = None
    luminance_weights: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
    non_black_threshold: float = 1e-5
    frame_pattern: str = "*.exr"
    recursive: bool = False
    max_depth: int | None = 1
    allow_multiple_sequences: bool = False
    source_mode: SourceMode = SourceMode.AUTO

    def __post_init__(self) -> None:
        if not isinstance(self.source_mode, SourceMode):
            object.__setattr__(self, "source_mode", SourceMode(self.source_mode))
        if not self.frame_pattern.strip():
            raise ValueError("Frame pattern must not be empty.")
        if "/" in self.frame_pattern or "\\" in self.frame_pattern:
            raise ValueError("Frame pattern must be a filename pattern, not a path.")
        if self.max_depth is not None and self.max_depth < 0:
            raise ValueError("Discovery max_depth must be non-negative or None.")


@dataclass(frozen=True, slots=True)
class SequenceDescriptor:
    directory: Path
    prefix: str
    suffix: str
    padding: int
    frame_numbers: tuple[int, ...]
    files: tuple[Path, ...]
    missing_ranges: tuple[tuple[int, int], ...] = ()
    duplicate_frames: tuple[int, ...] = ()
    padding_widths: tuple[int, ...] = ()

    @property
    def pattern(self) -> str:
        return f"{self.prefix}{'#' * self.padding}{self.suffix}.exr"

    @property
    def start_frame(self) -> int | None:
        return self.frame_numbers[0] if self.frame_numbers else None

    @property
    def end_frame(self) -> int | None:
        return self.frame_numbers[-1] if self.frame_numbers else None

    @property
    def frame_count(self) -> int:
        return len(self.frame_numbers)

    @property
    def missing_frame_count(self) -> int:
        return sum(end - start + 1 for start, end in self.missing_ranges)


@dataclass(frozen=True, slots=True)
class SequenceCheckResult:
    source: Path | None = None
    sequences: tuple[SequenceDescriptor, ...] = ()
    unnumbered_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def missing_frame_count(self) -> int:
        return sum(sequence.missing_frame_count for sequence in self.sequences)

    @property
    def duplicate_frame_count(self) -> int:
        return sum(len(sequence.duplicate_frames) for sequence in self.sequences)


@dataclass(frozen=True, slots=True)
class SeriesMetricSet:
    """Robust cross-frame statistics for one color AOV."""

    frame_count: int
    median_luminance: float
    mad_luminance: float
    min_luminance: float
    max_luminance: float
    max_frame_delta: float
    max_frame_delta_from: Path | None = None
    max_frame_delta_to: Path | None = None
    outlier_frames: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    source: Path
    frames: tuple[Path, ...]
    inspections: tuple[FileInspection, ...]
    metrics_by_aov: Mapping[str, MetricSet]
    successful_frames: tuple[Path, ...] = ()
    failed_frames: tuple[Path, ...] = ()
    findings: tuple[Finding, ...] = ()
    warnings: tuple[str, ...] = ()
    rules_executed: tuple[str, ...] = ()
    sequence_check: SequenceCheckResult = field(default_factory=SequenceCheckResult)
    channel_metrics_by_aov: Mapping[str, Mapping[str, ChannelMetricSet]] = field(
        default_factory=dict
    )
    frame_metrics: Mapping[Path, Mapping[str, MetricSet]] = field(default_factory=dict)
    source_kind: SourceKind = SourceKind.SINGLE_FILE
    series_metrics_by_aov: Mapping[str, SeriesMetricSet] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, SourceKind):
            object.__setattr__(self, "source_kind", SourceKind(self.source_kind))
        if self.frames and not self.successful_frames and not self.failed_frames:
            object.__setattr__(self, "successful_frames", self.frames)
        object.__setattr__(self, "metrics_by_aov", MappingProxyType(dict(self.metrics_by_aov)))
        object.__setattr__(
            self,
            "channel_metrics_by_aov",
            MappingProxyType(
                {
                    aov_name: MappingProxyType(dict(channel_metrics))
                    for aov_name, channel_metrics in self.channel_metrics_by_aov.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "frame_metrics",
            MappingProxyType(
                {
                    Path(frame_path): MappingProxyType(dict(aov_metrics))
                    for frame_path, aov_metrics in self.frame_metrics.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "series_metrics_by_aov",
            MappingProxyType(dict(self.series_metrics_by_aov)),
        )

    @property
    def frame_count(self) -> int:
        """Number of frames successfully decoded and included in metrics."""

        return len(self.successful_frames)

    @property
    def discovered_frame_count(self) -> int:
        return len(self.frames)

    @property
    def failed_frame_count(self) -> int:
        return len(self.failed_frames)

    @property
    def technical_aov_count(self) -> int:
        return len(set(self.channel_metrics_by_aov) - set(self.metrics_by_aov))

    @property
    def analyzed_aov_count(self) -> int:
        return len(self.metrics_by_aov) + self.technical_aov_count
