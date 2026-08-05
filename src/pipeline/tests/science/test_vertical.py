"""Tests for uncertainty-aware fail-closed vertical classification."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from searise_pipeline.science import (
    ClassificationReason,
    ScienceContractError,
    UncertaintyAggregate,
    reconcile_vertical_interval,
)


def _aggregate(
    values: list[float], valid: list[bool] | None = None
) -> UncertaintyAggregate:
    array = np.asarray(values, dtype=np.float64)
    mask = np.ones(array.shape, dtype=np.bool_) if valid is None else np.asarray(valid)
    array[~mask] = np.nan
    return UncertaintyAggregate(array, mask, ("term",), ())


def _classify(
    baseline: list[float],
    lower: list[float],
    central: list[float],
    upper: list[float],
    terrain: list[float],
    baseline_bound: list[float],
    terrain_bound: list[float],
    *,
    connectivity: list[bool] | None = None,
    connectivity_known: list[bool] | None = None,
    maximum: float | None = 10.0,
    scope: list[bool] | None = None,
    scope_known: list[bool] | None = None,
    supported: list[bool] | None = None,
):  # type: ignore[no-untyped-def]
    size = len(baseline)
    return reconcile_vertical_interval(
        np.asarray(baseline),
        np.asarray(lower),
        np.asarray(central),
        np.asarray(upper),
        np.asarray(terrain),
        _aggregate(baseline_bound),
        _aggregate(terrain_bound),
        coastal_scope=np.asarray(scope if scope is not None else [True] * size),
        coastal_scope_known=np.asarray(
            scope_known if scope_known is not None else [True] * size
        ),
        transform_supported=np.asarray(
            supported if supported is not None else [True] * size
        ),
        connectivity_passed=None if connectivity is None else np.asarray(connectivity),
        connectivity_known=(
            None if connectivity_known is None else np.asarray(connectivity_known)
        ),
        maximum_total_uncertainty_m=maximum,
    )


def test_interval_rule_distinguishes_confident_ambiguous_and_connectivity_states() -> None:
    result = _classify(
        baseline=[0, 0, 0, 0, 0],
        lower=[2, 0, 0, 2, 2],
        central=[2.5, 0.5, 1, 2.5, 2.5],
        upper=[3, 1, 2, 3, 3],
        terrain=[1, 2, 1, 1, 1],
        baseline_bound=[0.1] * 5,
        terrain_bound=[0.1] * 5,
        connectivity=[True, False, False, False, False],
        connectivity_known=[True, False, False, True, False],
    )

    np.testing.assert_array_equal(result.class_values, [1, 0, 255, 0, 255])
    np.testing.assert_array_equal(
        result.reason_codes,
        [
            ClassificationReason.NONE,
            ClassificationReason.NONE,
            ClassificationReason.UNCERTAIN_THRESHOLD,
            ClassificationReason.CONNECTIVITY_REJECTED,
            ClassificationReason.CONNECTIVITY_UNAVAILABLE,
        ],
    )


def test_exact_zero_lower_clearance_is_vertically_eligible() -> None:
    result = _classify(
        baseline=[0],
        lower=[1],
        central=[1],
        upper=[1],
        terrain=[1],
        baseline_bound=[0],
        terrain_bound=[0],
        connectivity=[True],
        connectivity_known=[True],
    )

    assert result.lower_clearance_m[0] == 0
    assert result.class_values[0] == 1


def test_missing_or_excessive_uncertainty_fails_closed() -> None:
    missing = _aggregate([0.1], [False])
    valid = _aggregate([0.1])
    common = dict(
        baseline_egm2008_m=np.array([0.0]),
        projection_lower_m=np.array([10.0]),
        projection_central_m=np.array([10.0]),
        projection_upper_m=np.array([10.0]),
        terrain_egm2008_m=np.array([0.0]),
        coastal_scope=np.array([True]),
        coastal_scope_known=np.array([True]),
        transform_supported=np.array([True]),
        connectivity_passed=np.array([True]),
        connectivity_known=np.array([True]),
    )

    missing_result = reconcile_vertical_interval(
        **common,
        baseline_uncertainty=missing,
        terrain_uncertainty=valid,
        maximum_total_uncertainty_m=10,
    )
    no_policy = reconcile_vertical_interval(
        **common,
        baseline_uncertainty=valid,
        terrain_uncertainty=valid,
        maximum_total_uncertainty_m=None,
    )
    excessive = reconcile_vertical_interval(
        **common,
        baseline_uncertainty=_aggregate([6.0]),
        terrain_uncertainty=_aggregate([5.0]),
        maximum_total_uncertainty_m=10,
    )

    assert missing_result.reason_codes[0] == ClassificationReason.MISSING_UNCERTAINTY_BOUND
    assert no_policy.reason_codes[0] == ClassificationReason.UNCERTAINTY_POLICY_UNAVAILABLE
    assert excessive.reason_codes[0] == ClassificationReason.EXCESSIVE_UNCERTAINTY
    assert all(item.class_values[0] == 255 for item in (missing_result, no_policy, excessive))


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"scope_known": [False]}, ClassificationReason.COASTAL_SCOPE_UNAVAILABLE),
        ({"scope": [False]}, ClassificationReason.OUTSIDE_COASTAL_SCOPE),
        ({"supported": [False]}, ClassificationReason.TRANSFORM_OUT_OF_COVERAGE),
        ({"baseline": [np.nan]}, ClassificationReason.SOURCE_NODATA),
    ],
)
def test_scope_coverage_and_nodata_have_stable_reasons(
    changes: dict[str, Any], reason: ClassificationReason
) -> None:
    arguments: dict[str, Any] = {
        "baseline": [0.0],
        "lower": [2.0],
        "central": [2.0],
        "upper": [2.0],
        "terrain": [0.0],
        "baseline_bound": [0.1],
        "terrain_bound": [0.1],
        "connectivity": [True],
        "connectivity_known": [True],
    }
    arguments.update(changes)

    result = _classify(**arguments)

    assert result.class_values[0] == 255
    assert result.reason_codes[0] == reason


def test_common_vertical_shift_leaves_clearance_and_class_unchanged() -> None:
    original = _classify(
        [1],
        [2],
        [2.5],
        [3],
        [1],
        [0.2],
        [0.2],
        connectivity=[True],
        connectivity_known=[True],
    )
    shifted = _classify(
        [101],
        [2],
        [2.5],
        [3],
        [101],
        [0.2],
        [0.2],
        connectivity=[True],
        connectivity_known=[True],
    )

    np.testing.assert_allclose(
        original.lower_clearance_m, shifted.lower_clearance_m, rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        original.upper_clearance_m, shifted.upper_clearance_m, rtol=0, atol=1e-12
    )
    np.testing.assert_array_equal(original.class_values, shifted.class_values)


def test_widening_bounds_can_demote_but_cannot_flip_confident_class() -> None:
    narrow = _classify(
        [0],
        [2],
        [2.5],
        [3],
        [1],
        [0.1],
        [0.1],
        connectivity=[True],
        connectivity_known=[True],
    )
    wide = _classify(
        [0],
        [2],
        [2.5],
        [3],
        [1],
        [0.6],
        [0.6],
        connectivity=[True],
        connectivity_known=[True],
    )

    assert narrow.class_values[0] == 1
    assert wide.class_values[0] == 255
    assert wide.reason_codes[0] == ClassificationReason.UNCERTAIN_THRESHOLD


def test_non_monotonic_projection_interval_is_rejected() -> None:
    with pytest.raises(ScienceContractError, match="not monotonic"):
        _classify(
            [0],
            [2],
            [1],
            [3],
            [0],
            [0],
            [0],
            connectivity=[True],
            connectivity_known=[True],
        )
