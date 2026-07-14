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

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


@dataclass(frozen=True, slots=True)
class AnalysisOptions:
    preset_name: str | None = None
    enabled_rules: tuple[str, ...] = ()
    luminance_weights: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
    non_black_threshold: float = 1e-5


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    source: Path
    frames: tuple[Path, ...]
    inspections: tuple[FileInspection, ...]
    metrics_by_aov: Mapping[str, MetricSet]
    findings: tuple[Finding, ...] = ()
    warnings: tuple[str, ...] = ()
    rules_executed: tuple[str, ...] = ()
    channel_metrics_by_aov: Mapping[str, Mapping[str, ChannelMetricSet]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
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

    @property
    def frame_count(self) -> int:
        return len(self.frames)
