"""Tests for exact AR6 schema selection and source-native interpolation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr

from searise_pipeline.science import (
    ScienceContractError,
    bilinear_sample,
    extract_projection_grid,
    load_science_contracts,
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
    values[1, 1, :] = np.array([999, 1000, 2000, 3000, 4000, 5000, 6000])
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
            "quantiles": np.array([0.17, 0.5, 0.83], dtype=np.float32),
            "years": np.array([2030, 2050, 2100]),
            "locations": locations,
        },
    )


def test_exact_mapping_reconstructs_complete_grid_in_metres() -> None:
    grid = extract_projection_grid(_dataset(), _projection(), "ssp2-45", 2050)

    np.testing.assert_array_equal(grid.latitudes, [0, 1])
    np.testing.assert_array_equal(grid.longitudes, [-1, 0, 1])
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
