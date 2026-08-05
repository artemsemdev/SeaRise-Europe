"""Verified source-native lookup for the pinned IPCC AR6 regional projections."""

from __future__ import annotations

import hashlib
import math
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np
import xarray as xr
from shapely.geometry import Point  # type: ignore[import-untyped]
from shapely.geometry.base import BaseGeometry  # type: ignore[import-untyped]

from .ar6 import Ar6MemberIdentity, Ar6ProjectionInterval, projection_member_identity
from .contracts import ScienceContractError

_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class VerifiedAr6Archive:
    """An archive whose size and SHA-256 match both scientific source contracts."""

    path: Path
    sha256: str
    source_lock: Mapping[str, Any]
    projection: Mapping[str, Any]


@dataclass(frozen=True)
class Ar6SourceLocation:
    """Traceability identity of one resolved source-native AR6 grid location."""

    location_id: int
    latitude: float
    longitude: float
    family: str
    distance_km: float


@dataclass(frozen=True)
class Ar6ProjectionLookupResult:
    """A projection interval or an explicit fail-closed product state."""

    state: str
    reason_code: str
    scenario: str
    horizon: int
    baseline: str
    lower_m: float | None = None
    central_m: float | None = None
    upper_m: float | None = None
    source: Ar6SourceLocation | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_ar6_archive(
    archive_path: Path,
    source_lock: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> VerifiedAr6Archive:
    """Hash the complete archive before allowing any member to be opened."""
    expected = projection["archive"]
    if not archive_path.is_file():
        raise ScienceContractError(f"AR6 archive is absent: {archive_path}")
    if archive_path.stat().st_size != expected["byteSize"]:
        raise ScienceContractError("AR6 archive byte size differs from source semantics")
    actual_sha256 = _sha256(archive_path)
    if actual_sha256 != expected["sha256"]:
        raise ScienceContractError("AR6 archive SHA-256 differs from source semantics")

    for scenario in projection["mapping"]["scenarios"]:
        identity = projection_member_identity(source_lock, projection, scenario)
        if identity.archive_sha256 != actual_sha256:
            raise ScienceContractError("AR6 archive SHA-256 differs from the source lock")
    return VerifiedAr6Archive(archive_path, actual_sha256, source_lock, projection)


@contextmanager
def open_verified_ar6_member(
    archive: VerifiedAr6Archive,
    scenario: str,
) -> Iterator[tuple[xr.Dataset, Ar6MemberIdentity]]:
    """Extract, hash, then open one exact member without trusting ZIP metadata."""
    identity = projection_member_identity(archive.source_lock, archive.projection, scenario)
    if identity.archive_sha256 != archive.sha256:
        raise ScienceContractError("AR6 member belongs to another verified archive")

    try:
        with zipfile.ZipFile(archive.path) as source_zip:
            info = source_zip.getinfo(identity.path)
            if info.file_size != identity.byte_size:
                raise ScienceContractError("AR6 member byte size differs from the source lock")
            with tempfile.TemporaryDirectory(prefix="searise-ar6-") as temporary:
                member_path = Path(temporary) / Path(identity.path).name
                digest = hashlib.sha256()
                extracted_size = 0
                with source_zip.open(info) as source, member_path.open("wb") as target:
                    while chunk := source.read(_HASH_CHUNK_BYTES):
                        target.write(chunk)
                        digest.update(chunk)
                        extracted_size += len(chunk)
                if extracted_size != identity.byte_size:
                    raise ScienceContractError("AR6 extracted member byte size changed")
                if digest.hexdigest() != identity.sha256:
                    raise ScienceContractError("AR6 member SHA-256 differs from the source lock")
                with xr.open_dataset(
                    member_path,
                    engine="netcdf4",
                    decode_cf=False,
                    mask_and_scale=False,
                ) as dataset:
                    yield dataset, identity
    except KeyError as error:
        raise ScienceContractError(f"AR6 member is absent from archive: {identity.path}") from error
    except zipfile.BadZipFile as error:
        raise ScienceContractError("AR6 archive is not a valid ZIP file") from error


def _validate_interval_grid(interval: Ar6ProjectionInterval) -> None:
    reference = interval.lower
    expected_shape = (reference.latitudes.size, reference.longitudes.size)
    if reference.location_ids.shape != expected_shape or reference.values_m.shape != expected_shape:
        raise ScienceContractError("AR6 lookup grid shape differs from its coordinates")
    if np.unique(reference.location_ids).size != reference.location_ids.size:
        raise ScienceContractError("AR6 lookup grid contains duplicate source location IDs")
    for candidate in (interval.central, interval.upper):
        if not (
            np.array_equal(candidate.latitudes, reference.latitudes)
            and np.array_equal(candidate.longitudes, reference.longitudes)
            and np.array_equal(candidate.location_ids, reference.location_ids)
            and candidate.values_m.shape == expected_shape
        ):
            raise ScienceContractError("AR6 lookup interval grids do not share one source grid")


def _nearest_grid_location(
    interval: Ar6ProjectionInterval,
    latitude: float,
    longitude: float,
    earth_radius_km: float,
) -> tuple[int, int, float]:
    reference = interval.lower
    source_lons, source_lats = np.meshgrid(reference.longitudes, reference.latitudes)
    query_latitude = math.radians(latitude)
    source_latitudes = np.radians(source_lats)
    latitude_delta = source_latitudes - query_latitude
    longitude_delta = (np.radians(source_lons) - math.radians(longitude) + math.pi) % (
        2 * math.pi
    ) - math.pi
    haversine = np.sin(latitude_delta / 2) ** 2 + (
        math.cos(query_latitude) * np.cos(source_latitudes) * np.sin(longitude_delta / 2) ** 2
    )
    distances = (
        2 * earth_radius_km * np.arctan2(np.sqrt(haversine), np.sqrt(np.maximum(0, 1 - haversine)))
    )
    flat_ids = reference.location_ids.ravel()
    order = np.lexsort((flat_ids, distances.ravel()))
    row, column = np.unravel_index(int(order[0]), distances.shape)
    return int(row), int(column), float(distances[row, column])


def lookup_ar6_projection(
    interval: Ar6ProjectionInterval,
    *,
    latitude: float,
    longitude: float,
    scenario: str,
    horizon: int,
    baseline: str,
    support: BaseGeometry,
    coastal_scope: BaseGeometry,
    lookup_contract: Mapping[str, Any],
) -> Ar6ProjectionLookupResult:
    """Resolve one source grid node; never interpolate or skip a nodata node."""
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Latitude must be finite and between -90 and 90")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("Longitude must be finite and between -180 and 180")
    _validate_interval_grid(interval)

    reasons = lookup_contract["resultContract"]["stableReasonCodes"]
    point = Point(longitude, latitude)
    if not support.covers(point):
        return Ar6ProjectionLookupResult(
            "UnsupportedGeography",
            reasons["outsideEuropeSupport"],
            scenario,
            horizon,
            baseline,
        )
    if not coastal_scope.covers(point):
        return Ar6ProjectionLookupResult(
            "OutOfScope",
            reasons["outsideCoastalScope"],
            scenario,
            horizon,
            baseline,
        )

    lookup = lookup_contract["lookup"]
    row, column, distance_km = _nearest_grid_location(
        interval,
        latitude,
        longitude,
        float(lookup["distance"]["earthMeanRadiusKm"]),
    )
    source = Ar6SourceLocation(
        location_id=int(interval.lower.location_ids[row, column]),
        latitude=float(interval.lower.latitudes[row]),
        longitude=float(interval.lower.longitudes[column]),
        family="grid",
        distance_km=distance_km,
    )
    if distance_km > float(lookup["maximumDistanceKm"]):
        return Ar6ProjectionLookupResult(
            "DataUnavailable",
            reasons["sourceGridBeyondMaximumDistance"],
            scenario,
            horizon,
            baseline,
            source=source,
        )

    values = (
        float(interval.lower.values_m[row, column]),
        float(interval.central.values_m[row, column]),
        float(interval.upper.values_m[row, column]),
    )
    if not all(math.isfinite(value) for value in values):
        return Ar6ProjectionLookupResult(
            "DataUnavailable",
            reasons["sourceValueNodata"],
            scenario,
            horizon,
            baseline,
            source=source,
        )
    return Ar6ProjectionLookupResult(
        "ProjectionAvailable",
        "projection-available",
        scenario,
        horizon,
        baseline,
        lower_m=values[0],
        central_m=values[1],
        upper_m=values[2],
        source=source,
    )
