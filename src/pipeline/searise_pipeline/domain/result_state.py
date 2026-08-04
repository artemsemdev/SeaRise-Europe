"""Static-target five-state mapping, independent of legacy API types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

ResultState = Literal[
    "ModeledExposureDetected",
    "NoModeledExposureDetected",
    "DataUnavailable",
    "OutOfScope",
    "UnsupportedGeography",
]
ClassValue = Optional[Literal[0, 1]]


@dataclass(frozen=True)
class AssessmentSample:
    """Minimum domain evidence needed to determine a public result state."""

    in_europe: bool
    in_coastal_zone: Optional[bool]
    class_value: ClassValue


def determine_result_state(sample: AssessmentSample) -> ResultState:
    """Map support, coastal scope, and exact class evidence in safe precedence."""
    if not sample.in_europe:
        return "UnsupportedGeography"
    if sample.in_coastal_zone is False:
        return "OutOfScope"
    if sample.in_coastal_zone is not True:
        return "DataUnavailable"
    return _state_for_class(sample.class_value)


def _state_for_class(class_value: ClassValue) -> ResultState:
    if class_value is None:
        return "DataUnavailable"
    if class_value == 1:
        return "ModeledExposureDetected"
    if class_value == 0:
        return "NoModeledExposureDetected"
    raise ValueError(f"Unsupported class value: {class_value!r}")
