"""Deterministic reconstruction of the 1995-2014 mean water surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from .contracts import ScienceContractError


@dataclass(frozen=True)
class MonthlySlaField:
    """One complete source month of simple-mean SLA values in metres."""

    period_start: date
    period_end_exclusive: date
    values_m: NDArray[np.float64]
    units: str = "m"


@dataclass(frozen=True)
class BaselineSurface:
    """Day-weighted SLA plus static MDT on the common source grid."""

    values_m: NDArray[np.float64]
    interval_count: int
    calendar_day_weight: int
    reference_start: date
    reference_end_exclusive: date


def _next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _parse_date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ScienceContractError(f"Invalid baseline {label}: {value!r}") from exc


def reconstruct_baseline_surface(
    monthly_sla: Sequence[MonthlySlaField],
    mdt_m: NDArray[np.floating[Any]],
    baseline_contract: Mapping[str, Any],
    *,
    water_mask: NDArray[np.bool_] | None = None,
) -> BaselineSurface:
    """Return the exact calendar-day-weighted SLA mean plus static MDT.

    Missing source intervals are a source-contract failure. Missing values in
    any required monthly field, MDT, or water mask propagate to nodata for the
    affected cell; they are never filled from neighbouring cells.
    """
    reference = baseline_contract["referencePeriod"]
    expected_start = _parse_date(reference["startInclusive"], "reference start")
    expected_end = _parse_date(reference["endExclusive"], "reference end")
    expected_count = int(baseline_contract["monthlyObjectCount"])
    expected_days = int(baseline_contract["calendarDayWeight"])
    if len(monthly_sla) != expected_count:
        raise ScienceContractError(
            f"Baseline needs {expected_count} monthly intervals, got {len(monthly_sla)}"
        )

    mdt = np.asarray(mdt_m, dtype=np.float64)
    if mdt.ndim < 1:
        raise ScienceContractError("Baseline MDT must be an array")
    if water_mask is not None and np.asarray(water_mask).shape != mdt.shape:
        raise ScienceContractError("Baseline water mask does not match MDT shape")

    weighted_sum = np.zeros(mdt.shape, dtype=np.float64)
    compensation = np.zeros(mdt.shape, dtype=np.float64)
    complete = np.isfinite(mdt)
    cursor = expected_start
    total_days = 0
    for index, field in enumerate(monthly_sla):
        if field.units != "m":
            raise ScienceContractError(f"Baseline interval {index} units are not metres")
        if field.period_start != cursor:
            raise ScienceContractError(
                f"Baseline interval {index} is missing, duplicated, or unordered"
            )
        expected_interval_end = _next_month(cursor)
        if field.period_end_exclusive != expected_interval_end:
            raise ScienceContractError(f"Baseline interval {index} is not one calendar month")
        values = np.asarray(field.values_m, dtype=np.float64)
        if values.shape != mdt.shape:
            raise ScienceContractError(f"Baseline interval {index} does not match MDT shape")
        day_weight = (expected_interval_end - cursor).days
        finite = np.isfinite(values)
        complete &= finite

        # Kahan accumulation keeps the fixed source order stable without
        # depending on BLAS reduction order.
        weighted = np.where(finite, values * day_weight, 0.0)
        adjusted = weighted - compensation
        updated = weighted_sum + adjusted
        compensation = (updated - weighted_sum) - adjusted
        weighted_sum = updated
        total_days += day_weight
        cursor = expected_interval_end

    if cursor != expected_end or total_days != expected_days:
        raise ScienceContractError(
            "Baseline intervals do not cover the locked reference period and day weight"
        )
    if water_mask is not None:
        complete &= np.asarray(water_mask, dtype=np.bool_)

    values = weighted_sum / float(total_days) + mdt
    values[~complete] = np.nan
    return BaselineSurface(
        values_m=values,
        interval_count=len(monthly_sla),
        calendar_day_weight=total_days,
        reference_start=expected_start,
        reference_end_exclusive=expected_end,
    )
