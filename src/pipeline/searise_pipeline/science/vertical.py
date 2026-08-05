"""Uncertainty-aware vertical interval reconciliation and classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .contracts import ScienceContractError
from .uncertainty import UncertaintyAggregate

NODATA_CLASS = np.uint8(255)


class ClassificationReason(IntEnum):
    """Stable machine codes for class provenance and fail-closed outcomes."""

    NONE = 0
    OUTSIDE_COASTAL_SCOPE = 1
    COASTAL_SCOPE_UNAVAILABLE = 2
    TRANSFORM_OUT_OF_COVERAGE = 3
    SOURCE_NODATA = 4
    MISSING_UNCERTAINTY_BOUND = 5
    UNCERTAINTY_POLICY_UNAVAILABLE = 6
    EXCESSIVE_UNCERTAINTY = 7
    UNCERTAIN_THRESHOLD = 8
    CONNECTIVITY_UNAVAILABLE = 9
    CONNECTIVITY_REJECTED = 10


REASON_LABELS = {
    reason.value: reason.name.lower().replace("_", "-") for reason in ClassificationReason
}


@dataclass(frozen=True)
class VerticalResult:
    """Continuous clearance interval plus exact class and reason arrays."""

    lower_clearance_m: NDArray[np.float64]
    central_clearance_m: NDArray[np.float64]
    upper_clearance_m: NDArray[np.float64]
    class_values: NDArray[np.uint8]
    reason_codes: NDArray[np.uint8]


def _array(
    value: NDArray[np.floating[Any]], shape: tuple[int, ...], label: str
) -> NDArray[np.float64]:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != shape:
        raise ScienceContractError(f"Vertical {label} shape differs from baseline")
    return result


def _mask(
    value: NDArray[np.bool_] | None,
    shape: tuple[int, ...],
    label: str,
    *,
    default: bool,
) -> NDArray[np.bool_]:
    if value is None:
        return np.full(shape, default, dtype=np.bool_)
    result = np.asarray(value, dtype=np.bool_)
    if result.shape != shape:
        raise ScienceContractError(f"Vertical {label} shape differs from baseline")
    return result


def reconcile_vertical_interval(
    baseline_egm2008_m: NDArray[np.floating[Any]],
    projection_lower_m: NDArray[np.floating[Any]],
    projection_central_m: NDArray[np.floating[Any]],
    projection_upper_m: NDArray[np.floating[Any]],
    terrain_egm2008_m: NDArray[np.floating[Any]],
    baseline_uncertainty: UncertaintyAggregate,
    terrain_uncertainty: UncertaintyAggregate,
    *,
    coastal_scope: NDArray[np.bool_] | None,
    coastal_scope_known: NDArray[np.bool_] | None,
    transform_supported: NDArray[np.bool_] | None,
    connectivity_passed: NDArray[np.bool_] | None,
    connectivity_known: NDArray[np.bool_] | None,
    maximum_total_uncertainty_m: float | None,
) -> VerticalResult:
    """Apply the accepted interval rule and fail closed on incomplete evidence."""
    baseline = np.asarray(baseline_egm2008_m, dtype=np.float64)
    if baseline.ndim < 1:
        raise ScienceContractError("Vertical baseline must be an array")
    shape = baseline.shape
    lower_projection = _array(projection_lower_m, shape, "lower projection")
    central_projection = _array(projection_central_m, shape, "central projection")
    upper_projection = _array(projection_upper_m, shape, "upper projection")
    terrain = _array(terrain_egm2008_m, shape, "terrain")
    for label, aggregate in (
        ("baseline uncertainty", baseline_uncertainty),
        ("terrain uncertainty", terrain_uncertainty),
    ):
        if aggregate.values_m.shape != shape or aggregate.valid.shape != shape:
            raise ScienceContractError(f"Vertical {label} shape differs from baseline")

    finite_projection = (
        np.isfinite(lower_projection)
        & np.isfinite(central_projection)
        & np.isfinite(upper_projection)
    )
    if np.any(
        finite_projection
        & (
            (lower_projection > central_projection)
            | (central_projection > upper_projection)
        )
    ):
        raise ScienceContractError("Vertical projection interval is not monotonic")
    if maximum_total_uncertainty_m is not None and maximum_total_uncertainty_m < 0:
        raise ScienceContractError("Maximum total uncertainty cannot be negative")

    numeric = (
        np.isfinite(baseline)
        & finite_projection
        & np.isfinite(terrain)
        & baseline_uncertainty.valid
        & terrain_uncertainty.valid
    )
    lower_clearance = (
        baseline
        - baseline_uncertainty.values_m
        + lower_projection
        - (terrain + terrain_uncertainty.values_m)
    )
    central_clearance = baseline + central_projection - terrain
    upper_clearance = (
        baseline
        + baseline_uncertainty.values_m
        + upper_projection
        - (terrain - terrain_uncertainty.values_m)
    )
    for values in (lower_clearance, central_clearance, upper_clearance):
        values[~numeric] = np.nan

    classes = np.full(shape, NODATA_CLASS, dtype=np.uint8)
    reasons = np.zeros(shape, dtype=np.uint8)
    scope = _mask(coastal_scope, shape, "coastal scope", default=False)
    scope_known = _mask(
        coastal_scope_known, shape, "coastal-scope evidence", default=False
    )
    supported = _mask(transform_supported, shape, "transform support", default=False)
    connected = _mask(connectivity_passed, shape, "connectivity", default=False)
    connection_known = _mask(
        connectivity_known, shape, "connectivity evidence", default=False
    )

    def mark(mask: NDArray[np.bool_], reason: ClassificationReason) -> None:
        target = mask & (reasons == ClassificationReason.NONE)
        reasons[target] = reason

    mark(~scope_known, ClassificationReason.COASTAL_SCOPE_UNAVAILABLE)
    mark(scope_known & ~scope, ClassificationReason.OUTSIDE_COASTAL_SCOPE)
    mark(~supported, ClassificationReason.TRANSFORM_OUT_OF_COVERAGE)
    source_values_valid = (
        np.isfinite(baseline)
        & finite_projection
        & np.isfinite(terrain)
    )
    mark(~source_values_valid, ClassificationReason.SOURCE_NODATA)
    bounds_valid = baseline_uncertainty.valid & terrain_uncertainty.valid
    mark(~bounds_valid, ClassificationReason.MISSING_UNCERTAINTY_BOUND)
    if maximum_total_uncertainty_m is None:
        mark(
            np.ones(shape, dtype=np.bool_),
            ClassificationReason.UNCERTAINTY_POLICY_UNAVAILABLE,
        )
    else:
        total_bound = baseline_uncertainty.values_m + terrain_uncertainty.values_m
        mark(
            bounds_valid & (total_bound > maximum_total_uncertainty_m),
            ClassificationReason.EXCESSIVE_UNCERTAINTY,
        )

    ambiguous = (
        (reasons == ClassificationReason.NONE)
        & (lower_clearance < 0)
        & (upper_clearance >= 0)
    )
    mark(ambiguous, ClassificationReason.UNCERTAIN_THRESHOLD)

    definitive_no = (reasons == ClassificationReason.NONE) & (upper_clearance < 0)
    classes[definitive_no] = 0
    vertically_eligible = (reasons == ClassificationReason.NONE) & (lower_clearance >= 0)
    mark(vertically_eligible & ~connection_known, ClassificationReason.CONNECTIVITY_UNAVAILABLE)
    exposed = vertically_eligible & connection_known & connected
    rejected = vertically_eligible & connection_known & ~connected
    classes[exposed] = 1
    classes[rejected] = 0
    reasons[rejected] = ClassificationReason.CONNECTIVITY_REJECTED
    return VerticalResult(
        lower_clearance_m=lower_clearance,
        central_clearance_m=central_clearance,
        upper_clearance_m=upper_clearance,
        class_values=classes,
        reason_codes=reasons,
    )
