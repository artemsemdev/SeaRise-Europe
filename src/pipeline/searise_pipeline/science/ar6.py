"""Inspect and transform the exact IPCC AR6 20210809 regional schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import xarray as xr
from numpy.typing import NDArray

from .contracts import ScienceContractError


@dataclass(frozen=True)
class Ar6GridSlice:
    """One AR6 statistic reshaped from locations onto its explicit native grid."""

    latitudes: NDArray[np.float64]
    longitudes: NDArray[np.float64]
    location_ids: NDArray[np.int64]
    values_m: NDArray[np.float64]


@dataclass(frozen=True)
class Ar6ProjectionInterval:
    """Exact lower, central, and upper AR6 projection grids."""

    scenario: str
    horizon: int
    baseline: str
    source_release: str
    member_sha256: str
    lower: Ar6GridSlice
    central: Ar6GridSlice
    upper: Ar6GridSlice


@dataclass(frozen=True)
class Ar6MemberIdentity:
    """Scenario-specific member locked inside the exact AR6 archive."""

    scenario: str
    archive_sha256: str
    path: str
    byte_size: int
    sha256: str


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ScienceContractError(f"Unexpected AR6 {label}: {actual!r} != {expected!r}")


def _fill_value(variable: xr.DataArray) -> Any:
    return variable.encoding.get("_FillValue", variable.attrs.get("_FillValue"))


def validate_ar6_schema(dataset: xr.Dataset, projection: Mapping[str, Any]) -> None:
    """Reject any projection dataset that differs from the binding mapping."""
    mapping = projection["mapping"]
    coordinates = mapping["coordinates"]
    variable_name = mapping["variable"]
    required_variables = {
        variable_name,
        coordinates["latitude"],
        coordinates["longitude"],
    }
    available_variables = set(dataset.data_vars) | set(dataset.coords)
    missing = required_variables - available_variables
    if missing:
        raise ScienceContractError(f"Missing AR6 variables: {sorted(missing)}")

    variable = dataset[variable_name]
    _require_equal(list(variable.dims), mapping["dimensions"], "dimension order")
    for dimension, expected_size in mapping["expectedSizes"].items():
        _require_equal(dataset.sizes.get(dimension), expected_size, f"{dimension} size")

    locations_name = coordinates["locations"]
    for role in ("latitude", "longitude"):
        coordinate = dataset[coordinates[role]]
        _require_equal(coordinate.dims, (locations_name,), f"{role} dimensions")
        _require_equal(
            coordinate.attrs.get("units"),
            mapping["coordinateUnits"][role],
            f"{role} units",
        )

    _require_equal(variable.attrs.get("units"), mapping["units"], "value units")
    fill_value = _fill_value(variable)
    if fill_value is None:
        raise ScienceContractError("Unexpected AR6 fill value: missing")
    _require_equal(float(fill_value), float(mapping["fillValue"]), "fill value")


def extract_projection_grid(
    dataset: xr.Dataset,
    projection: Mapping[str, Any],
    scenario: str,
    year: int,
    *,
    quantile: float | None = None,
) -> Ar6GridSlice:
    """Select the exact approved statistic and reshape explicit grid locations."""
    validate_ar6_schema(dataset, projection)
    mapping = projection["mapping"]
    if scenario not in mapping["scenarios"]:
        raise ScienceContractError(f"Unsupported AR6 scenario: {scenario}")
    if year not in mapping["years"]:
        raise ScienceContractError(f"Unsupported AR6 horizon: {year}")

    coordinates = mapping["coordinates"]
    year_values = np.asarray(dataset[coordinates["years"]].values)
    quantile_values = np.asarray(dataset[coordinates["quantiles"]].values)
    selected_quantile = (
        mapping["statistic"]["quantile"] if quantile is None else quantile
    )
    if year not in year_values:
        raise ScienceContractError(f"AR6 horizon is absent from source: {year}")
    if np.count_nonzero(year_values == year) != 1:
        raise ScienceContractError(f"AR6 horizon is not uniquely present: {year}")
    if np.count_nonzero(quantile_values == selected_quantile) != 1:
        raise ScienceContractError(
            f"AR6 quantile is not uniquely present in source: {selected_quantile}"
        )

    location_ids = np.asarray(dataset[coordinates["locations"]].values)
    grid_rule = projection["nativeCoordinates"]
    selected = location_ids >= grid_rule["locationIdMinimum"]
    _require_equal(int(selected.sum()), grid_rule["locationCount"], "grid location count")

    source_lats = np.asarray(dataset[coordinates["latitude"]].values, dtype=np.float64)[
        selected
    ]
    source_lons = np.asarray(dataset[coordinates["longitude"]].values, dtype=np.float64)[
        selected
    ]
    latitudes = np.unique(source_lats)
    longitudes = np.unique(source_lons)
    _require_equal(latitudes.size, grid_rule["latitudeCount"], "latitude count")
    _require_equal(longitudes.size, grid_rule["longitudeCount"], "longitude count")
    _require_equal(
        [float(longitudes[0]), float(longitudes[-1])],
        [float(item) for item in grid_rule["longitudeRange"]],
        "longitude range",
    )
    if not np.all(np.diff(latitudes) == 1) or not np.all(np.diff(longitudes) == 1):
        raise ScienceContractError("AR6 native grid is not spaced at exactly one degree")
    if len(set(zip(source_lats, source_lons))) != grid_rule["locationCount"]:
        raise ScienceContractError("AR6 native grid contains duplicate coordinates")
    if latitudes.size * longitudes.size != grid_rule["locationCount"]:
        raise ScienceContractError("AR6 native grid is not a complete latitude/longitude product")

    selected_values = (
        dataset[mapping["variable"]]
        .sel(
            {
                coordinates["years"]: year,
                coordinates["quantiles"]: selected_quantile,
            }
        )
        .values[selected]
    )
    values = np.asarray(selected_values, dtype=np.float64)
    values[values == mapping["fillValue"]] = np.nan
    values *= mapping["unitToMetres"]

    lat_index = np.searchsorted(latitudes, source_lats)
    lon_index = np.searchsorted(longitudes, source_lons)
    location_grid = np.full((latitudes.size, longitudes.size), -1, dtype=np.int64)
    grid = np.full((latitudes.size, longitudes.size), np.nan, dtype=np.float64)
    location_grid[lat_index, lon_index] = np.asarray(location_ids[selected], dtype=np.int64)
    grid[lat_index, lon_index] = values
    if np.any(location_grid < 0):
        raise ScienceContractError("AR6 native grid is missing source location identities")
    return Ar6GridSlice(
        latitudes=latitudes,
        longitudes=longitudes,
        location_ids=location_grid,
        values_m=grid,
    )


def extract_projection_interval(
    dataset: xr.Dataset,
    projection: Mapping[str, Any],
    scenario: str,
    year: int,
    *,
    member_identity: Ar6MemberIdentity,
    verified_member_sha256: str,
) -> Ar6ProjectionInterval:
    """Select the exact 0.167/0.5/0.833 likely interval without fallback."""
    if member_identity.scenario != scenario:
        raise ScienceContractError("AR6 member identity does not match requested scenario")
    if member_identity.archive_sha256 != projection["archive"]["sha256"]:
        raise ScienceContractError("AR6 member identity belongs to another archive")
    if verified_member_sha256 != member_identity.sha256:
        raise ScienceContractError("AR6 member SHA-256 differs from the source lock")
    statistics = projection["mapping"]["intervalStatistics"]
    interval = Ar6ProjectionInterval(
        scenario=scenario,
        horizon=year,
        baseline=projection["mapping"]["baseline"],
        source_release=projection["version"],
        member_sha256=member_identity.sha256,
        lower=extract_projection_grid(
            dataset,
            projection,
            scenario,
            year,
            quantile=statistics["lowerQuantile"],
        ),
        central=extract_projection_grid(
            dataset,
            projection,
            scenario,
            year,
            quantile=statistics["centralQuantile"],
        ),
        upper=extract_projection_grid(
            dataset,
            projection,
            scenario,
            year,
            quantile=statistics["upperQuantile"],
        ),
    )
    for candidate in (interval.central, interval.upper):
        if not (
            np.array_equal(candidate.latitudes, interval.lower.latitudes)
            and np.array_equal(candidate.longitudes, interval.lower.longitudes)
            and np.array_equal(candidate.location_ids, interval.lower.location_ids)
        ):
            raise ScienceContractError("AR6 interval grids do not share coordinates")
    complete = (
        np.isfinite(interval.lower.values_m)
        & np.isfinite(interval.central.values_m)
        & np.isfinite(interval.upper.values_m)
    )
    if np.any(
        complete
        & (
            (interval.lower.values_m > interval.central.values_m)
            | (interval.central.values_m > interval.upper.values_m)
        )
    ):
        raise ScienceContractError("AR6 interval quantiles are not monotonic")
    return interval


def projection_member_identity(
    source_lock: Mapping[str, Any], projection: Mapping[str, Any], scenario: str
) -> Ar6MemberIdentity:
    """Resolve one scenario member from the audited source lock."""
    mapping = projection["mapping"]
    if scenario not in mapping["scenarios"]:
        raise ScienceContractError(f"Unsupported AR6 scenario: {scenario}")
    sources = [
        item
        for item in source_lock["sources"]
        if item["id"] == projection["sourceId"] and item["version"] == projection["version"]
    ]
    if len(sources) != 1:
        raise ScienceContractError("AR6 source lock entry is missing or duplicated")
    assets = [
        asset
        for asset in sources[0]["assets"]
        if asset.get("sha256") == projection["archive"]["sha256"]
    ]
    if len(assets) != 1:
        raise ScienceContractError("AR6 archive identity differs from the source lock")
    upstream_scenario = mapping["scenarios"][scenario]
    members = [
        member
        for member in assets[0].get("members", [])
        if member.get("scenario") == upstream_scenario
    ]
    if len(members) != 1:
        raise ScienceContractError("AR6 scenario member is missing or duplicated")
    member = members[0]
    return Ar6MemberIdentity(
        scenario=scenario,
        archive_sha256=assets[0]["sha256"],
        path=member["path"],
        byte_size=member["byteSize"],
        sha256=member["sha256"],
    )


def bilinear_sample(
    grid: Ar6GridSlice,
    latitudes: NDArray[np.float64],
    longitudes: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Sample inside the native grid; never extrapolate or bridge nodata."""
    if latitudes.shape != longitudes.shape:
        raise ValueError("Latitude and longitude arrays must have the same shape")
    result = np.full(latitudes.shape, np.nan, dtype=np.float64)
    flat_result = result.ravel()
    for index, (latitude, longitude) in enumerate(
        zip(latitudes.ravel(), longitudes.ravel())
    ):
        if not (
            grid.latitudes[0] <= latitude <= grid.latitudes[-1]
            and grid.longitudes[0] <= longitude <= grid.longitudes[-1]
        ):
            continue
        lat_hi = int(np.searchsorted(grid.latitudes, latitude, side="right"))
        lon_hi = int(np.searchsorted(grid.longitudes, longitude, side="right"))
        lat_hi = min(max(lat_hi, 1), grid.latitudes.size - 1)
        lon_hi = min(max(lon_hi, 1), grid.longitudes.size - 1)
        lat_lo, lon_lo = lat_hi - 1, lon_hi - 1
        y = (latitude - grid.latitudes[lat_lo]) / (
            grid.latitudes[lat_hi] - grid.latitudes[lat_lo]
        )
        x = (longitude - grid.longitudes[lon_lo]) / (
            grid.longitudes[lon_hi] - grid.longitudes[lon_lo]
        )
        neighbours = np.array(
            [
                grid.values_m[lat_lo, lon_lo],
                grid.values_m[lat_lo, lon_hi],
                grid.values_m[lat_hi, lon_lo],
                grid.values_m[lat_hi, lon_hi],
            ]
        )
        weights = np.array([(1 - x) * (1 - y), x * (1 - y), (1 - x) * y, x * y])
        required = weights > 0
        if np.all(np.isfinite(neighbours[required])):
            flat_result[index] = float(np.sum(neighbours[required] * weights[required]))
    return result
