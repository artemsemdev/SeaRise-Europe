"""Tests for conservative non-projection uncertainty aggregation."""

from __future__ import annotations

import numpy as np
import pytest

from searise_pipeline.science import (
    ScienceContractError,
    UncertaintyTerm,
    aggregate_absolute_bounds,
)


def _term(term_id: str, values: list[float] | None) -> UncertaintyTerm:
    return UncertaintyTerm(
        id=term_id,
        component="baseline",
        bound_m=None if values is None else np.asarray(values, dtype=np.float64),
        units="m",
        provenance=f"locked:{term_id}",
        spatial_handling="per-cell-absolute-bound",
    )


def test_required_bounds_sum_without_independence_assumption() -> None:
    result = aggregate_absolute_bounds(
        [_term("mapping", [0.1, 0.2]), _term("geoid", [0.3, 0.4])],
        ("mapping", "geoid"),
        (2,),
    )

    np.testing.assert_allclose(result.values_m, [0.4, 0.6])
    np.testing.assert_array_equal(result.valid, [True, True])
    assert result.missing_term_ids == ()


def test_missing_term_or_cell_never_defaults_to_zero() -> None:
    missing_term = aggregate_absolute_bounds(
        [_term("mapping", [0.1, 0.2])], ("mapping", "geoid"), (2,)
    )
    missing_cell = aggregate_absolute_bounds(
        [_term("mapping", [0.1, np.nan])], ("mapping",), (2,)
    )

    assert np.isnan(missing_term.values_m).all()
    assert missing_term.missing_term_ids == ("geoid",)
    assert np.isnan(missing_cell.values_m[1])
    assert not missing_cell.valid[1]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda term: UncertaintyTerm(**{**term.__dict__, "units": "cm"}), "semantics"),
        (
            lambda term: UncertaintyTerm(**{**term.__dict__, "provenance": ""}),
            "semantics",
        ),
        (lambda term: _term(term.id, [-0.1, 0.2]), "negative"),
    ],
)
def test_invalid_uncertainty_semantics_fail_closed(mutation, message: str) -> None:  # type: ignore[no-untyped-def]
    term = mutation(_term("mapping", [0.1, 0.2]))

    with pytest.raises(ScienceContractError, match=message):
        aggregate_absolute_bounds([term], ("mapping",), (2,))
