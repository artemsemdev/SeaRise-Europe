"""Rebuild and inspect the explicitly approximate Phase 0 geometries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd  # type: ignore[import-untyped]
import shapely  # type: ignore[import-untyped]
from shapely.geometry import (  # type: ignore[import-untyped]
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
)
from shapely.geometry.base import BaseGeometry  # type: ignore[import-untyped]

from .contracts import ScienceContractError


@dataclass(frozen=True)
class CandidateGeometries:
    """Deterministically rebuilt support and coastal approximation."""

    support: BaseGeometry
    coastal: BaseGeometry
    selected_feature_count: int


def _polygonal(geometry: BaseGeometry) -> BaseGeometry:
    parts = [
        part
        for part in shapely.get_parts(shapely.make_valid(geometry))
        if isinstance(part, (Polygon, MultiPolygon))
    ]
    if not parts:
        raise ScienceContractError("Geometry recipe produced no polygonal output")
    return shapely.normalize(shapely.make_valid(shapely.union_all(parts)))


def _precision(geometry: BaseGeometry, decimals: int) -> BaseGeometry:
    return _polygonal(
        shapely.set_precision(geometry, grid_size=10 ** (-decimals), mode="valid_output")
    )


def rebuild_approximation(
    admin_path: Path,
    ocean_path: Path,
    rules: Mapping[str, Any],
) -> CandidateGeometries:
    """Rebuild from pinned source archives and machine-readable parameters."""
    admin = gpd.read_file(admin_path)
    ocean = gpd.read_file(ocean_path)
    if admin.crs is None or admin.crs.to_epsg() != 4326:
        raise ScienceContractError("Natural Earth admin source is not EPSG:4326")
    if ocean.crs is None or ocean.crs.to_epsg() != 4326:
        raise ScienceContractError("Natural Earth ocean source is not EPSG:4326")
    if not {"CONTINENT", "NAME"}.issubset(admin.columns):
        raise ScienceContractError("Natural Earth admin schema is missing required fields")

    support_recipe = rules["support"]["recipe"]
    if support_recipe["filter"] != "CONTINENT == 'Europe' AND NAME != 'Russia'":
        raise ScienceContractError("Unsupported Europe filter expression")
    selected = admin[(admin["CONTINENT"] == "Europe") & (admin["NAME"] != "Russia")]
    if len(selected) != support_recipe["selectedFeatureCount"]:
        raise ScienceContractError("Natural Earth Europe feature count changed")

    support_clip = box(*support_recipe["clipBoundsWgs84"])
    support = shapely.union_all(selected.geometry.intersection(support_clip).array)
    support = support.buffer(support_recipe["legacyBufferDegrees"])
    support = support.simplify(
        support_recipe["legacySimplifyDegrees"], preserve_topology=True
    )
    support = _precision(support, support_recipe["coordinatePrecision"])

    coastal_recipe = rules["coastal"]["recipe"]
    ocean_clip = box(*coastal_recipe["oceanClipBoundsWgs84"])
    clipped_ocean = _polygonal(shapely.union_all(ocean.geometry.array).intersection(ocean_clip))
    metric_crs = coastal_recipe["metricCrs"]
    metric_ocean = gpd.GeoSeries([clipped_ocean], crs=4326).to_crs(metric_crs).iloc[0]
    metric_support = gpd.GeoSeries([support], crs=4326).to_crs(metric_crs).iloc[0]
    metric_coastal = metric_ocean.buffer(coastal_recipe["bufferMetres"]).intersection(
        metric_support
    )
    coastal = gpd.GeoSeries([metric_coastal], crs=metric_crs).to_crs(4326).iloc[0]
    coastal = coastal.simplify(
        coastal_recipe["legacySimplifyDegrees"], preserve_topology=True
    )
    coastal = _precision(coastal, coastal_recipe["coordinatePrecision"])
    return CandidateGeometries(support, coastal, len(selected))


def canonical_geojson_bytes(
    name: str,
    geometry: BaseGeometry,
    properties: Mapping[str, Any],
) -> bytes:
    """Serialize normalized geometry with stable key order and whitespace."""
    document = {
        "features": [
            {
                "geometry": mapping(shapely.normalize(geometry)),
                "properties": dict(properties),
                "type": "Feature",
            }
        ],
        "name": name,
        "type": "FeatureCollection",
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _geometry_stats(geometry: BaseGeometry, metric_crs: str) -> dict[str, Any]:
    metric = gpd.GeoSeries([geometry], crs=4326).to_crs(metric_crs).iloc[0]
    return {
        "geometryType": geometry.geom_type,
        "valid": bool(geometry.is_valid),
        "validityReason": shapely.is_valid_reason(geometry),
        "componentCount": len(list(shapely.get_parts(geometry))),
        "boundsWgs84": list(geometry.bounds),
        "areaSquareKilometres": metric.area / 1_000_000,
        "perimeterKilometres": metric.length / 1_000,
    }


def inspect_geometry_assets(
    repo_root: Path,
    rules: Mapping[str, Any],
    controls_path: Path,
) -> dict[str, Any]:
    """Report geometry, topology, control, and boundary-predicate evidence."""
    geometries: dict[str, BaseGeometry] = {}
    report: dict[str, Any] = {"schemaVersion": 1, "predicate": rules["predicate"]}
    for key in ("support", "coastal"):
        entry = rules[key]
        path = repo_root / entry["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ScienceContractError(f"{key} geometry checksum mismatch")
        geometry = gpd.read_file(path).geometry.union_all()
        geometries[key] = geometry
        report[key] = {
            "version": entry["version"],
            "status": entry["status"],
            "sha256": digest,
            **_geometry_stats(geometry, entry["recipe"]["metricCrs"]),
        }

    controls = json.loads(controls_path.read_text(encoding="utf-8"))
    if controls["predicate"] != rules["predicate"]:
        raise ScienceContractError("Geometry control predicate does not match contract")
    outcomes = []
    for control in controls["controls"]:
        point = Point(control["longitude"], control["latitude"])
        actual_support = geometries["support"].covers(point)
        actual_coastal = geometries["coastal"].covers(point)
        passed = actual_support == control["support"] and actual_coastal == control["coastal"]
        outcomes.append({"name": control["name"], "kind": control["kind"], "passed": passed})
    if not all(item["passed"] for item in outcomes):
        raise ScienceContractError("One or more geography controls failed")

    boundary_point = geometries["support"].boundary.representative_point()
    report["topology"] = {
        "supportCoversCoastal": geometries["support"].covers(geometries["coastal"]),
        "boundaryControl": {
            "longitude": boundary_point.x,
            "latitude": boundary_point.y,
            "covers": geometries["support"].covers(boundary_point),
            "contains": geometries["support"].contains(boundary_point),
        },
    }
    report["controls"] = {
        "count": len(outcomes),
        "passed": sum(item["passed"] for item in outcomes),
        "outcomes": outcomes,
    }
    return report
