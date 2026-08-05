"""Tests for verified AR6 archive reads and source-native point lookup."""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr
from shapely.geometry import box

from searise_pipeline.science import (
    Ar6GridSlice,
    Ar6ProjectionInterval,
    ScienceContractError,
    lookup_ar6_projection,
    open_verified_ar6_member,
    verify_ar6_archive,
)

SCIENCE_DIR = Path(__file__).parents[2] / "science"
MEMBER_PATHS = {
    "ssp126": (
        "ar6-regional-confidence/regional/confidence_output_files/"
        "medium_confidence/ssp126/total_ssp126_medium_confidence_values.nc"
    ),
    "ssp245": (
        "ar6-regional-confidence/regional/confidence_output_files/"
        "medium_confidence/ssp245/total_ssp245_medium_confidence_values.nc"
    ),
    "ssp585": (
        "ar6-regional-confidence/regional/confidence_output_files/"
        "medium_confidence/ssp585/total_ssp585_medium_confidence_values.nc"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    member_path = tmp_path / "member.nc"
    xr.Dataset(
        data_vars={
            "sea_level_change": (
                ("quantiles", "years", "locations"),
                np.array([[[100]], [[200]], [[300]]], dtype=np.int16),
                {"units": "mm", "_FillValue": -32768},
            ),
            "lat": (("locations",), [0.0], {"units": "Degrees North"}),
            "lon": (("locations",), [0.0], {"units": "Degrees East"}),
        },
        coords={
            "quantiles": [0.167, 0.5, 0.833],
            "years": [2050],
            "locations": [1000000000],
        },
    ).to_netcdf(member_path, engine="netcdf4")
    member_sha256 = _sha256(member_path)
    archive_path = tmp_path / "ar6.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(member_path, MEMBER_PATHS["ssp245"])
    archive_sha256 = _sha256(archive_path)

    projection = deepcopy(
        json.loads((SCIENCE_DIR / "source-semantics.json").read_text())["projection"]
    )
    projection["archive"].update(
        {"byteSize": archive_path.stat().st_size, "sha256": archive_sha256}
    )
    source_lock = {
        "sources": [
            {
                "id": projection["sourceId"],
                "version": projection["version"],
                "assets": [
                    {
                        "byteSize": archive_path.stat().st_size,
                        "sha256": archive_sha256,
                        "members": [
                            {
                                "scenario": upstream,
                                "path": MEMBER_PATHS[upstream],
                                "byteSize": member_path.stat().st_size,
                                "sha256": member_sha256,
                            }
                            for upstream in ("ssp126", "ssp245", "ssp585")
                        ],
                    }
                ],
            }
        ]
    }
    return archive_path, source_lock, projection


def _contract() -> dict[str, Any]:
    return json.loads((SCIENCE_DIR / "ar6-lookup-validation.json").read_text())


def _slice(
    values: list[list[float]],
    *,
    latitudes: list[float] | None = None,
    longitudes: list[float] | None = None,
    location_ids: list[list[int]] | None = None,
) -> Ar6GridSlice:
    return Ar6GridSlice(
        latitudes=np.asarray(latitudes if latitudes is not None else [0.0]),
        longitudes=np.asarray(longitudes if longitudes is not None else [-0.5, 0.5]),
        location_ids=np.asarray(location_ids if location_ids is not None else [[20, 10]]),
        values_m=np.asarray(values, dtype=np.float64),
    )


def _interval(
    lower: list[list[float]],
    central: list[list[float]],
    upper: list[list[float]],
    **kwargs: Any,
) -> Ar6ProjectionInterval:
    return Ar6ProjectionInterval(
        _slice(lower, **kwargs),
        _slice(central, **kwargs),
        _slice(upper, **kwargs),
    )


def _lookup(interval: Ar6ProjectionInterval, latitude: float, longitude: float):
    return lookup_ar6_projection(
        interval,
        latitude=latitude,
        longitude=longitude,
        scenario="ssp2-45",
        horizon=2050,
        baseline="1995-2014 mean",
        support=box(-180, -90, 180, 90),
        coastal_scope=box(-180, -90, 180, 90),
        lookup_contract=_contract(),
    )


def test_archive_and_member_hashes_are_verified_before_dataset_is_opened(
    tmp_path: Path,
) -> None:
    archive_path, source_lock, projection = _archive_fixture(tmp_path)

    verified = verify_ar6_archive(archive_path, source_lock, projection)
    with open_verified_ar6_member(verified, "ssp2-45") as (dataset, identity):
        assert dataset.sizes == {"quantiles": 3, "years": 1, "locations": 1}
        assert identity.sha256 == source_lock["sources"][0]["assets"][0]["members"][1]["sha256"]


def test_archive_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    archive_path, source_lock, projection = _archive_fixture(tmp_path)
    archive_path.write_bytes(archive_path.read_bytes()[:-1] + b"x")

    with pytest.raises(ScienceContractError, match="archive SHA-256"):
        verify_ar6_archive(archive_path, source_lock, projection)


def test_member_hash_mismatch_fails_before_netcdf_read(tmp_path: Path) -> None:
    archive_path, source_lock, projection = _archive_fixture(tmp_path)
    source_lock["sources"][0]["assets"][0]["members"][1]["sha256"] = "0" * 64

    verified = verify_ar6_archive(archive_path, source_lock, projection)
    with pytest.raises(ScienceContractError, match="member SHA-256"):
        with open_verified_ar6_member(verified, "ssp2-45"):
            pytest.fail("unverified member was opened")


def test_lookup_uses_lowest_location_id_for_an_exact_distance_tie() -> None:
    interval = _interval([[0.1, 0.2]], [[0.3, 0.4]], [[0.5, 0.6]])

    result = _lookup(interval, 0.0, 0.0)

    assert result.state == "ProjectionAvailable"
    assert result.reason_code == "projection-available"
    assert (result.lower_m, result.central_m, result.upper_m) == (0.2, 0.4, 0.6)
    assert result.source is not None
    assert result.source.location_id == 10
    assert result.source.family == "grid"


def test_lookup_does_not_skip_a_nearest_nodata_location() -> None:
    interval = _interval([[np.nan, 0.2]], [[np.nan, 0.4]], [[np.nan, 0.6]])

    result = _lookup(interval, 0.0, -0.49)

    assert result.state == "DataUnavailable"
    assert result.reason_code == "source-value-nodata"
    assert result.source is not None
    assert result.source.location_id == 20
    assert result.central_m is None


def test_maximum_distance_is_inclusive_and_then_fails_closed() -> None:
    radius = _contract()["lookup"]["distance"]["earthMeanRadiusKm"]
    boundary_latitude = math.degrees(100 / radius)
    interval = _interval(
        [[0.1]],
        [[0.2]],
        [[0.3]],
        longitudes=[0.0],
        location_ids=[[1]],
    )

    at_boundary = _lookup(interval, boundary_latitude, 0.0)
    beyond_boundary = _lookup(interval, math.degrees(100.001 / radius), 0.0)

    assert at_boundary.state == "ProjectionAvailable"
    assert at_boundary.source is not None
    assert at_boundary.source.distance_km == 100
    assert beyond_boundary.state == "DataUnavailable"
    assert beyond_boundary.reason_code == "source-location-too-distant"


def test_geography_states_are_resolved_before_source_lookup() -> None:
    interval = _interval([[0.1, 0.2]], [[0.3, 0.4]], [[0.5, 0.6]])
    contract = _contract()

    unsupported = lookup_ar6_projection(
        interval,
        latitude=5,
        longitude=5,
        scenario="ssp2-45",
        horizon=2050,
        baseline="1995-2014 mean",
        support=box(-2, -2, 2, 2),
        coastal_scope=box(-1, -1, 1, 1),
        lookup_contract=contract,
    )
    out_of_scope = lookup_ar6_projection(
        interval,
        latitude=1.5,
        longitude=0,
        scenario="ssp2-45",
        horizon=2050,
        baseline="1995-2014 mean",
        support=box(-2, -2, 2, 2),
        coastal_scope=box(-1, -1, 1, 1),
        lookup_contract=contract,
    )

    assert (unsupported.state, unsupported.reason_code, unsupported.source) == (
        "UnsupportedGeography",
        "outside-europe-support",
        None,
    )
    assert (out_of_scope.state, out_of_scope.reason_code, out_of_scope.source) == (
        "OutOfScope",
        "outside-coastal-scope",
        None,
    )
