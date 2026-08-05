"""Tests for exact AR6 schema selection and source-native interpolation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr

from searise_pipeline.science import (
    Ar6MemberIdentity,
    ScienceContractError,
    bilinear_sample,
    extract_projection_grid,
    extract_projection_interval,
    load_science_contracts,
    projection_member_identity,
    validate_ar6_schema,
)

CONTRACT_DIR = Path(__file__).parents[2] / "science"


def _projection() -> dict[str, Any]:
    contracts = load_science_contracts(CONTRACT_DIR)
    projection = deepcopy(contracts.source_semantics["projection"])
    projection["mapping"]["expectedSizes"] = {
        "quantiles": 3,
        "years": 3,
        "locations": 7,
    }
    projection["nativeCoordinates"].update(
        {
            "locationCount": 6,
            "latitudeCount": 2,
            "longitudeCount": 3,
            "longitudeRange": [-1, 1],
        }
    )
    return projection


def _dataset() -> xr.Dataset:
    locations = np.array(
        [1, 1000000000, 1000000010, 1000000020, 1000010000, 1000010010, 1000010020]
    )
    latitudes = np.array([0, 0, 0, 0, 1, 1, 1], dtype=np.float32)
    longitudes = np.array([0, -1, 0, 1, -1, 0, 1], dtype=np.float32)
    values = np.zeros((3, 3, 7), dtype=np.int16)
    values[0, 1, :] = np.array([999, 500, 1500, 2500, 3500, 4500, 5500])
    values[1, 1, :] = np.array([999, 1000, 2000, 3000, 4000, 5000, 6000])
    values[2, 1, :] = np.array([999, 1500, 2500, 3500, 4500, 5500, 6500])
    return xr.Dataset(
        data_vars={
            "sea_level_change": (
                ("quantiles", "years", "locations"),
                values,
                {"units": "mm", "_FillValue": -32768},
            ),
            "lat": (("locations",), latitudes, {"units": "Degrees North"}),
            "lon": (("locations",), longitudes, {"units": "Degrees East"}),
        },
        coords={
            "quantiles": np.array([0.167, 0.5, 0.833], dtype=np.float64),
            "years": np.array([2030, 2050, 2100]),
            "locations": locations,
        },
    )


def _member(scenario: str = "ssp2-45") -> Ar6MemberIdentity:
    return Ar6MemberIdentity(scenario, "a" * 64, "member.nc", 123, "b" * 64)


def _interval(dataset: xr.Dataset, scenario: str = "ssp2-45"):
    projection = _projection()
    projection["archive"]["sha256"] = "a" * 64
    member = _member(scenario)
    return extract_projection_interval(
        dataset,
        projection,
        scenario,
        2050,
        member_identity=member,
        verified_member_sha256=member.sha256,
    )


def test_exact_mapping_reconstructs_complete_grid_in_metres() -> None:
    grid = extract_projection_grid(_dataset(), _projection(), "ssp2-45", 2050)

    np.testing.assert_array_equal(grid.latitudes, [0, 1])
    np.testing.assert_array_equal(grid.longitudes, [-1, 0, 1])
    np.testing.assert_array_equal(
        grid.location_ids,
        [[1000000000, 1000000010, 1000000020], [1000010000, 1000010010, 1000010020]],
    )
    np.testing.assert_allclose(grid.values_m, [[1, 2, 3], [4, 5, 6]])


def test_bilinear_sampling_preserves_nodes_and_has_no_extrapolation() -> None:
    grid = extract_projection_grid(_dataset(), _projection(), "ssp2-45", 2050)

    sampled = bilinear_sample(
        grid,
        np.array([0.0, 0.5, 2.0]),
        np.array([-1.0, -0.5, 0.0]),
    )

    np.testing.assert_allclose(sampled[:2], [1.0, 3.0])
    assert np.isnan(sampled[2])


def test_bilinear_sampling_does_not_bridge_nodata() -> None:
    dataset = _dataset()
    dataset["sea_level_change"].values[1, 1, 1] = -32768
    grid = extract_projection_grid(dataset, _projection(), "ssp2-45", 2050)

    sampled = bilinear_sample(grid, np.array([0.5]), np.array([-0.5]))

    assert np.isnan(sampled[0])


def test_exact_likely_interval_uses_source_quantiles_without_rounding() -> None:
    interval = _interval(_dataset())

    np.testing.assert_allclose(interval.lower.values_m[0], [0.5, 1.5, 2.5])
    np.testing.assert_allclose(interval.central.values_m[0], [1.0, 2.0, 3.0])
    np.testing.assert_allclose(interval.upper.values_m[0], [1.5, 2.5, 3.5])


def test_human_quantile_label_is_not_accepted_as_source_coordinate() -> None:
    dataset = _dataset().assign_coords(quantiles=[0.17, 0.5, 0.833])

    with pytest.raises(ScienceContractError, match="0.167"):
        _interval(dataset)


def test_non_monotonic_projection_interval_fails_closed() -> None:
    dataset = _dataset()
    dataset["sea_level_change"].values[0, 1, 1] = 2000

    with pytest.raises(ScienceContractError, match="not monotonic"):
        _interval(dataset)


def test_member_identity_binds_scenario_archive_and_verified_bytes() -> None:
    contracts = load_science_contracts(CONTRACT_DIR)
    source_lock = json.loads(
        (CONTRACT_DIR.parent / "sources/source-lock.json").read_text(encoding="utf-8")
    )
    identity = projection_member_identity(
        source_lock, contracts.source_semantics["projection"], "ssp2-45"
    )

    assert identity.path.endswith("total_ssp245_medium_confidence_values.nc")
    assert identity.sha256 == "3f31aadb53b7962a729a839cd58e841f171e72575f9e2b802399be6656aa8cb8"

    with pytest.raises(ScienceContractError, match="SHA-256"):
        extract_projection_interval(
            _dataset(),
            {**_projection(), "archive": {"sha256": identity.archive_sha256}},
            "ssp2-45",
            2050,
            member_identity=identity,
            verified_member_sha256="0" * 64,
        )

    with pytest.raises(ScienceContractError, match="requested scenario"):
        extract_projection_interval(
            _dataset(),
            {**_projection(), "archive": {"sha256": "a" * 64}},
            "ssp5-85",
            2050,
            member_identity=_member("ssp2-45"),
            verified_member_sha256="b" * 64,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda dataset: dataset["sea_level_change"].attrs.update(units="m"), "value units"),
        (lambda dataset: dataset["lat"].attrs.update(units="degrees_north"), "latitude units"),
        (lambda dataset: dataset["sea_level_change"].attrs.pop("_FillValue"), "fill value"),
    ],
)
def test_unexpected_source_semantics_fail_closed(mutation: Any, message: str) -> None:
    dataset = _dataset()
    mutation(dataset)

    with pytest.raises(ScienceContractError, match=message):
        validate_ar6_schema(dataset, _projection())


def test_nearest_year_selection_is_forbidden() -> None:
    dataset = _dataset().assign_coords(years=[2030, 2040, 2100])

    with pytest.raises(ScienceContractError, match="absent from source"):
        extract_projection_grid(dataset, _projection(), "ssp2-45", 2050)
