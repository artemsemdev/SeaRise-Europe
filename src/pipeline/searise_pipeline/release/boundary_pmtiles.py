"""Deterministic visual-only PMTiles for reviewed engineering boundaries."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, cast

from searise_pipeline.science.contracts import ScienceContractError

from .boundary_geoparquet import validate_boundary_geoparquet
from .pmtiles import VectorToolchainEvidence

_MINIMUM_ZOOM = 0
_MAXIMUM_ZOOM = 6
_STATUS = "selected-scope-approximation"
_PURPOSE = "product-eligibility-only"
_SHAPELY_VERSION = "2.0.7"
_PMTILES_HEADER = struct.Struct("<7sB11Q6B4iB2i")


@dataclass(frozen=True)
class _BoundarySpecification:
    role: str
    boundary_id: str
    source_path: str
    source_byte_size: int
    source_sha256: str
    layer_id: str
    header_bounds: tuple[float, float, float, float]
    header_center: tuple[float, float, int]


_BOUNDARIES = {
    "support-boundary": _BoundarySpecification(
        role="support-boundary",
        boundary_id="europe-support",
        source_path="boundaries/europe.parquet",
        source_byte_size=267676,
        source_sha256="531c6042a33cf3be9bc3ea340b0e557cb66bafb34de7954db0d7e47be90d35a9",
        layer_id="support_boundary",
        header_bounds=(-28.851018, 30.021176, 40.1733959, 74.536347),
        header_center=(25.3125, 38.788894, 6),
    ),
    "coastal-boundary": _BoundarySpecification(
        role="coastal-boundary",
        boundary_id="coastal-analysis-zone",
        source_path="boundaries/coastal-analysis-zone.parquet",
        source_byte_size=667750,
        source_sha256="3ba4d5eaba24d1202482bc33fd64fde8ce54b7ff1dd1456990d3c8cfece43366",
        layer_id="coastal_boundary",
        header_bounds=(-28.850986, 30.021211, 38.3141589, 74.536318),
        header_center=(25.3125, 38.788894, 6),
    ),
}


@dataclass(frozen=True)
class _BoundarySource:
    specification: _BoundarySpecification
    geometry: Any
    version: str
    lineage: Mapping[str, Any]
    rights: Mapping[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_shapely() -> Any:
    try:
        import shapely
    except ImportError as exc:
        raise ScienceContractError("Boundary PMTiles requires Shapely 2.0.7") from exc
    if shapely.__version__ != _SHAPELY_VERSION:
        raise ScienceContractError("Boundary PMTiles requires exact Shapely 2.0.7")
    return shapely


def _load_source(
    geoparquet_path: Path,
    source_geojson_path: Path,
    *,
    role: str,
) -> _BoundarySource:
    try:
        specification = _BOUNDARIES[role]
    except KeyError as exc:
        raise ScienceContractError(f"Unsupported boundary role: {role}") from exc
    if (
        not geoparquet_path.is_file()
        or geoparquet_path.stat().st_size != specification.source_byte_size
        or _sha256(geoparquet_path) != specification.source_sha256
    ):
        raise ScienceContractError(
            "Boundary PMTiles source GeoParquet identity differs from PR #214"
        )
    validate_boundary_geoparquet(
        geoparquet_path,
        source_geojson_path,
        role=role,
    )
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ScienceContractError(
            "Boundary PMTiles requires the pinned geospatial toolchain"
        ) from exc
    shapely = _require_shapely()
    try:
        table = pq.read_table(geoparquet_path)
        metadata = pq.ParquetFile(geoparquet_path).metadata.metadata or {}
        boundary = json.loads(metadata[b"searise:boundary"])
        geo = json.loads(metadata[b"geo"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ScienceContractError("Boundary GeoParquet metadata cannot be decoded") from exc
    values = table.to_pydict()
    expected = {
        "boundary_id": [specification.boundary_id],
        "role": [role],
        "status": [_STATUS],
        "purpose": [_PURPOSE],
        "publication_eligible": [False],
        "canonical": [False],
        "production": [False],
        "hazard_extent_claim": [False],
    }
    if any(values.get(field) != value for field, value in expected.items()):
        raise ScienceContractError("Boundary GeoParquet safe row values differ from PR #214")
    if (
        boundary.get("role") != role
        or boundary.get("status") != _STATUS
        or boundary.get("purpose") != _PURPOSE
        or boundary.get("engineeringUse") != "engineering-only"
        or any(
            boundary.get(field) is not False
            for field in (
                "publicationEligible",
                "canonical",
                "production",
                "hazardExtentClaim",
            )
        )
    ):
        raise ScienceContractError("Boundary GeoParquet safe metadata differs from PR #214")
    geometry = shapely.from_wkb(values["geometry"][0])
    geometry_metadata = geo.get("columns", {}).get("geometry", {})
    bbox = geometry_metadata.get("bbox")
    if (
        geometry.geom_type != "MultiPolygon"
        or not geometry.is_valid
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or tuple(float(value) for value in bbox) != tuple(float(value) for value in geometry.bounds)
    ):
        raise ScienceContractError("Boundary GeoParquet geometry metadata differs from its row")
    return _BoundarySource(
        specification=specification,
        geometry=geometry,
        version=str(boundary["version"]),
        lineage=boundary["lineage"],
        rights=boundary["rights"],
    )


def _toolchain_metadata(
    evidence: VectorToolchainEvidence,
    *,
    build_receipt_sha256: str,
) -> dict[str, object]:
    observed = asdict(evidence)
    observed["platform"] = observed.pop("pmtiles_distribution_platform")
    observed["shapely_version"] = _SHAPELY_VERSION
    observed["tippecanoe_build_receipt_sha256"] = build_receipt_sha256
    return observed


def _expected_metadata(
    source: _BoundarySource,
    evidence: VectorToolchainEvidence,
    *,
    build_receipt_sha256: str,
) -> dict[str, Any]:
    specification = source.specification
    return {
        "attribution": source.rights["attribution"],
        "description": (f"SeaRise {specification.boundary_id} engineering boundary; visual only"),
        "format": "pbf",
        "generator": f"tippecanoe v{evidence.tippecanoe_version}",
        "name": f"SeaRise {specification.boundary_id}",
        "searise": {
            "analytical_lookup": "prohibited",
            "canonical": False,
            "hazard_extent_claim": False,
            "lineage": source.lineage,
            "production": False,
            "publication_eligible": False,
            "purpose": _PURPOSE,
            "rights": source.rights,
            "role": specification.role,
            "schema_version": "1.0.0",
            "source_geoparquet": {
                "byte_size": specification.source_byte_size,
                "path": specification.source_path,
                "sha256": specification.source_sha256,
            },
            "status": _STATUS,
            "toolchain": _toolchain_metadata(
                evidence,
                build_receipt_sha256=build_receipt_sha256,
            ),
            "version": source.version,
            "visual_only": True,
        },
        "type": "overlay",
        "vector_layers": [
            {
                "description": "Engineering product-eligibility boundary; visual only",
                "fields": {
                    "analytical_lookup": "String",
                    "boundary_id": "String",
                    "canonical": "Boolean",
                    "hazard_extent_claim": "Boolean",
                    "production": "Boolean",
                    "publication_eligible": "Boolean",
                    "purpose": "String",
                    "role": "String",
                    "source_geoparquet_byte_size": "Number",
                    "source_geoparquet_sha256": "String",
                    "status": "String",
                    "version": "String",
                    "visual_only": "Boolean",
                },
                "id": specification.layer_id,
                "maxzoom": _MAXIMUM_ZOOM,
                "minzoom": _MINIMUM_ZOOM,
            }
        ],
        "version": "1",
    }


def _validate_metadata(
    metadata: object,
    source: _BoundarySource,
    evidence: VectorToolchainEvidence,
    *,
    build_receipt_sha256: str,
) -> Mapping[str, Any]:
    expected = _expected_metadata(source, evidence, build_receipt_sha256=build_receipt_sha256)
    prohibited = {"generator_options", "tilestats", "timestamp", "hostname", "host"}
    if metadata != expected or type(metadata) is not dict or prohibited.intersection(metadata):
        raise ScienceContractError("Boundary PMTiles metadata differs from the safe allow-list")
    return metadata


def _read_pmtiles_header(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()[: _PMTILES_HEADER.size]
        values = _PMTILES_HEADER.unpack(payload)
    except (OSError, struct.error) as exc:
        raise ScienceContractError("Boundary PMTiles v3 header cannot be decoded") from exc
    if values[0] != b"PMTiles":
        raise ScienceContractError("Boundary PMTiles magic differs from PMTiles v3")
    compression = {1: "none", 2: "gzip", 3: "brotli", 4: "zstd"}
    tile_types = {1: "mvt", 2: "png", 3: "jpeg", 4: "webp", 5: "avif"}
    return {
        "spec_version": values[1],
        "root_dir_offset": values[2],
        "root_dir_bytes": values[3],
        "json_metadata_offset": values[4],
        "json_metadata_bytes": values[5],
        "leaf_dirs_offset": values[6],
        "leaf_dirs_bytes": values[7],
        "tile_data_offset": values[8],
        "tile_data_bytes": values[9],
        "addressed_tiles_count": values[10],
        "tile_entries_count": values[11],
        "tile_contents_count": values[12],
        "clustered": {0: False, 1: True}.get(values[13], f"unknown:{values[13]}"),
        "internal_compression": compression.get(values[14], f"unknown:{values[14]}"),
        "tile_compression": compression.get(values[15], f"unknown:{values[15]}"),
        "tile_type": tile_types.get(values[16], f"unknown:{values[16]}"),
        "minzoom": values[17],
        "maxzoom": values[18],
        "bounds": [value / 10_000_000 for value in values[19:23]],
        "center": [values[24] / 10_000_000, values[25] / 10_000_000, values[23]],
    }


def _validate_header(
    header: Mapping[str, Any],
    reported: object,
    source: _BoundarySource,
    *,
    byte_size: int,
) -> None:
    expected = {
        "spec_version": 3,
        "clustered": True,
        "internal_compression": "gzip",
        "tile_compression": "gzip",
        "tile_type": "mvt",
        "minzoom": _MINIMUM_ZOOM,
        "maxzoom": _MAXIMUM_ZOOM,
        "bounds": list(source.specification.header_bounds),
        "center": list(source.specification.header_center),
    }
    if any(header.get(key) != value for key, value in expected.items()):
        raise ScienceContractError("Boundary PMTiles header differs from generation parameters")
    reported_keys = ("tile_compression", "tile_type", "minzoom", "maxzoom", "bounds", "center")
    if reported != {key: header[key] for key in reported_keys}:
        raise ScienceContractError("PMTiles tool and decoded header disagree")
    observed_counts = tuple(
        header.get(key)
        for key in ("tile_contents_count", "tile_entries_count", "addressed_tiles_count")
    )
    if any(type(value) is not int or value <= 0 for value in observed_counts):
        raise ScienceContractError("Boundary PMTiles tile counts are inconsistent")
    counts = cast(tuple[int, int, int], observed_counts)
    if not counts[0] <= counts[1] <= counts[2]:
        raise ScienceContractError("Boundary PMTiles tile counts are inconsistent")
    root_end = header.get("root_dir_offset", 0) + header.get("root_dir_bytes", 0)
    metadata_end = header.get("json_metadata_offset", 0) + header.get("json_metadata_bytes", 0)
    leaf_end = header.get("leaf_dirs_offset", 0) + header.get("leaf_dirs_bytes", 0)
    tile_end = header.get("tile_data_offset", 0) + header.get("tile_data_bytes", 0)
    if (
        header.get("root_dir_offset") != _PMTILES_HEADER.size
        or header.get("json_metadata_offset") != root_end
        or header.get("leaf_dirs_offset") != metadata_end
        or header.get("tile_data_offset") != leaf_end
        or tile_end != byte_size
        or any(
            type(header.get(key)) is not int or header[key] <= 0
            for key in ("root_dir_bytes", "json_metadata_bytes", "tile_data_bytes")
        )
    ):
        raise ScienceContractError("Boundary PMTiles sections are not canonical and contiguous")
