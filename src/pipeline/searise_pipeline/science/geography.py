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


def _metric_geometry(
    geometry: BaseGeometry,
    metric_crs: str,
    precision_metres: float,
    simplify_metres: float,
) -> BaseGeometry:
    """Repair, quantize, and simplify polygonal geometry in a metric CRS."""
    metric = gpd.GeoSeries([_polygonal(geometry)], crs=4326).to_crs(metric_crs).iloc[0]
    metric = _polygonal(metric)
    metric = _polygonal(
        shapely.set_precision(metric, grid_size=precision_metres, mode="valid_output")
    )
    if simplify_metres:
        metric = _polygonal(metric.simplify(simplify_metres, preserve_topology=True))
    return _polygonal(
        shapely.set_precision(metric, grid_size=precision_metres, mode="valid_output")
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
    if not {"CONTINENT", "NAME", "ADM0_A3"}.issubset(admin.columns):
        raise ScienceContractError("Natural Earth admin schema is missing required fields")

    support_recipe = rules["support"]["recipe"]
    if "includedAdmin0A3" in support_recipe:
        included = set(support_recipe["includedAdmin0A3"])
        selected = admin[admin["ADM0_A3"].isin(included)]
        actual = set(str(value) for value in selected["ADM0_A3"])
        if actual != included:
            missing = ", ".join(sorted(included - actual))
            raise ScienceContractError(f"Natural Earth support codes changed: {missing}")
    else:
        if support_recipe["filter"] != "CONTINENT == 'Europe' AND NAME != 'Russia'":
            raise ScienceContractError("Unsupported Europe filter expression")
        selected = admin[(admin["CONTINENT"] == "Europe") & (admin["NAME"] != "Russia")]
    if len(selected) != support_recipe["selectedFeatureCount"]:
        raise ScienceContractError("Natural Earth Europe feature count changed")

    support_clip = box(*support_recipe["clipBoundsWgs84"])
    support_wgs84 = _polygonal(
        shapely.union_all(selected.geometry.intersection(support_clip).array)
    )
    metric_crs = support_recipe["metricCrs"]
    if "precisionMetres" in support_recipe:
        support_metric = _metric_geometry(
            support_wgs84,
            metric_crs,
            support_recipe["precisionMetres"],
            0,
        )
        support_metric = _polygonal(
            support_metric.buffer(
                support_recipe["coastlineToleranceMetres"],
                quad_segs=support_recipe["bufferQuadSegments"],
            )
        )
        support_metric = _polygonal(
            shapely.set_precision(
                support_metric,
                grid_size=support_recipe["precisionMetres"],
                mode="valid_output",
            ).simplify(
                support_recipe["simplifyMetres"], preserve_topology=True
            )
        )
    else:
        # Compatibility path for the Phase 0.2 characterization fixture.
        support = support_wgs84.buffer(support_recipe["legacyBufferDegrees"])
        support = support.simplify(
            support_recipe["legacySimplifyDegrees"], preserve_topology=True
        )
        support = _precision(support, support_recipe["coordinatePrecision"])
        support_metric = gpd.GeoSeries([support], crs=4326).to_crs(metric_crs).iloc[0]

    coastal_recipe = rules["coastal"]["recipe"]
    ocean_clip = box(*coastal_recipe["oceanClipBoundsWgs84"])
    clipped_ocean = _polygonal(
        shapely.union_all(ocean.geometry.array).intersection(ocean_clip)
    )
    if coastal_recipe["metricCrs"] != metric_crs:
        raise ScienceContractError("Support and coastal metric CRS must match")
    if "precisionMetres" in coastal_recipe:
        metric_ocean = _metric_geometry(
            clipped_ocean,
            metric_crs,
            coastal_recipe["precisionMetres"],
            0,
        )
    else:
        metric_ocean = gpd.GeoSeries([clipped_ocean], crs=4326).to_crs(metric_crs).iloc[0]
    metric_coastal = metric_ocean.buffer(
        coastal_recipe["bufferMetres"],
        quad_segs=coastal_recipe.get("bufferQuadSegments", 8),
    ).intersection(support_metric)
    if "precisionMetres" in coastal_recipe:
        metric_coastal = _polygonal(
            shapely.set_precision(
                metric_coastal,
                grid_size=coastal_recipe["precisionMetres"],
                mode="valid_output",
            )
        )
        metric_coastal = metric_coastal.simplify(
            coastal_recipe["simplifyMetres"], preserve_topology=True
        ).intersection(
            support_metric.buffer(-coastal_recipe["containmentInsetMetres"])
        )
        metric_coastal = _polygonal(
            shapely.set_precision(
                metric_coastal,
                grid_size=coastal_recipe["precisionMetres"],
                mode="valid_output",
            )
        )
    coastal = gpd.GeoSeries([metric_coastal], crs=metric_crs).to_crs(4326).iloc[0]
    if "precisionMetres" in coastal_recipe:
        support = gpd.GeoSeries([support_metric], crs=metric_crs).to_crs(4326).iloc[0]
        support = _precision(support, support_recipe["coordinatePrecision"])
        coastal = _precision(coastal, coastal_recipe["coordinatePrecision"])
        # Rounding each geometry independently can reintroduce zero-width
        # topology artifacts. Apply the declared serialization inset before
        # the final intersection so the persisted geometry is exactly covered.
        coastal = shapely.normalize(
            shapely.make_valid(
                coastal.buffer(
                    -coastal_recipe["serializationContainmentInsetDegrees"],
                    quad_segs=1,
                ).intersection(support)
            )
        )
        if not isinstance(coastal, (Polygon, MultiPolygon)):
            raise ScienceContractError("Final coastal geometry is not polygonal")
    else:
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
        "coastalOutsideSupportSquareMetres": gpd.GeoSeries(
            [geometries["coastal"].difference(geometries["support"])], crs=4326
        )
        .to_crs(rules["support"]["recipe"]["metricCrs"])
        .iloc[0]
        .area,
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
