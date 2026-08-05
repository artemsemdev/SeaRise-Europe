"""Tests for the locked 1995-2014 baseline reconstruction."""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.science import (
    MonthlySlaField,
    ScienceContractError,
    load_science_contracts,
    reconstruct_baseline_surface,
)

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src/pipeline/science"
MANIFEST = (
    REPO_ROOT
    / "src/pipeline/sources/manifests/cmems-eur-monthly-sla-1995-2014-v202411.jsonl.gz"
)


def _three_month_contract() -> dict[str, object]:
    contract = deepcopy(
        load_science_contracts(CONTRACT_DIR).source_semantics["verticalInputs"]["baseline"]
    )
    contract["referencePeriod"] = {
        "startInclusive": "2000-01-01",
        "endExclusive": "2000-04-01",
    }
    contract["monthlyObjectCount"] = 3
    contract["calendarDayWeight"] = 91
    return contract


def _field(start: date, end: date, values: list[float]) -> MonthlySlaField:
    return MonthlySlaField(start, end, np.asarray(values, dtype=np.float64))


def test_baseline_uses_calendar_days_and_static_mdt() -> None:
    fields = [
        _field(date(2000, 1, 1), date(2000, 2, 1), [1.0, 10.0]),
        _field(date(2000, 2, 1), date(2000, 3, 1), [2.0, 20.0]),
        _field(date(2000, 3, 1), date(2000, 4, 1), [3.0, 30.0]),
    ]

    result = reconstruct_baseline_surface(
        fields, np.array([0.5, -0.5]), _three_month_contract()
    )

    expected = np.array(
        [(31 * 1 + 29 * 2 + 31 * 3) / 91 + 0.5, (31 * 10 + 29 * 20 + 31 * 30) / 91 - 0.5]
    )
    np.testing.assert_allclose(result.values_m, expected)
    assert result.interval_count == 3
    assert result.calendar_day_weight == 91


def test_missing_cell_or_non_water_cell_propagates_to_nodata() -> None:
    fields = [
        _field(date(2000, 1, 1), date(2000, 2, 1), [1.0, 1.0, 1.0]),
        _field(date(2000, 2, 1), date(2000, 3, 1), [2.0, np.nan, 2.0]),
        _field(date(2000, 3, 1), date(2000, 4, 1), [3.0, 3.0, 3.0]),
    ]

    result = reconstruct_baseline_surface(
        fields,
        np.zeros(3),
        _three_month_contract(),
        water_mask=np.array([True, True, False]),
    )

    assert np.isfinite(result.values_m[0])
    assert np.isnan(result.values_m[1:]).all()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda fields: fields.pop(),
        lambda fields: fields.__setitem__(
            1, _field(date(2000, 3, 1), date(2000, 4, 1), [2.0])
        ),
        lambda fields: fields.__setitem__(
            1, _field(date(2000, 2, 1), date(2000, 4, 1), [2.0])
        ),
    ],
)
def test_missing_duplicate_or_non_monthly_intervals_fail_closed(mutation: object) -> None:
    fields = [
        _field(date(2000, 1, 1), date(2000, 2, 1), [1.0]),
        _field(date(2000, 2, 1), date(2000, 3, 1), [2.0]),
        _field(date(2000, 3, 1), date(2000, 4, 1), [3.0]),
    ]
    mutation(fields)  # type: ignore[operator]

    with pytest.raises(ScienceContractError, match="interval"):
        reconstruct_baseline_surface(fields, np.zeros(1), _three_month_contract())


def test_pinned_manifest_drives_all_240_months_and_7305_days() -> None:
    records = [
        json.loads(line)
        for line in gzip.decompress(MANIFEST.read_bytes()).decode("utf-8").splitlines()
    ]
    fields = [
        _field(
            date.fromisoformat(row["periodStart"]),
            date.fromisoformat(row["periodEndExclusive"]),
            [1.0],
        )
        for row in records[1:]
    ]
    contract = load_science_contracts(CONTRACT_DIR).source_semantics["verticalInputs"][
        "baseline"
    ]

    result = reconstruct_baseline_surface(fields, np.array([0.25]), contract)

    np.testing.assert_array_equal(result.values_m, [1.25])
    assert result.interval_count == 240
    assert result.calendar_day_weight == 7305
