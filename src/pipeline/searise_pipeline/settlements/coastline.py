"""Build and inspect the immutable direct shoreline used for settlement distance."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import pyproj  # type: ignore[import-untyped]
import shapely  # type: ignore[import-untyped]
from shapely.geometry import LineString, Point, box, mapping, shape  # type: ignore[import-untyped]
from shapely.geometry.base import BaseGeometry  # type: ignore[import-untyped]

from searise_pipeline.settlements.coastline_contract import (
    CoastlineContractError,
    canonical_json_bytes,
    load_coastline_policy,
    quantize_distance_meters,
    sha256_bytes,
    sha256_file,
    validate_coastline_sources,
)

_EXPECTED_TOOLCHAIN = {
    "geopandas": "1.0.1",
    "gdal": "3.10.3",
    "geos": "3.11.4",
    "proj": "9.3.0",
    "pyogrio": "0.11.1",
    "pyproj": "3.6.1",
    "shapely": "2.0.7",
}
_EXPECTED_CONTROLS = [
    {
        "id": "major-island-ponta-delgada",
        "kind": "major-island",
        "name": "Ponta Delgada",
        "longitude": -25.6666,
        "latitude": 37.7412,
        "minimumDistanceMeters": None,
        "maximumDistanceMeters": 1000,
        "expectedNearestAssetId": "coastline",
    },
    {
        "id": "minor-island-capri",
        "kind": "minor-island",
        "name": "Capri",
        "longitude": 14.2426,
        "latitude": 40.5532,
        "minimumDistanceMeters": None,
        "maximumDistanceMeters": 1000,
        "expectedNearestAssetId": "minor-islands-coastline",
    },
    {
        "id": "port-barcelona",
        "kind": "port",
        "name": "Barcelona",
        "longitude": 2.1734,
        "latitude": 41.3851,
        "minimumDistanceMeters": None,
        "maximumDistanceMeters": 5000,
        "expectedNearestAssetId": "coastline",
    },
    {
        "id": "inland-prague",
        "kind": "inland",
        "name": "Prague",
        "longitude": 14.4208,
        "latitude": 50.088,
        "minimumDistanceMeters": 300000,
        "maximumDistanceMeters": None,
        "expectedNearestAssetId": "coastline",
    },
]


def _require_toolchain() -> None:
    actual = {
        "geopandas": gpd.__version__,
        "gdal": pyogrio.__gdal_version_string__,
        "geos": shapely.geos_version_string,
        "proj": pyproj.__proj_version__,
        "pyogrio": pyogrio.__version__,
        "pyproj": pyproj.__version__,
        "shapely": shapely.__version__,
    }
    if actual != _EXPECTED_TOOLCHAIN:
        raise CoastlineContractError(
            f"shoreline builder toolchain differs from the pinned identity: {actual}"
        )


def _validate_named_controls(policy: Mapping[str, Any]) -> None:
    if policy["controls"] != _EXPECTED_CONTROLS:
        raise CoastlineContractError("shoreline named controls differ from the reviewed v1 set")


def _verified_archive_members(path: Path, asset: Mapping[str, Any]) -> dict[str, bytes]:
    if not path.is_file():
        raise CoastlineContractError(f"locked shoreline archive is absent: {asset['id']}")
    if (path.stat().st_size, sha256_file(path)) != (asset["byteSize"], asset["sha256"]):
        raise CoastlineContractError(f"{asset['id']} archive checksum or size mismatch")
    expected = {member["path"]: member for member in asset["members"]}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if [info.filename for info in infos] != list(expected):
                raise CoastlineContractError(f"{asset['id']} ZIP member order or set changed")
            result: dict[str, bytes] = {}
            for info in infos:
                member = expected[info.filename]
                content = archive.read(info.filename)
                observed = (
                    info.file_size,
                    info.compress_size,
                    f"{info.CRC:08x}",
                    sha256_bytes(content),
                )
                locked = (
                    member["byteSize"],
                    member["compressedByteSize"],
                    member["crc32"],
                    member["sha256"],
                )
                if observed != locked:
                    raise CoastlineContractError(
                        f"{asset['id']} ZIP member identity changed: {info.filename}"
                    )
                result[info.filename] = content
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise CoastlineContractError(f"cannot verify {asset['id']} archive: {exc}") from exc
    version_name = next(name for name in result if name.endswith(".VERSION.txt"))
    try:
        native_version = result[version_name].decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise CoastlineContractError(f"{asset['id']} native version is not ASCII") from exc
    if native_version != asset["nativeVersion"]:
        raise CoastlineContractError(f"{asset['id']} VERSION member disagrees with source lock")
    return result


def _read_direct_lines(
    asset_id: str,
    native_version: str,
    members: Mapping[str, bytes],
    destination: Path,
) -> list[dict[str, Any]]:
    destination.mkdir()
    for name, content in members.items():
        target = destination / name
        if target.name != name:
            raise CoastlineContractError(f"unsafe shoreline archive member path: {name}")
        target.write_bytes(content)
    shape_paths = sorted(destination.glob("*.shp"))
    if len(shape_paths) != 1:
        raise CoastlineContractError(f"{asset_id} archive must contain one shapefile")
    frame = gpd.read_file(shape_paths[0], engine="pyogrio")
    if frame.crs is None or frame.crs.to_epsg() != 4326:
        raise CoastlineContractError(f"{asset_id} shoreline CRS is not EPSG:4326")
    if frame.empty or not frame.is_valid.all() or set(frame.geom_type) != {"LineString"}:
        raise CoastlineContractError(f"{asset_id} source must be valid direct LineStrings")
    return [
        {
            "geometry": geometry,
            "nativeVersion": native_version,
            "sourceAssetId": asset_id,
        }
        for geometry in frame.geometry
    ]


def _canonical_features(
    source_lines: Mapping[str, list[dict[str, Any]]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selection = box(*policy["recipe"]["selectionBoundsWgs84"])
    features: list[dict[str, Any]] = []
    for asset_id in policy["recipe"]["sourceAssetOrder"]:
        selected = [
            item for item in source_lines[asset_id] if item["geometry"].intersects(selection)
        ]
        normalized_items = [(item, shapely.normalize(item["geometry"])) for item in selected]
        normalized_items.sort(key=lambda item: shapely.to_wkb(item[1], byte_order=1))
        for item, normalized in normalized_items:
            if not normalized.equals(item["geometry"]):
                raise CoastlineContractError("shoreline normalization changed source line shape")
            features.append(
                {
                    "geometry": mapping(normalized),
                    "properties": {"sourceAssetId": asset_id},
                    "type": "Feature",
                }
            )
    if not features:
        raise CoastlineContractError("shoreline selection produced no direct linework")
    return features


def build_coastline(
    source_lock_path: Path,
    policy_path: Path,
    archives: Mapping[str, Path],
) -> bytes:
    """Rebuild canonical shoreline bytes from both exact official archives."""
    _require_toolchain()
    policy = load_coastline_policy(policy_path)
    _validate_named_controls(policy)
    assets = validate_coastline_sources(source_lock_path, policy)
    expected_ids = policy["recipe"]["sourceAssetOrder"]
    if list(archives) != expected_ids:
        raise CoastlineContractError("caller did not supply both shoreline archives in order")
    source_lines: dict[str, list[dict[str, Any]]] = {}
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        for asset_id in expected_ids:
            members = _verified_archive_members(archives[asset_id], assets[asset_id])
            source_lines[asset_id] = _read_direct_lines(
                asset_id,
                assets[asset_id]["nativeVersion"],
                members,
                temporary_root / asset_id,
            )
    document = {
        "features": _canonical_features(source_lines, policy),
        "name": "europe-settlement-shoreline-v1",
        "type": "FeatureCollection",
    }
    return canonical_json_bytes(document) + b"\n"


def _artifact_lines(
    document: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, list[BaseGeometry]]:
    expected_assets = policy["recipe"]["sourceAssetOrder"]
    by_source: dict[str, list[BaseGeometry]] = {asset_id: [] for asset_id in expected_assets}
    if document.get("type") != "FeatureCollection" or document.get("name") != (
        "europe-settlement-shoreline-v1"
    ):
        raise CoastlineContractError("shoreline artifact envelope changed")
    for feature in document.get("features", []):
        if set(feature) != {"geometry", "properties", "type"} or feature["type"] != "Feature":
            raise CoastlineContractError("shoreline feature contract changed")
        properties = feature["properties"]
        if set(properties) != {"sourceAssetId"} or properties["sourceAssetId"] not in by_source:
            raise CoastlineContractError("shoreline feature source identity changed")
        geometry = shape(feature["geometry"])
        if not isinstance(geometry, LineString) or geometry.is_empty or not geometry.is_valid:
            raise CoastlineContractError("shoreline artifact contains non-line or invalid geometry")
        by_source[properties["sourceAssetId"]].append(geometry)
    if any(not geometries for geometries in by_source.values()):
        raise CoastlineContractError("shoreline artifact omitted a required source asset")
    return by_source


def _control_results(
    by_source: Mapping[str, list[BaseGeometry]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    metric_crs = policy["distanceMethod"]["metricCrs"]
    metric_sources = {
        asset_id: gpd.GeoSeries([shapely.union_all(lines)], crs=4326).to_crs(metric_crs).iloc[0]
        for asset_id, lines in by_source.items()
    }
    results = []
    for control in policy["controls"]:
        point = (
            gpd.GeoSeries([Point(control["longitude"], control["latitude"])], crs=4326)
            .to_crs(metric_crs)
            .iloc[0]
        )
        distances = {
            asset_id: float(point.distance(geometry))
            for asset_id, geometry in metric_sources.items()
        }
        nearest_asset = min(distances, key=lambda asset_id: (distances[asset_id], asset_id))
        distance = distances[nearest_asset]
        passed = (
            (
                control["minimumDistanceMeters"] is None
                or distance >= control["minimumDistanceMeters"]
            )
            and (
                control["maximumDistanceMeters"] is None
                or distance <= control["maximumDistanceMeters"]
            )
            and (
                control["expectedNearestAssetId"] is None
                or nearest_asset == control["expectedNearestAssetId"]
            )
        )
        results.append(
            {
                "expectedNearestAssetId": control["expectedNearestAssetId"],
                "id": control["id"],
                "maximumDistanceMeters": control["maximumDistanceMeters"],
                "minimumDistanceMeters": control["minimumDistanceMeters"],
                "nearestAssetId": nearest_asset,
                "passed": passed,
                "persistedDistanceMeters": quantize_distance_meters(distance),
            }
        )
    if not all(item["passed"] for item in results):
        raise CoastlineContractError("one or more named shoreline controls failed")
    return results


def inspect_coastline_artifact(repo_root: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Verify checked-in bytes, direct-line structure, metric controls, and bounds."""
    _require_toolchain()
    _validate_named_controls(policy)
    output = policy["output"]
    path = repo_root / output["path"]
    try:
        content = path.read_bytes()
        document = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise CoastlineContractError(f"cannot read shoreline artifact: {exc}") from exc
    if (len(content), sha256_bytes(content)) != (output["byteSize"], output["sha256"]):
        raise CoastlineContractError("shoreline artifact checksum or byte-size mismatch")
    if canonical_json_bytes(document) + b"\n" != content:
        raise CoastlineContractError("shoreline artifact is not canonical JSON")
    by_source = _artifact_lines(document, policy)
    lines = [geometry for geometries in by_source.values() for geometry in geometries]
    feature_count = len(lines)
    coordinate_count = sum(int(shapely.get_num_coordinates(line)) for line in lines)
    bounds = list(shapely.union_all(lines).bounds)
    if (feature_count, coordinate_count, bounds) != (
        output["featureCount"],
        output["coordinateCount"],
        output["boundsWgs84"],
    ):
        raise CoastlineContractError("shoreline artifact statistics changed")
    controls = _control_results(by_source, policy)
    return {
        "boundsWgs84": bounds,
        "bySourceAsset": {
            asset_id: len(by_source[asset_id]) for asset_id in policy["recipe"]["sourceAssetOrder"]
        },
        "controlResults": controls,
        "controls": {"count": len(controls), "passed": sum(item["passed"] for item in controls)},
        "coordinateCount": coordinate_count,
        "featureCount": feature_count,
        "featuresTruncated": 0,
        "geometryTypes": sorted({line.geom_type for line in lines}),
        "sha256": output["sha256"],
        "valid": all(line.is_valid for line in lines),
    }


