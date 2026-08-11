"""Deterministic visual-only PMTiles for reviewed engineering boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, cast

from searise_pipeline.science.contracts import ScienceContractError

from .boundary_geoparquet import validate_boundary_geoparquet
from .pmtiles import (
    VectorToolchainEvidence,
    _canonicalize_tippecanoe_gzip_headers,
    _run,
    validate_vector_toolchain,
)

_MINIMUM_ZOOM = 0
_MAXIMUM_ZOOM = 6
_FULL_DETAIL = 17
_BUFFER = 0
_VISUAL_SEGMENT_LENGTH_DEGREES = 0.10
_VISUAL_EQUIVALENCE_LIMIT_DEGREES = 1e-12
_STATUS = "selected-scope-approximation"
_PURPOSE = "product-eligibility-only"
_SHAPELY_VERSION = "2.0.7"
_MVT_EXTENT = 2**_FULL_DETAIL
_QUANTIZATION_STEP_DEGREES = 360 / (2**_MAXIMUM_ZOOM * _MVT_EXTENT)
_PER_STAGE_ERROR_DEGREES = _QUANTIZATION_STEP_DEGREES / 2
_COORDINATE_ERROR_DEGREES = 2 * _PER_STAGE_ERROR_DEGREES
_GEOMETRY_TOLERANCE_DEGREES = math.sqrt(2) * _COORDINATE_ERROR_DEGREES
# One ULP prevents a mathematically exact threshold from failing after binary
# arithmetic without changing either declared semantic tolerance.
_COORDINATE_COMPARISON_LIMIT_DEGREES = math.nextafter(
    _COORDINATE_ERROR_DEGREES, math.inf
)
_GEOMETRY_COMPARISON_LIMIT_DEGREES = math.nextafter(
    _GEOMETRY_TOLERANCE_DEGREES, math.inf
)
_PMTILES_HEADER = struct.Struct("<7sB11Q6B4iB2i")


@dataclass(frozen=True)
class _BoundarySpecification:
    role: str
    boundary_id: str
    source_path: str
    source_byte_size: int
    source_sha256: str
    output_path: str
    layer_id: str
    feature_id: int
    header_bounds: tuple[float, float, float, float]
    header_center: tuple[float, float, int]


_BOUNDARIES = {
    "support-boundary": _BoundarySpecification(
        role="support-boundary",
        boundary_id="europe-support",
        source_path="boundaries/europe.parquet",
        source_byte_size=267676,
        source_sha256="531c6042a33cf3be9bc3ea340b0e557cb66bafb34de7954db0d7e47be90d35a9",
        output_path="boundaries/europe.pmtiles",
        layer_id="support_boundary",
        feature_id=1,
        header_bounds=(-28.851018, 30.021176, 40.1733959, 74.536347),
        header_center=(25.3125, 38.788894, 6),
    ),
    "coastal-boundary": _BoundarySpecification(
        role="coastal-boundary",
        boundary_id="coastal-analysis-zone",
        source_path="boundaries/coastal-analysis-zone.parquet",
        source_byte_size=667750,
        source_sha256="3ba4d5eaba24d1202482bc33fd64fde8ce54b7ff1dd1456990d3c8cfece43366",
        output_path="boundaries/coastal-analysis-zone.pmtiles",
        layer_id="coastal_boundary",
        feature_id=2,
        header_bounds=(-28.850986, 30.021211, 38.3141589, 74.536318),
        header_center=(25.3125, 38.788894, 6),
    ),
}
_DECODED_FEATURE_IDS = {"support-boundary": 1, "coastal-boundary": 2}


@dataclass(frozen=True)
class _BoundarySource:
    specification: _BoundarySpecification
    geometry: Any
    version: str
    lineage: Mapping[str, Any]
    rights: Mapping[str, Any]


@dataclass(frozen=True)
class BoundaryPmtilesEvidence:
    """Identity and decoded parity for one boundary visualization archive."""

    path: str
    byte_size: int
    sha256: str
    source_geoparquet_byte_size: int
    source_geoparquet_sha256: str
    decoded_fragment_count: int
    geometry_parity: Mapping[str, Any]
    visual_intermediary: Mapping[str, Any]
    header: Mapping[str, Any]
    metadata: Mapping[str, Any]
    toolchain: VectorToolchainEvidence


@dataclass(frozen=True)
class BoundaryVectorToolPaths:
    """Paths required to prove and run one pinned vector toolchain."""

    tippecanoe: Path
    decode: Path
    pmtiles: Path
    tippecanoe_source: Path
    tippecanoe_build_receipt: Path
    pmtiles_distribution_asset: Path
    platform: str

    def validate(self, contract: Mapping[str, Any]) -> VectorToolchainEvidence:
        return validate_vector_toolchain(
            tippecanoe_path=self.tippecanoe,
            decode_path=self.decode,
            pmtiles_path=self.pmtiles,
            tippecanoe_source_archive_path=self.tippecanoe_source,
            tippecanoe_build_receipt_path=self.tippecanoe_build_receipt,
            pmtiles_distribution_asset_path=self.pmtiles_distribution_asset,
            pmtiles_distribution_platform=self.platform,
            contract=contract,
        )


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


def _writer_feature_properties(source: _BoundarySource) -> dict[str, object]:
    specification = source.specification
    return {
        "analytical_lookup": "prohibited",
        "boundary_id": specification.boundary_id,
        "canonical": False,
        "hazard_extent_claim": False,
        "production": False,
        "publication_eligible": False,
        "purpose": _PURPOSE,
        "role": specification.role,
        "source_geoparquet_byte_size": specification.source_byte_size,
        "source_geoparquet_sha256": specification.source_sha256,
        "status": _STATUS,
        "version": source.version,
        "visual_only": True,
    }


def _expected_decoded_properties(source: _BoundarySource) -> dict[str, object]:
    specification = source.specification
    return {
        "analytical_lookup": "prohibited",
        "boundary_id": specification.boundary_id,
        "canonical": False,
        "hazard_extent_claim": False,
        "production": False,
        "publication_eligible": False,
        "purpose": "product-eligibility-only",
        "role": specification.role,
        "source_geoparquet_byte_size": specification.source_byte_size,
        "source_geoparquet_sha256": specification.source_sha256,
        "status": "selected-scope-approximation",
        "version": source.version,
        "visual_only": True,
    }


def _write_ndjson(path: Path, source: _BoundarySource) -> Mapping[str, Any]:
    from shapely.geometry import mapping

    geometry, evidence = _visual_geometry(source.geometry)
    feature = {
        "geometry": mapping(geometry),
        "id": source.specification.feature_id,
        "properties": _writer_feature_properties(source),
        "type": "Feature",
    }
    path.write_text(
        json.dumps(feature, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return evidence


def _tippecanoe_options(
    source: _BoundarySource, *, full_detail: int = _FULL_DETAIL
) -> list[str]:
    return [
        "--force",
        f"--layer={source.specification.layer_id}",
        "--projection=EPSG:4326",
        f"--minimum-zoom={_MINIMUM_ZOOM}",
        f"--maximum-zoom={_MAXIMUM_ZOOM}",
        f"--full-detail={full_detail}",
        f"--buffer={_BUFFER}",
        "--no-feature-limit",
        "--no-tile-size-limit",
        "--no-line-simplification",
        "--no-tiny-polygon-reduction",
        "--no-tiny-polygon-reduction-at-maximum-zoom",
        "--preserve-input-order",
    ]


def _generation_parameters(source: _BoundarySource) -> dict[str, object]:
    return {
        "angular_error_model": {
            "comparison": (
                "symmetric-vertex-to-boundary-discrete-distance-plus-per-axis-envelope"
            ),
            "coordinate_error_degrees": _COORDINATE_ERROR_DEGREES,
            "geometry_tolerance_degrees": _GEOMETRY_TOLERANCE_DEGREES,
            "maximum_rounding_stages": 2,
            "model": "web-mercator-mvt-quantization-plus-tile-clipping",
            "per_stage_coordinate_error_degrees": _PER_STAGE_ERROR_DEGREES,
            "quantization_step_degrees": _QUANTIZATION_STEP_DEGREES,
        },
        "gzip_canonicalization": {
            "method": "tippecanoe-tile-member-os-byte-rewrite",
            "operating_system_byte": 255,
        },
        "pmtiles_metadata_edit": "canonical-json-replacement",
        "visual_intermediary": {
            "canonical_source_modified": False,
            "coordinate_space": "EPSG:4326-degrees",
            "maximum_segment_length_degrees": _VISUAL_SEGMENT_LENGTH_DEGREES,
            "method": "shapely-segmentize",
            "purpose": "bound-nonlinear-web-mercator-chord-error",
            "source": source.specification.source_path,
            "topology_required": "identical-polygon-and-interior-ring-counts",
        },
        "tippecanoe_options": _tippecanoe_options(source),
    }


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
    properties = _expected_decoded_properties(source)
    return {
        "attribution": source.rights["attribution"],
        "description": (f"SeaRise {specification.boundary_id} engineering boundary; visual only"),
        "format": "pbf",
        "generator": f"tippecanoe v{evidence.tippecanoe_version}",
        "name": f"SeaRise {specification.boundary_id}",
        "searise": {
            "analytical_lookup": properties["analytical_lookup"],
            "canonical": False,
            "generation": _generation_parameters(source),
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
                    key: (
                        "Boolean"
                        if type(value) is bool
                        else "Number"
                        if type(value) is int
                        else "String"
                    )
                    for key, value in properties.items()
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


def _polygon_topology(geometry: Any) -> tuple[int, int]:
    if geometry.geom_type == "Polygon":
        polygons = [geometry]
    elif geometry.geom_type == "MultiPolygon":
        polygons = list(geometry.geoms)
    else:
        return (-1, -1)
    return len(polygons), sum(len(polygon.interiors) for polygon in polygons)


def _polygon_rings(geometry: Any) -> list[Any]:
    if geometry.geom_type == "Polygon":
        polygons = [geometry]
    elif geometry.geom_type == "MultiPolygon":
        polygons = list(geometry.geoms)
    else:
        return []
    return [
        ring
        for polygon in polygons
        for ring in (polygon.exterior, *polygon.interiors)
    ]


def _boundary_vertices_and_segments(geometry: Any) -> tuple[list[tuple[float, float]], list[Any]]:
    try:
        from shapely.geometry import LineString
    except ImportError as exc:
        raise ScienceContractError("Boundary parity requires Shapely") from exc
    vertices: list[tuple[float, float]] = []
    segments: list[Any] = []
    for ring in _polygon_rings(geometry):
        coordinates = [(float(x), float(y)) for x, y, *_ in ring.coords]
        vertices.extend(coordinates)
        segments.extend(
            LineString((start, end))
            for start, end in zip(coordinates, coordinates[1:])
            if start != end
        )
    if not vertices or not segments:
        raise ScienceContractError("Boundary parity requires polygon boundary segments")
    return vertices, segments


def _indexed_directed_vertex_boundary_distance(first: Any, second: Any) -> tuple[float, int]:
    """Return exact vertex-to-segment distances using an independent spatial index."""
    try:
        from shapely import STRtree, distance, points
    except ImportError as exc:
        raise ScienceContractError("Boundary parity requires Shapely") from exc
    vertices, _ = _boundary_vertices_and_segments(first)
    _, segments = _boundary_vertices_and_segments(second)
    query_points = points(vertices)
    tree = STRtree(segments)
    nearest = tree.nearest(query_points)
    distances = distance(query_points, tree.geometries.take(nearest))
    return max(float(value) for value in distances), len(vertices)


def _symmetric_vertex_boundary_distances(first: Any, second: Any) -> Mapping[str, Any]:
    first_to_second, first_vertices = _indexed_directed_vertex_boundary_distance(
        first, second
    )
    second_to_first, second_vertices = _indexed_directed_vertex_boundary_distance(
        second, first
    )
    return {
        "comparison": "symmetric-vertex-to-boundary-discrete-distance",
        "firstToSecondMaximumDegrees": first_to_second,
        "firstVertexCount": first_vertices,
        "secondToFirstMaximumDegrees": second_to_first,
        "secondVertexCount": second_vertices,
        "symmetricMaximumDegrees": max(first_to_second, second_to_first),
    }


def _topology_evidence(geometry: Any) -> Mapping[str, int]:
    polygon_count, interior_ring_count = _polygon_topology(geometry)
    return {
        "interiorRingCount": interior_ring_count,
        "polygonCount": polygon_count,
    }


def _visual_geometry(geometry: Any) -> tuple[Any, Mapping[str, Any]]:
    """Densify only the visual intermediary and prove source-equivalent topology."""
    shapely = _require_shapely()
    visual = shapely.segmentize(
        geometry,
        max_segment_length=_VISUAL_SEGMENT_LENGTH_DEGREES,
    )
    source_topology = _polygon_topology(geometry)
    visual_topology = _polygon_topology(visual)
    if (
        not visual.is_valid
        or visual.is_empty
        or source_topology != visual_topology
    ):
        raise ScienceContractError("Visual boundary segmentization changed topology")
    distances = _symmetric_vertex_boundary_distances(geometry, visual)
    envelope_differences = [
        abs(observed - expected)
        for observed, expected in zip(visual.bounds, geometry.bounds)
    ]
    if (
        distances["symmetricMaximumDegrees"]
        > _VISUAL_EQUIVALENCE_LIMIT_DEGREES
        or max(envelope_differences) > _VISUAL_EQUIVALENCE_LIMIT_DEGREES
    ):
        raise ScienceContractError("Visual boundary segmentization changed geometry")
    return visual, {
        "canonicalSourceModified": False,
        "coordinateSpace": "EPSG:4326-degrees",
        "maximumSegmentLengthDegrees": _VISUAL_SEGMENT_LENGTH_DEGREES,
        "method": "shapely-segmentize",
        "sourceTopology": _topology_evidence(geometry),
        "visualTopology": _topology_evidence(visual),
        "equivalenceLimitDegrees": _VISUAL_EQUIVALENCE_LIMIT_DEGREES,
        "envelopeAxisDifferencesDegrees": envelope_differences,
        "distance": distances,
    }


def _decoded_geometry_parity(source: Any, decoded: Any) -> Mapping[str, Any]:
    if (
        not decoded.is_valid
        or decoded.is_empty
        or _polygon_topology(decoded) != _polygon_topology(source)
    ):
        raise ScienceContractError("Decoded boundary PMTiles geometry parity differs")
    distances = _symmetric_vertex_boundary_distances(source, decoded)
    envelope_differences = [
        abs(observed - expected)
        for observed, expected in zip(decoded.bounds, source.bounds)
    ]
    if (
        max(envelope_differences) > _COORDINATE_COMPARISON_LIMIT_DEGREES
        or distances["symmetricMaximumDegrees"]
        > _GEOMETRY_COMPARISON_LIMIT_DEGREES
    ):
        raise ScienceContractError("Decoded boundary PMTiles geometry parity differs")
    return {
        "comparison": (
            "symmetric-vertex-to-boundary-discrete-distance-plus-per-axis-envelope"
        ),
        "coordinateLimitDegrees": _COORDINATE_ERROR_DEGREES,
        "distance": distances,
        "envelopeAxisDifferencesDegrees": envelope_differences,
        "geometryLimitDegrees": _GEOMETRY_TOLERANCE_DEGREES,
        "sourceTopology": _topology_evidence(source),
        "decodedTopology": _topology_evidence(decoded),
    }


def _decoded_fragments(
    document: object,
    source: _BoundarySource,
    *,
    extent: int = _MVT_EXTENT,
) -> list[Any]:
    _require_shapely()
    try:
        from shapely.geometry import shape
    except ImportError as exc:
        raise ScienceContractError("Decoded PMTiles parity requires Shapely") from exc
    if type(document) is not dict or type(document.get("features")) is not list:
        raise ScienceContractError("Decoded boundary PMTiles document is malformed")
    fragments: list[Any] = []
    for tile in document["features"]:
        if type(tile) is not dict or type(tile.get("features")) is not list:
            raise ScienceContractError("Decoded boundary PMTiles tile is malformed")
        for layer in tile["features"]:
            if (
                type(layer) is not dict
                or layer.get("properties")
                != {
                    "extent": extent,
                    "layer": source.specification.layer_id,
                    "version": 2,
                }
                or type(layer.get("features")) is not list
            ):
                raise ScienceContractError("Decoded boundary PMTiles layer differs")
            for feature in layer["features"]:
                if (
                    type(feature) is not dict
                    or feature.get("id") != _DECODED_FEATURE_IDS[source.specification.role]
                    or type(feature.get("id")) is not int
                    or feature.get("properties") != _expected_decoded_properties(source)
                ):
                    raise ScienceContractError("Decoded boundary PMTiles properties differ")
                try:
                    fragments.append(shape(feature["geometry"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ScienceContractError(
                        "Decoded boundary PMTiles geometry is malformed"
                    ) from exc
    if not fragments:
        raise ScienceContractError("Decoded boundary PMTiles contains no boundary fragments")
    return fragments


def _validate_decoded_document(
    document: object, source: _BoundarySource
) -> tuple[int, Mapping[str, Any]]:
    try:
        from shapely import union_all
    except ImportError as exc:
        raise ScienceContractError("Decoded PMTiles parity requires Shapely") from exc
    fragments = _decoded_fragments(document, source)
    merged = union_all(fragments)
    parity = _decoded_geometry_parity(source.geometry, merged)
    return len(fragments), parity


def evaluate_boundary_profile_matrix(
    source_geoparquet_path: Path,
    source_geojson_path: Path,
    *,
    role: str,
    contract: Mapping[str, Any],
    tools: BoundaryVectorToolPaths,
) -> list[Mapping[str, Any]]:
    """Compare the approved detail/segmentization candidates with pinned tools."""
    source = _load_source(source_geoparquet_path, source_geojson_path, role=role)
    tools.validate(contract)
    try:
        from shapely import union_all
        from shapely.geometry import mapping
    except ImportError as exc:
        raise ScienceContractError("Boundary profile selection requires Shapely") from exc
    profiles: list[Mapping[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="searise-boundary-profile-") as temp:
        staging = Path(temp)
        for full_detail in (14, 17):
            for segment_length in (None, _VISUAL_SEGMENT_LENGTH_DEGREES):
                profile_id = (
                    f"detail-{full_detail}-"
                    + ("source-vertices" if segment_length is None else "segmentize-0.10")
                )
                if segment_length is None:
                    visual = source.geometry
                    visual_evidence: Mapping[str, Any] = {
                        "canonicalSourceModified": False,
                        "method": "none",
                        "sourceTopology": _topology_evidence(source.geometry),
                        "visualTopology": _topology_evidence(source.geometry),
                    }
                else:
                    visual, visual_evidence = _visual_geometry(source.geometry)
                feature = {
                    "geometry": mapping(visual),
                    "id": source.specification.feature_id,
                    "properties": _writer_feature_properties(source),
                    "type": "Feature",
                }
                ndjson = staging / f"{profile_id}.ndjson"
                archive = staging / f"{profile_id}.pmtiles"
                ndjson.write_text(
                    json.dumps(feature, sort_keys=True, separators=(",", ":"))
                    + "\n",
                    encoding="utf-8",
                )
                _run(
                    [
                        str(tools.tippecanoe),
                        f"--output={archive}",
                        *_tippecanoe_options(source, full_detail=full_detail),
                        str(ndjson),
                    ]
                )
                _run([str(tools.pmtiles), "verify", str(archive)])
                try:
                    decoded = json.loads(
                        _run(
                            [
                                str(tools.decode),
                                f"-Z{_MAXIMUM_ZOOM}",
                                f"-z{_MAXIMUM_ZOOM}",
                                str(archive),
                            ]
                        )
                    )
                except json.JSONDecodeError as exc:
                    raise ScienceContractError(
                        "Boundary profile diagnostic cannot decode its PMTiles"
                    ) from exc
                fragments = _decoded_fragments(
                    decoded,
                    source,
                    extent=2**full_detail,
                )
                merged = union_all(fragments)
                if not merged.is_valid or merged.is_empty:
                    raise ScienceContractError(
                        "Boundary profile diagnostic produced invalid geometry"
                    )
                distances = _symmetric_vertex_boundary_distances(
                    source.geometry, merged
                )
                envelope_differences = [
                    abs(observed - expected)
                    for observed, expected in zip(
                        merged.bounds, source.geometry.bounds
                    )
                ]
                coordinate_limit = 360 / (2**_MAXIMUM_ZOOM * 2**full_detail)
                geometry_limit = math.sqrt(2) * coordinate_limit
                topology_matches = _polygon_topology(merged) == _polygon_topology(
                    source.geometry
                )
                passed = (
                    topology_matches
                    and max(envelope_differences)
                    <= math.nextafter(coordinate_limit, math.inf)
                    and distances["symmetricMaximumDegrees"]
                    <= math.nextafter(geometry_limit, math.inf)
                )
                profiles.append(
                    {
                        "artifact": {
                            "byteSize": archive.stat().st_size,
                            "sha256": _sha256(archive),
                        },
                        "decodedFragmentCount": len(fragments),
                        "decodedTopology": _topology_evidence(merged),
                        "envelopeAxisDifferencesDegrees": envelope_differences,
                        "fullDetail": full_detail,
                        "geometryLimitDegrees": geometry_limit,
                        "geometryParity": distances,
                        "mvtExtent": 2**full_detail,
                        "officialPmtilesVerify": "passed",
                        "passed": passed,
                        "profileId": profile_id,
                        "sourceTopology": _topology_evidence(source.geometry),
                        "topologyMatches": topology_matches,
                        "visualIntermediary": visual_evidence,
                    }
                )
    selected = next(
        profile
        for profile in profiles
        if profile["fullDetail"] == _FULL_DETAIL
        and profile["visualIntermediary"]["method"] == "shapely-segmentize"
    )
    if not selected["passed"]:
        raise ScienceContractError("Selected boundary PMTiles profile did not pass")
    if any(profile["passed"] for profile in profiles if profile["fullDetail"] == 14):
        raise ScienceContractError(
            "A lower-detail boundary PMTiles profile passed; review the selected profile"
        )
    return profiles


def validate_boundary_pmtiles(
    path: Path,
    source_geoparquet_path: Path,
    source_geojson_path: Path,
    *,
    role: str,
    contract: Mapping[str, Any],
    tools: BoundaryVectorToolPaths,
) -> BoundaryPmtilesEvidence:
    """Validate structure and decoded visual parity against exact GeoParquet."""
    source = _load_source(source_geoparquet_path, source_geojson_path, role=role)
    evidence = tools.validate(contract)
    build_receipt_sha256 = _sha256(tools.tippecanoe_build_receipt)
    _run([str(tools.pmtiles), "verify", str(path)])
    try:
        metadata = json.loads(_run([str(tools.pmtiles), "show", str(path), "--metadata"]))
        reported_header = json.loads(_run([str(tools.pmtiles), "show", str(path), "--header-json"]))
    except json.JSONDecodeError as exc:
        raise ScienceContractError("Boundary PMTiles metadata or header is malformed") from exc
    validated_metadata = _validate_metadata(
        metadata,
        source,
        evidence,
        build_receipt_sha256=build_receipt_sha256,
    )
    header = _read_pmtiles_header(path)
    _validate_header(header, reported_header, source, byte_size=path.stat().st_size)
    try:
        decoded = json.loads(
            _run(
                [
                    str(tools.decode),
                    f"-Z{_MAXIMUM_ZOOM}",
                    f"-z{_MAXIMUM_ZOOM}",
                    str(path),
                ]
            )
        )
    except json.JSONDecodeError as exc:
        raise ScienceContractError("Decoded boundary PMTiles JSON is malformed") from exc
    fragments, geometry_parity = _validate_decoded_document(decoded, source)
    _, visual_intermediary = _visual_geometry(source.geometry)
    return BoundaryPmtilesEvidence(
        path=source.specification.output_path,
        byte_size=path.stat().st_size,
        sha256=_sha256(path),
        source_geoparquet_byte_size=source.specification.source_byte_size,
        source_geoparquet_sha256=source.specification.source_sha256,
        decoded_fragment_count=fragments,
        geometry_parity=geometry_parity,
        visual_intermediary=visual_intermediary,
        header=header,
        metadata=validated_metadata,
        toolchain=evidence,
    )


def write_boundary_pmtiles(
    source_geoparquet_path: Path,
    source_geojson_path: Path,
    path: Path,
    *,
    role: str,
    contract: Mapping[str, Any],
    tools: BoundaryVectorToolPaths,
) -> BoundaryPmtilesEvidence:
    """Build one visual archive only from the exact PR #214 GeoParquet."""
    source = _load_source(source_geoparquet_path, source_geojson_path, role=role)
    evidence = tools.validate(contract)
    build_receipt_sha256 = _sha256(tools.tippecanoe_build_receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="searise-boundary-pmtiles-", dir=path.parent) as temp:
        staging = Path(temp)
        ndjson = staging / "boundary.ndjson"
        archive = staging / "boundary.pmtiles"
        metadata_path = staging / "metadata.json"
        _write_ndjson(ndjson, source)
        metadata_path.write_text(
            json.dumps(
                _expected_metadata(
                    source,
                    evidence,
                    build_receipt_sha256=build_receipt_sha256,
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        _run(
            [
                str(tools.tippecanoe),
                f"--output={archive}",
                *_tippecanoe_options(source),
                str(ndjson),
            ]
        )
        _run([str(tools.pmtiles), "edit", str(archive), f"--metadata={metadata_path}"])
        _canonicalize_tippecanoe_gzip_headers(archive)
        validated = validate_boundary_pmtiles(
            archive,
            source_geoparquet_path,
            source_geojson_path,
            role=role,
            contract=contract,
            tools=tools,
        )
        os.replace(archive, path)
    return validated
