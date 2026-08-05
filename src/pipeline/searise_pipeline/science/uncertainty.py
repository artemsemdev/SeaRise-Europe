"""Explicit conservative uncertainty terms for vertical reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from .contracts import ScienceContractError


@dataclass(frozen=True)
class UncertaintyTerm:
    """One absolute error bound with auditable semantics."""

    id: str
    component: str
    bound_m: NDArray[np.float64] | None
    units: str
    provenance: str
    spatial_handling: str
    aggregation_rule: str = "sum-absolute-bounds"


@dataclass(frozen=True)
class UncertaintyAggregate:
    """Conservative sum and per-cell completeness of required bounds."""

    values_m: NDArray[np.float64]
    valid: NDArray[np.bool_]
    term_ids: tuple[str, ...]
    missing_term_ids: tuple[str, ...]


def aggregate_absolute_bounds(
    terms: Sequence[UncertaintyTerm],
    required_ids: Sequence[str],
    shape: tuple[int, ...],
) -> UncertaintyAggregate:
    """Sum complete non-negative metre bounds without independence claims."""
    required = tuple(required_ids)
    if len(set(required)) != len(required):
        raise ScienceContractError("Required uncertainty term ids are duplicated")
    by_id = {term.id: term for term in terms}
    if len(by_id) != len(terms):
        raise ScienceContractError("Uncertainty term ids are duplicated")
    unexpected = set(by_id) - set(required)
    if unexpected:
        raise ScienceContractError(f"Unexpected uncertainty terms: {sorted(unexpected)}")

    values = np.zeros(shape, dtype=np.float64)
    valid = np.ones(shape, dtype=np.bool_)
    missing_ids: list[str] = []
    for term_id in required:
        term = by_id.get(term_id)
        if term is None or term.bound_m is None:
            valid[:] = False
            missing_ids.append(term_id)
            continue
        if (
            term.units != "m"
            or not term.provenance
            or not term.spatial_handling
            or term.aggregation_rule != "sum-absolute-bounds"
        ):
            raise ScienceContractError(f"Uncertainty term {term_id} has incomplete semantics")
        bound = np.asarray(term.bound_m, dtype=np.float64)
        if bound.shape != shape:
            raise ScienceContractError(f"Uncertainty term {term_id} has the wrong shape")
        finite = np.isfinite(bound)
        if np.any(finite & (bound < 0)):
            raise ScienceContractError(f"Uncertainty term {term_id} has a negative bound")
        valid &= finite
        values += np.where(finite, bound, 0.0)

    values[~valid] = np.nan
    return UncertaintyAggregate(
        values_m=values,
        valid=valid,
        term_ids=required,
        missing_term_ids=tuple(missing_ids),
    )
