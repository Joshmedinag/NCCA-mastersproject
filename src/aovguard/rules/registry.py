from __future__ import annotations

from collections.abc import Callable

from aovguard.core.models import AnalysisReport, Finding
from aovguard.rules.builtin import (
    validate_aov_structure_mismatch,
    validate_constant_channel,
    validate_empty_aov,
    validate_missing_aov,
    validate_missing_channels,
    validate_nan_inf,
    validate_negative_values,
    validate_near_empty_aov,
    validate_resolution_mismatch,
)
from aovguard.rules.definitions import RuleDefinition

RuleFunction = Callable[[AnalysisReport, RuleDefinition], list[Finding]]

RULES: dict[str, RuleFunction] = {
    "nan_inf": validate_nan_inf,
    "empty_aov": validate_empty_aov,
    "near_empty_aov": validate_near_empty_aov,
    "missing_aov": validate_missing_aov,
    "missing_channels": validate_missing_channels,
    "negative_values": validate_negative_values,
    "constant_channel": validate_constant_channel,
    "resolution_mismatch": validate_resolution_mismatch,
    "aov_structure_mismatch": validate_aov_structure_mismatch,
}
