"""Build offline AR6 lookup goldens with an independent netCDF4 reader."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd  # type: ignore[import-untyped]
import netCDF4  # type: ignore[import-untyped]
import numpy as np
from shapely.geometry import Point  # type: ignore[import-untyped]

CHUNK_BYTES = 1024 * 1024
GENERATOR_PATH = "scripts/science/build_ar6_lookup_goldens.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _archive_asset(
    source_lock: Mapping[str, Any], validation: Mapping[str, Any]
) -> Mapping[str, Any]:
    source_binding = validation["source"]
    sources = [
        source
        for source in source_lock["sources"]
        if source["id"] == source_binding["sourceId"]
        and source["version"] == source_binding["version"]
    ]
    if len(sources) != 1:
        raise ValueError("AR6 source lock entry is missing or duplicated")
    assets = [
        asset
        for asset in sources[0]["assets"]
        if asset.get("sha256") == source_binding["archiveSha256"]
    ]
    if len(assets) != 1:
        raise ValueError("AR6 archive binding differs from the source lock")
    return assets[0]


def _verify_archive(archive_path: Path, asset: Mapping[str, Any]) -> None:
    if archive_path.stat().st_size != asset["byteSize"]:
        raise ValueError("AR6 archive byte size differs from the source lock")
    if _sha256(archive_path) != asset["sha256"]:
        raise ValueError("AR6 archive SHA-256 differs from the source lock")


def _extract_members(
    archive_path: Path,
    asset: Mapping[str, Any],
    target_dir: Path,
) -> dict[str, Path]:
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for member in asset["members"]:
            target = target_dir / Path(member["path"]).name
            digest = hashlib.sha256()
            size = 0
            with archive.open(member["path"]) as source, target.open("wb") as output:
                while chunk := source.read(CHUNK_BYTES):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != member["byteSize"] or digest.hexdigest() != member["sha256"]:
                raise ValueError(f"AR6 member integrity mismatch: {member['scenario']}")
            extracted[member["scenario"]] = target
    return extracted


def _coordinate_index(values: np.ndarray[Any, Any], expected: float, label: str) -> int:
    matches = np.flatnonzero(values == expected)
    if matches.size != 1:
        raise ValueError(f"AR6 {label} is absent or duplicated: {expected}")
    return int(matches[0])


def _grid_coordinates(
    dataset: netCDF4.Dataset,
    location_id_minimum: int,
    expected_count: int,
) -> tuple[
    np.ndarray[Any, Any],
    np.ndarray[Any, Any],
    np.ndarray[Any, Any],
    np.ndarray[Any, Any],
]:
    location_ids = np.asarray(dataset.variables["locations"][:], dtype=np.int64)
    selected = location_ids >= location_id_minimum
    if np.count_nonzero(selected) != expected_count:
        raise ValueError("AR6 native grid count differs from the decision contract")
    return (
        np.flatnonzero(selected),
        location_ids[selected],
        np.asarray(dataset.variables["lat"][:], dtype=np.float64)[selected],
        np.asarray(dataset.variables["lon"][:], dtype=np.float64)[selected],
    )


def _nearest_location(
    latitude: float,
    longitude: float,
    location_ids: np.ndarray[Any, Any],
    latitudes: np.ndarray[Any, Any],
    longitudes: np.ndarray[Any, Any],
    radius_km: float,
) -> tuple[int, float]:
    query_latitude = math.radians(latitude)
    source_latitudes = np.radians(latitudes)
    latitude_delta = source_latitudes - query_latitude
    longitude_delta = (np.radians(longitudes) - math.radians(longitude) + math.pi) % (
        2 * math.pi
    ) - math.pi
    haversine = np.sin(latitude_delta / 2) ** 2 + (
        math.cos(query_latitude)
        * np.cos(source_latitudes)
        * np.sin(longitude_delta / 2) ** 2
    )
    distances = (
        2
        * radius_km
        * np.arctan2(np.sqrt(haversine), np.sqrt(np.maximum(0, 1 - haversine)))
    )
    order = np.lexsort((location_ids, distances))
    selected = int(order[0])
    return selected, float(distances[selected])


def _scope_state(point: Point, support: Any, coastal: Any) -> tuple[str, str]:
    if not support.covers(point):
        return "UnsupportedGeography", "outside-europe-support"
    if not coastal.covers(point):
        return "OutOfScope", "outside-coastal-scope"
    return "ProjectionAvailable", "projection-available"


def _projection_values(
    dataset: netCDF4.Dataset,
    source_index: int,
    horizon: int,
    quantiles: Mapping[str, float],
    unit_to_metres: float,
    fill_value: int,
) -> dict[str, float] | None:
    years = np.asarray(dataset.variables["years"][:])
    source_quantiles = np.asarray(dataset.variables["quantiles"][:])
    year_index = _coordinate_index(years, horizon, "year")
    values: dict[str, float] = {}
    for statistic in ("lower", "central", "upper"):
        quantile_index = _coordinate_index(
            source_quantiles, quantiles[statistic], f"{statistic} quantile"
        )
        raw = int(
            dataset.variables["sea_level_change"][
                quantile_index, year_index, source_index
            ]
        )
        if raw == fill_value:
            return None
        values[f"{statistic}Metres"] = raw * unit_to_metres
    if not values["lowerMetres"] <= values["centralMetres"] <= values["upperMetres"]:
        raise ValueError("AR6 likely interval is not monotonic")
    return values


def build_goldens(
    repository_root: Path,
    archive_path: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    science_dir = repository_root / "src/pipeline/science"
    validation_path = science_dir / "ar6-lookup-validation.json"
    decision_path = science_dir / "ar6-projection-contract.json"
    source_lock_path = repository_root / "src/pipeline/sources/source-lock.json"
    validation = _load(validation_path)
    decision = _load(decision_path)
    source_lock = _load(source_lock_path)
    asset = _archive_asset(source_lock, validation)
    _verify_archive(archive_path, asset)

    support_path = repository_root / "data/geometry/europe.geojson"
    coastal_path = repository_root / "data/geometry/coastal_analysis_zone.geojson"
    support = gpd.read_file(support_path).geometry.union_all()
    coastal = gpd.read_file(coastal_path).geometry.union_all()
    point_rule = decision["spatialLookup"]["point"]
    grid_rule = decision["spatialLookup"]["gridIdentity"]
    source_binding = decision["sourceBinding"]
    upstream_scenarios = validation["source"]["memberSha256ByScenario"]
    product_to_upstream = {
        product: product.replace("ssp1-26", "ssp126")
        .replace("ssp2-45", "ssp245")
        .replace("ssp5-85", "ssp585")
        for product in upstream_scenarios
    }

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="searise-ar6-goldens-") as temporary:
        member_paths = _extract_members(archive_path, asset, Path(temporary))
        datasets = {
            scenario: netCDF4.Dataset(member_paths[upstream])
            for scenario, upstream in product_to_upstream.items()
        }
        try:
            for dataset in datasets.values():
                dataset.set_auto_mask(False)
            reference_grid = _grid_coordinates(
                datasets["ssp1-26"],
                grid_rule["locationIdMinimum"],
                grid_rule["locationCount"],
            )
            for scenario, dataset in datasets.items():
                candidate_grid = _grid_coordinates(
                    dataset,
                    grid_rule["locationIdMinimum"],
                    grid_rule["locationCount"],
                )
                if not all(
                    np.array_equal(candidate, reference)
                    for candidate, reference in zip(candidate_grid, reference_grid)
                ):
                    raise ValueError(f"AR6 native grids differ for {scenario}")

            source_indexes, location_ids, latitudes, longitudes = reference_grid
            for declared in validation["validation"]["goldenPoints"]:
                coordinates = declared["coordinates"]
                state, reason = _scope_state(
                    Point(coordinates["longitude"], coordinates["latitude"]),
                    support,
                    coastal,
                )
                if state != declared["expectedState"]:
                    raise ValueError(f"Golden scope state changed: {declared['id']}")
                result: dict[str, Any] = {
                    "id": declared["id"],
                    "coordinates": coordinates,
                    "state": state,
                    "reasonCode": reason,
                }
                if state == "ProjectionAvailable":
                    location_index, distance_km = _nearest_location(
                        coordinates["latitude"],
                        coordinates["longitude"],
                        location_ids,
                        latitudes,
                        longitudes,
                        point_rule["earthRadiusKilometres"],
                    )
                    if distance_km > point_rule["maximumDistanceKilometres"]:
                        raise ValueError(
                            f"Golden source is too distant: {declared['id']}"
                        )
                    result["source"] = {
                        "locationId": int(location_ids[location_index]),
                        "latitude": float(latitudes[location_index]),
                        "longitude": float(longitudes[location_index]),
                        "family": "grid",
                        "distanceKilometres": round(
                            distance_km, point_rule["reportedDistanceDecimalPlaces"]
                        ),
                    }
                    projections = []
                    for scenario in source_binding["scenarios"]:
                        dataset = datasets[scenario]
                        source_index = int(source_indexes[location_index])
                        for horizon in source_binding["horizons"]:
                            values = _projection_values(
                                dataset,
                                source_index,
                                horizon,
                                source_binding["quantiles"],
                                source_binding["unitToMetres"],
                                source_binding["fillValue"],
                            )
                            if values is None:
                                raise ValueError(
                                    f"Golden source is nodata: {declared['id']}"
                                )
                            projections.append(
                                {"scenario": scenario, "horizon": horizon, **values}
                            )
                    result["projections"] = projections
                results.append(result)
        finally:
            for dataset in datasets.values():
                dataset.close()

    members = {member["scenario"]: member["sha256"] for member in asset["members"]}
    generator = repository_root / GENERATOR_PATH
    return {
        "$schema": "./ar6-lookup-goldens.schema.json",
        "schemaVersion": 1,
        "goldenSetId": decision["validation"]["goldenSetId"],
        "validationContract": {
            "path": "src/pipeline/science/ar6-lookup-validation.json",
            "sha256": _sha256(validation_path),
        },
        "decisionContract": {
            "path": "src/pipeline/science/ar6-projection-contract.json",
            "sha256": _sha256(decision_path),
        },
        "scopeGeometry": {
            "support": {
                "path": "data/geometry/europe.geojson",
                "sha256": _sha256(support_path),
            },
            "coastal": {
                "path": "data/geometry/coastal_analysis_zone.geojson",
                "sha256": _sha256(coastal_path),
            },
            "predicate": "covers",
        },
        "provenance": {
            "retrievedAt": retrieved_at,
            "sourceRecord": validation["source"]["record"],
            "archiveSha256": asset["sha256"],
            "memberSha256": members,
            "readerName": "netCDF4-python",
            "readerVersion": netCDF4.__version__,
            "generatorPath": GENERATOR_PATH,
            "generatorSha256": _sha256(generator),
            "networkRequiredForValidation": False,
            "onlineReferenceRole": "supplementary-manual-cross-check-only",
        },
        "numericToleranceMetres": decision["validation"]["absoluteToleranceMetres"],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    arguments = parser.parse_args()
    document = build_goldens(
        arguments.repository_root.resolve(),
        arguments.archive.resolve(),
        arguments.retrieved_at,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
