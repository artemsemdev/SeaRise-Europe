"""Deterministic engineering-only GeoParquet boundary artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from searise_pipeline.science.contracts import ScienceContractError

_STATUS = "selected-scope-approximation"
_PURPOSE = "product-eligibility-only"
_CONTRACT_PATH = "src/pipeline/science/geography-rules.json"
_CONTRACT_SHA256 = "195b7128ba5483a633e8e35187541b0b884ed8644ac40ae8191c9db9935becf5"
_RIGHTS = {
    "attribution": "Made with Natural Earth.",
    "licence": "Natural Earth public domain dedication",
    "spdx": "LicenseRef-Natural-Earth-Public-Domain",
    "url": "https://www.naturalearthdata.com/about/terms-of-use/",
}
_ARROW_SCHEMA_KEY = b"ARROW:schema"
_CANONICAL_ARROW_SCHEMAS = {
    "support-boundary": zlib.decompress(
        base64.b64decode(
            b"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"
        )
    ),
    "coastal-boundary": zlib.decompress(
        base64.b64decode(
            b"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"
        )
    ),
}
_CANONICAL_ARROW_SCHEMA_SHA256 = {
    "support-boundary": "190ff0496c3010425e2a6797dd04cf28703b72ed1b4a8a4f45826a1c21c30eb9",
    "coastal-boundary": "0c8c5af859e353d5aea4ba3c618938172c1657599227497295761b291b2565d6",
}
if any(
    hashlib.sha256(payload).hexdigest() != _CANONICAL_ARROW_SCHEMA_SHA256[role]
    for role, payload in _CANONICAL_ARROW_SCHEMAS.items()
):
    raise RuntimeError("Canonical boundary Arrow schema payload is corrupt")


@dataclass(frozen=True)
class _BoundarySpecification:
    boundary_id: str
    role: str
    input_path: str
    input_sha256: str
    output_path: str
    name: str
    version: str
    source_asset_id: str
    properties: Mapping[str, Any]


_SPECIFICATIONS = {
    "support-boundary": _BoundarySpecification(
        boundary_id="europe-support",
        role="support-boundary",
        input_path="data/geometry/europe.geojson",
        input_sha256="dd98b938df00fc582bbd220b913d96b1fd19bab812e2e9d95ecc4b409330a385",
        output_path="boundaries/europe.parquet",
        name="europe",
        version="natural-earth-5.1.1-explicit-scope-v2",
        source_asset_id="admin-0-countries",
        properties={
            "hazardExtentClaim": False,
            "source": "natural-earth-10m/5.1.1:admin-0-countries",
            "status": _STATUS,
            "version": "natural-earth-5.1.1-explicit-scope-v2",
        },
    ),
    "coastal-boundary": _BoundarySpecification(
        boundary_id="coastal-analysis-zone",
        role="coastal-boundary",
        input_path="data/geometry/coastal_analysis_zone.geojson",
        input_sha256="aa08f31460c80cbe35eefb44c6f8feb22b90727840eda3734241d707d7a910d9",
        output_path="boundaries/coastal-analysis-zone.parquet",
        name="coastal_analysis_zone",
        version="natural-earth-5.1.1-25km-scope-v2",
        source_asset_id="ocean",
        properties={
            "hazardExtentClaim": False,
            "role": _PURPOSE,
            "source": "natural-earth-10m/5.1.1:ocean",
            "status": _STATUS,
            "version": "natural-earth-5.1.1-25km-scope-v2",
        },
    ),
}


@dataclass(frozen=True)
class BoundaryGeoParquetEvidence:
    """Byte and lineage identity for one packaged boundary."""

    path: str
    role: str
    byte_size: int
    sha256: str
    source_sha256: str
    row_count: int


Coordinate = tuple[float, float]
Ring = tuple[Coordinate, ...]
Polygon = tuple[Ring, ...]
MultiPolygon = tuple[Polygon, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _specification(role: str) -> _BoundarySpecification:
    try:
        return _SPECIFICATIONS[role]
    except KeyError as exc:
        raise ScienceContractError(f"Unsupported boundary role: {role}") from exc


def _coordinate(value: Any) -> Coordinate:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) not in (int, float) for item in value)
    ):
        raise ScienceContractError("Boundary coordinates must be two finite numbers")
    longitude, latitude = (float(value[0]), float(value[1]))
    if (
        not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        raise ScienceContractError("Boundary coordinate lies outside OGC:CRS84")
    return round(longitude, 6), round(latitude, 6)


def _signed_area(points: Sequence[Coordinate]) -> float:
    return sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, (*points[1:], points[0]))
    ) / 2


def _canonical_ring(value: Any, *, exterior: bool) -> Ring:
    if not isinstance(value, list):
        raise ScienceContractError("Boundary ring must be an array")
    points: list[Coordinate] = []
    for raw_point in value:
        point = _coordinate(raw_point)
        if not points or points[-1] != point:
            points.append(point)
    if len(points) < 4 or points[0] != points[-1]:
        raise ScienceContractError("Boundary ring must be closed")
    points.pop()
    if len(points) < 3 or len(set(points)) != len(points):
        raise ScienceContractError("Boundary ring must have unique non-closing vertices")
    area = _signed_area(points)
    if area == 0:
        raise ScienceContractError("Boundary ring must have non-zero area")
    if (area > 0) != exterior:
        points.reverse()
    start = min(range(len(points)), key=points.__getitem__)
    normalized = points[start:] + points[:start]
    return tuple((*normalized, normalized[0]))


def _canonical_polygon(value: Any) -> Polygon:
    if not isinstance(value, list) or not value:
        raise ScienceContractError("Boundary polygon must contain an exterior ring")
    exterior = _canonical_ring(value[0], exterior=True)
    interiors = sorted(_canonical_ring(ring, exterior=False) for ring in value[1:])
    return (exterior, *interiors)


def _canonical_geometry(source_path: Path, specification: _BoundarySpecification) -> MultiPolygon:
    if _sha256(source_path) != specification.input_sha256:
        raise ScienceContractError("Boundary input SHA-256 differs from the immutable pin")
    try:
        document = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScienceContractError("Boundary input is not readable GeoJSON") from exc
    if (
        set(document) != {"features", "name", "type"}
        or document.get("type") != "FeatureCollection"
    ):
        raise ScienceContractError("Boundary input must be the canonical FeatureCollection")
    features = document.get("features")
    if (
        document.get("name") != specification.name
        or not isinstance(features, list)
        or len(features) != 1
    ):
        raise ScienceContractError("Boundary feature inventory differs from the immutable pin")
    feature = features[0]
    if (
        not isinstance(feature, dict)
        or set(feature) != {"geometry", "properties", "type"}
        or feature.get("type") != "Feature"
        or feature.get("properties") != specification.properties
    ):
        raise ScienceContractError("Boundary feature metadata differs from the immutable pin")
    geometry = feature.get("geometry")
    if (
        not isinstance(geometry, dict)
        or set(geometry) != {"coordinates", "type"}
        or geometry.get("type") != "MultiPolygon"
        or not isinstance(geometry.get("coordinates"), list)
    ):
        raise ScienceContractError("Boundary geometry must be one MultiPolygon")
    polygons = tuple(
        sorted(_canonical_polygon(polygon) for polygon in geometry["coordinates"])
    )
    if not polygons:
        raise ScienceContractError("Boundary MultiPolygon cannot be empty")
    return polygons


def _wkb(geometry: MultiPolygon) -> bytes:
    output = bytearray(struct.pack("<BII", 1, 6, len(geometry)))
    for polygon in geometry:
        output.extend(struct.pack("<BII", 1, 3, len(polygon)))
        for ring in polygon:
            output.extend(struct.pack("<I", len(ring)))
            for longitude, latitude in ring:
                output.extend(struct.pack("<dd", longitude, latitude))
    return bytes(output)


def _bounds(geometry: MultiPolygon) -> list[float]:
    coordinates = [point for polygon in geometry for ring in polygon for point in ring]
    longitudes, latitudes = zip(*coordinates)
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def _dependencies() -> tuple[Any, Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        import pyproj
    except ImportError as exc:
        raise ScienceContractError(
            "Boundary GeoParquet requires the pinned PyArrow and PROJ toolchain"
        ) from exc
    if (
        pa.__version__ != "16.1.0"
        or pyproj.__version__ != "3.6.1"
        or pyproj.proj_version_str != "9.3.0"
    ):
        raise ScienceContractError("Boundary GeoParquet toolchain differs from the pin")
    return pa, pq, pyproj


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _boundary_metadata(specification: _BoundarySpecification) -> dict[str, Any]:
    return {
        "canonical": False,
        "engineeringUse": "engineering-only",
        "hazardExtentClaim": False,
        "lineage": {
            "contract": {"path": _CONTRACT_PATH, "sha256": _CONTRACT_SHA256},
            "input": {
                "path": specification.input_path,
                "sha256": specification.input_sha256,
            },
            "source": {
                "assetId": specification.source_asset_id,
                "sourceId": "natural-earth-10m",
                "version": "5.1.1",
            },
        },
        "normalization": "crs84-multipolygon-rings-v1",
        "production": False,
        "publicationEligible": False,
        "purpose": _PURPOSE,
        "rights": _RIGHTS,
        "role": specification.role,
        "schemaVersion": "1.0.0",
        "status": _STATUS,
        "version": specification.version,
    }


def _schema(specification: _BoundarySpecification, geometry: MultiPolygon) -> Any:
    pa, _, pyproj = _dependencies()
    crs = pyproj.CRS.from_user_input("OGC:CRS84").to_json_dict()
    if crs.get("id") != {"authority": "OGC", "code": "CRS84"}:
        raise ScienceContractError("Pinned PROJ cannot represent OGC:CRS84 exactly")
    geo = {
        "columns": {
            "geometry": {
                "bbox": _bounds(geometry),
                "crs": crs,
                "encoding": "WKB",
                "geometry_types": ["MultiPolygon"],
            }
        },
        "creator": {"library": "searise-pipeline", "version": "0.1.0"},
        "primary_column": "geometry",
        "version": "1.1.0",
    }
    fields = [
        pa.field("boundary_id", pa.string(), nullable=False),
        pa.field("role", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("purpose", pa.string(), nullable=False),
        pa.field("version", pa.string(), nullable=False),
        pa.field("publication_eligible", pa.bool_(), nullable=False),
        pa.field("canonical", pa.bool_(), nullable=False),
        pa.field("production", pa.bool_(), nullable=False),
        pa.field("hazard_extent_claim", pa.bool_(), nullable=False),
        pa.field("geometry", pa.binary(), nullable=False),
    ]
    return pa.schema(
        fields,
        metadata={
            b"geo": _json_bytes(geo),
            b"searise:boundary": _json_bytes(_boundary_metadata(specification)),
        },
    )


def _table(specification: _BoundarySpecification, geometry: MultiPolygon) -> Any:
    pa, _, _ = _dependencies()
    values = [
        [specification.boundary_id],
        [specification.role],
        [_STATUS],
        [_PURPOSE],
        [specification.version],
        [False],
        [False],
        [False],
        [False],
        [_wkb(geometry)],
    ]
    schema = _schema(specification, geometry)
    arrays = [pa.array(value, type=field.type) for value, field in zip(values, schema)]
    return pa.Table.from_arrays(arrays, schema=schema)


def _serialized_bytes(table: Any, specification: _BoundarySpecification) -> bytes:
    pa, pq, _ = _dependencies()
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=9,
        data_page_version="1.0",
        row_group_size=1,
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )
    payload = bytes(sink.getvalue().to_pybytes())
    metadata = pq.ParquetFile(pa.BufferReader(payload)).metadata.metadata or {}
    try:
        generated_schema = metadata[_ARROW_SCHEMA_KEY]
    except KeyError as exc:
        raise ScienceContractError("Boundary GeoParquet Arrow schema is missing") from exc
    canonical_schema = _CANONICAL_ARROW_SCHEMAS[specification.role]
    if len(generated_schema) != len(canonical_schema):
        raise ScienceContractError("Boundary Arrow schema length differs from the pin")
    if payload.count(generated_schema) != 1:
        raise ScienceContractError("Boundary Arrow schema payload is not unique")
    if generated_schema != canonical_schema:
        payload = payload.replace(generated_schema, canonical_schema, 1)
    canonical_metadata = (
        pq.ParquetFile(pa.BufferReader(payload)).metadata.metadata or {}
    )
    if canonical_metadata.get(_ARROW_SCHEMA_KEY) != canonical_schema:
        raise ScienceContractError("Boundary Arrow schema canonicalization failed")
    return payload


def write_boundary_geoparquet(
    source_path: Path,
    output_path: Path,
    *,
    role: str,
) -> BoundaryGeoParquetEvidence:
    """Package one exact checked-in engineering boundary as GeoParquet 1.1."""
    specification = _specification(role)
    geometry = _canonical_geometry(source_path, specification)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_serialized_bytes(_table(specification, geometry), specification))
    validate_boundary_geoparquet(output_path, source_path, role=role)
    return BoundaryGeoParquetEvidence(
        path=specification.output_path,
        role=role,
        byte_size=output_path.stat().st_size,
        sha256=_sha256(output_path),
        source_sha256=specification.input_sha256,
        row_count=1,
    )


def validate_boundary_geoparquet(
    path: Path,
    source_path: Path,
    *,
    role: str,
) -> None:
    """Reject any drift in source, geometry, status, rights, schema, or encoding."""
    specification = _specification(role)
    geometry = _canonical_geometry(source_path, specification)
    expected = _table(specification, geometry)
    pa, pq, _ = _dependencies()
    try:
        parquet = pq.ParquetFile(path)
        actual = pq.read_table(path)
    except (OSError, pa.ArrowException) as exc:
        raise ScienceContractError("Boundary GeoParquet is unreadable") from exc
    if parquet.metadata.num_rows != 1 or parquet.metadata.num_row_groups != 1:
        raise ScienceContractError("Boundary GeoParquet row inventory differs")
    row_group = parquet.metadata.row_group(0)
    if row_group.num_rows != 1 or any(
        row_group.column(index).compression != "ZSTD"
        for index in range(row_group.num_columns)
    ):
        raise ScienceContractError("Boundary GeoParquet compression or row groups differ")
    if actual.schema != expected.schema:
        raise ScienceContractError("Boundary GeoParquet schema or metadata differs")
    if actual["geometry"][0].as_py() != _wkb(geometry):
        raise ScienceContractError("Boundary GeoParquet geometry differs from canonical source")
    if actual.column_names != expected.column_names or actual.to_pydict() != expected.to_pydict():
        raise ScienceContractError("Boundary GeoParquet row values differ from the pin")
    metadata = parquet.metadata.metadata or {}
    if (
        metadata.get(b"geo") != expected.schema.metadata[b"geo"]
        or metadata.get(b"searise:boundary")
        != expected.schema.metadata[b"searise:boundary"]
        or path.read_bytes().count(b"ARROW:schema") != 1
    ):
        raise ScienceContractError("Boundary GeoParquet metadata differs from the pin")
    if path.read_bytes() != _serialized_bytes(expected, specification):
        raise ScienceContractError("Boundary GeoParquet bytes or compression differ from the pin")