def build_coastline_evidence(repo_root: Path, policy_path: Path) -> dict[str, Any]:
    """Return byte-stable QA evidence bound to the policy, source lock, and output."""
    policy = load_coastline_policy(policy_path)
    source_lock_path = repo_root / policy["sourceLock"]["path"]
    validate_coastline_sources(source_lock_path, policy)
    return {
        "schemaVersion": 1,
        "evidenceId": "settlement-shoreline-distance-qa-v1",
        "policy": {
            "path": str(policy_path.relative_to(repo_root)),
            "sha256": sha256_file(policy_path),
            "version": policy["policyVersion"],
        },
        "distanceMethodVersion": policy["distanceMethodVersion"],
        "sourceLock": policy["sourceLock"],
        "output": policy["output"],
        "purpose": policy["purpose"],
        "recipe": policy["recipe"],
        "distanceMethod": policy["distanceMethod"],
        "distancePersistence": policy["distancePersistence"],
        "qaOracle": {
            "engine": "geopandas-pyogrio-pyproj-shapely",
            "independentFromProductionDuckdb": True,
            "method": (
                "Pyogrio/GDAL read, then GeoSeries.to_crs(EPSG:3035) and Shapely planar distance"
            ),
            "role": "checked-artifact-control-only",
        },
        "coastalClassification": policy["coastalClassification"],
        "toolchain": _EXPECTED_TOOLCHAIN,
        "inspection": inspect_coastline_artifact(repo_root, policy),
    }
