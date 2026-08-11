"""Deterministic, non-publishing GeoParquet serialization of one spatial stage."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections import namedtuple
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Mapping

from . import full_source_stage as source_stage
from . import normalized_catalogue_stage as catalogue_stage
from . import spatial_classification_stage as spatial_stage
from .catalogue import INCLUDED_FEATURE_CODES, CataloguePlace
from .spatial_classification import _PRODUCTION_GEOMETRY_IDENTITIES, CORE_CAPITAL_FEATURE_CODES

ROW_GROUP_SIZE = 4096
_RELEASE = re.compile(r"^searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}$")
_PLACE = re.compile(r"^geonames:([1-9][0-9]*)$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_HEX = re.compile(r"^[a-f0-9]{64}$")
_DISTANCE_METHOD = "epsg3035-planar-whole-meter-half-even-v1"
_ENVELOPE = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v3/"
    "artifact-envelope.schema.json"
)
_PLACE_SCHEMA = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v3/place.schema.json"
)
_FIELDS_SHA256 = "4cfac102ca87fb50bbf2df67389ed4cb57546bb850a65c3280ba74f2537b053a"
_FIELDS = (
    ("id", "utf8", False),
    ("source_spelling", "utf8", False),
    ("canonical_name", "utf8", False),
    ("canonical_name_role", "utf8", False),
    ("canonical_language", "utf8", True),
    ("canonical_script", "utf8", True),
    ("ascii_name", "utf8", False),
    ("alternate_names_json", "utf8", False),
    ("country_code", "utf8", False),
    ("admin1_code", "utf8", True),
    ("admin1_name", "utf8", True),
    ("longitude", "float64", False),
    ("latitude", "float64", False),
    ("population", "int64", True),
    ("feature_code", "utf8", False),
    ("source_updated_at", "utf8", False),
    ("support_geometry_id", "utf8", False),
    ("support_geometry_version", "utf8", False),
    ("support_geometry_sha256", "utf8", False),
    ("coastal_geometry_id", "utf8", False),
    ("coastal_geometry_version", "utf8", False),
    ("coastal_geometry_sha256", "utf8", False),
    ("shoreline_geometry_id", "utf8", False),
    ("shoreline_geometry_version", "utf8", False),
    ("shoreline_geometry_sha256", "utf8", False),
    ("spatial_predicate", "utf8", False),
    ("distance_method_version", "utf8", False),
    ("distance_to_coast_m", "int64", False),
    ("is_coastal", "bool", False),
    ("catalog_membership_json", "utf8", False),
    ("lineage_json", "utf8", False),
    ("geometry", "binary", False),
)
# fmt: off
_RECEIPT_KEYS = frozenset("schemaVersion materializationPerformed publicationEligible candidate deterministicIdentity".split())  # noqa: E501
_CANDIDATE_KEYS = frozenset("spatialStageSchemaVersion logicalHashVersion publicationClaim canonicalGeometryClaim hazardExtentClaim scientificApprovalClaim ownerApprovalClaim inputCatalogue geometry method toolchain counts logicalHashes deterministicIdentity".split())  # noqa: E501
_COUNT_KEYS = frozenset("normalizedPlaces classifiedPlaces spatialRejections europeCoreMemberships europeCoastalMemberships outsideSupportRejections".split())  # noqa: E501
_GEOMETRY_KEYS = frozenset("contractSha256 dataProvenanceClass geometryStatus publicationEligible geometries".split())  # noqa: E501
_ITEM_KEYS = frozenset("role id version path sha256 predicate".split())
# fmt: on


class SpatialGeoParquetError(ValueError):
    """The exact spatial stage cannot produce the requested GeoParquet bytes."""


@dataclass(frozen=True)
class SpatialGeoParquetEvidence:
    row_count: int
    source_rows_sha256: str
    logical_rows_sha256: str
    parquet_sha256: str
    spatial_receipt_sha256: str
    spatial_candidate_identity: str
    artifact_envelope: Mapping[str, Any]


_Authority = namedtuple("_Authority", "receipt_sha256 receipt_identity candidate_identity row_count source_hash rejection_hash counts geometry spatial_identity")  # noqa: E501  # fmt: skip


def _canonical(value: Any) -> bytes:
    try:
        return source_stage._canonical_json(value).encode("utf-8")
    except (ValueError, UnicodeEncodeError) as exc:
        raise SpatialGeoParquetError("GeoParquet value cannot be canonicalized") from exc


def _tools() -> tuple[Any, Any, Any]:
    duckdb, pa = source_stage._load_tools()
    try:
        import pyarrow.parquet as pq
        import pyproj
    except ImportError as exc:
        raise SpatialGeoParquetError("GeoParquet requires pinned PyArrow and PROJ") from exc
    if (pyproj.__version__, pyproj.proj_version_str) != ("3.6.1", "9.3.0"):
        raise SpatialGeoParquetError("GeoParquet toolchain differs from the pin")
    return duckdb, pa, pq


def _receipt(raw: bytes) -> _Authority:
    try:
        document = source_stage._strict_json(raw, "spatial receipt")
    except Exception as exc:
        raise SpatialGeoParquetError(f"spatial receipt is invalid: {exc}") from exc
    if type(document) is not dict or raw != _canonical(document) + b"\n":
        raise SpatialGeoParquetError("spatial receipt is not canonical JSON")
    candidate = document.get("candidate")
    if (
        set(document) != _RECEIPT_KEYS
        or document["schemaVersion"] != 1
        or document["materializationPerformed"] is not True
        or document["publicationEligible"] is not False
        or type(candidate) is not dict
        or set(candidate) != _CANDIDATE_KEYS
        or document != spatial_stage.spatial_receipt(candidate)
    ):
        raise SpatialGeoParquetError("spatial receipt structure or identity differs")
    unsigned = {key: value for key, value in candidate.items() if key != "deterministicIdentity"}
    if (
        candidate["deterministicIdentity"]
        != hashlib.sha256(_canonical(unsigned) + b"\n").hexdigest()
    ):
        raise SpatialGeoParquetError("spatial candidate deterministic identity differs")
    geometry, method = candidate["geometry"], candidate["method"]
    false_claims = (
        "publicationClaim",
        "canonicalGeometryClaim",
        "hazardExtentClaim",
        "scientificApprovalClaim",
        "ownerApprovalClaim",
    )
    if any(candidate[key] is not False for key in false_claims):
        raise SpatialGeoParquetError("spatial authority broadens a publication or science claim")
    if (
        candidate["spatialStageSchemaVersion"] != spatial_stage.SPATIAL_STAGE_SCHEMA_VERSION
        or candidate["logicalHashVersion"] != "canonical-jsonl-v1"
        or type(candidate["inputCatalogue"]) is not dict
        or type(geometry) is not dict
        or set(geometry) != _GEOMETRY_KEYS
        or geometry["dataProvenanceClass"] != "real-source"
        or geometry["geometryStatus"] != "selected-scope-approximation"
        or geometry["publicationEligible"] is not False
        or not _HEX.fullmatch(geometry["contractSha256"])
        or type(method) is not dict
        or method.get("predicate") != "ST_Covers"
        or method.get("metricCrs") != "EPSG:3035"
        or method.get("distanceMethodVersion") != _DISTANCE_METHOD
        or not _HEX.fullmatch(method.get("classificationSqlSha256", ""))
    ):
        raise SpatialGeoParquetError("spatial method or geometry authority differs")
    items = geometry["geometries"]
    if type(items) is not list or [item.get("role") for item in items] != [
        "support",
        "coastal",
        "shoreline",
    ]:
        raise SpatialGeoParquetError("spatial geometry inventory differs")
    for item in items:
        if (
            type(item) is not dict
            or set(item) != _ITEM_KEYS
            or any(type(item[key]) is not str or not item[key] for key in item)
            or not _HEX.fullmatch(item["sha256"])
        ):
            raise SpatialGeoParquetError("spatial geometry identity differs")
    observed = tuple(tuple(item[key] for key in ("role", "id", "version", "path", "sha256", "predicate")) for item in items)  # noqa: E501  # fmt: skip
    if observed != _PRODUCTION_GEOMETRY_IDENTITIES:
        raise SpatialGeoParquetError("spatial geometry differs from the full production identity")
    counts, hashes = candidate["counts"], candidate["logicalHashes"]
    if (
        type(counts) is not dict
        or set(counts) != _COUNT_KEYS
        or any(type(value) is not int or value < 0 for value in counts.values())
        or counts["classifiedPlaces"] < 1
        or counts["normalizedPlaces"] != counts["classifiedPlaces"] + counts["spatialRejections"]
        or type(hashes) is not dict
        or set(hashes) != {"classifiedPlaces", "spatialRejections"}
        or any(type(value) is not str or not _HEX.fullmatch(value) for value in hashes.values())
    ):
        raise SpatialGeoParquetError("spatial counts or logical hashes differ")
    identities = {
        f"{item['role']}Geometry": {
            "artifactId": item["id"],
            "version": item["version"],
            "sha256": item["sha256"],
        }
        for item in items
    }
    identities.update(predicate="covers", distanceMethodVersion=_DISTANCE_METHOD)
    return _Authority(
        hashlib.sha256(raw).hexdigest(),
        document["deterministicIdentity"],
        candidate["deterministicIdentity"],
        counts["classifiedPlaces"],
        hashes["classifiedPlaces"],
        hashes["spatialRejections"],
        counts,
        geometry,
        identities,
    )


def _memberships(population: int | None, feature_code: str, coastal: bool) -> list[str]:
    core = (
        population is not None and population >= 500
    ) or feature_code in CORE_CAPITAL_FEATURE_CODES
    return (["europe-core"] if core else []) + (["europe-coastal"] if coastal else [])


def _row(document: str, authority: _Authority) -> tuple[dict[str, Any], int]:
    try:
        value = source_stage._strict_json(document, "spatial place")
        if _canonical(value).decode() != document or set(value) != {
            "catalogMembership",
            "coastalCovers",
            "distanceToShorelineMeters",
            "place",
            "supportCovers",
        }:
            raise SpatialGeoParquetError("spatial place document is not canonical")
        place = catalogue_stage._decode(CataloguePlace, value["place"], "spatial place.place")
    except SpatialGeoParquetError:
        raise
    except Exception as exc:
        raise SpatialGeoParquetError(f"spatial place document is invalid: {exc}") from exc
    match = _PLACE.fullmatch(place.id) if type(place.id) is str else None
    source_id = int(match.group(1)) if match else 0
    if (
        not match
        or value["supportCovers"] is not True
        or type(value["coastalCovers"]) is not bool
        or type(value["distanceToShorelineMeters"]) is not int
        or value["distanceToShorelineMeters"] < 0
        or value["catalogMembership"]
        != _memberships(place.population, place.feature_code, value["coastalCovers"])
        or type(place.source_spelling) is not str
        or not place.source_spelling
        or type(place.ascii_name) is not str
        or not place.ascii_name
        or not place.canonical_name.value
        or not place.lineage
        or place.lineage[0].source_record_id != source_id
        or not _COUNTRY.fullmatch(place.country_code)
        or place.feature_code not in INCLUDED_FEATURE_CODES
        or type(place.longitude) is not float
        or type(place.latitude) is not float
        or not math.isfinite(place.longitude)
        or not math.isfinite(place.latitude)
        or not -180 <= place.longitude <= 180
        or not -90 <= place.latitude <= 90
        or (
            place.population is not None
            and (type(place.population) is not int or place.population < 0)
        )
    ):
        raise SpatialGeoParquetError("settlement spatial row differs from public v3")
    canonical = place.canonical_name
    alternates = [
        {"language": item.language, "role": "alternate", "script": item.script, "value": item.value}
        for item in place.alternate_names
    ]
    lineage = [
        {
            "sourceFile": item.source_file,
            "sourceId": "geonames",
            "sourceLine": item.source_line,
            "sourceRecordId": item.source_record_id,
            "sourceRelease": item.source_release,
            "sourceSha256": item.source_sha256,
        }
        for item in place.lineage
    ]
    geometries = {item["role"]: item for item in authority.geometry["geometries"]}
    row = {
        "id": place.id,
        "source_spelling": place.source_spelling,
        "canonical_name": canonical.value,
        "canonical_name_role": "canonical",
        "canonical_language": canonical.language,
        "canonical_script": canonical.script,
        "ascii_name": place.ascii_name,
        "alternate_names_json": _canonical(alternates).decode(),
        "country_code": place.country_code,
        "admin1_code": place.admin1_code,
        "admin1_name": place.admin1_name,
        "longitude": place.longitude,
        "latitude": place.latitude,
        "population": place.population,
        "feature_code": place.feature_code,
        "source_updated_at": place.source_updated_at.isoformat(),
        **{
            f"{role}_geometry_{field}": geometries[role][target]
            for role in ("support", "coastal", "shoreline")
            for field, target in (("id", "id"), ("version", "version"), ("sha256", "sha256"))
        },
        "spatial_predicate": "covers",
        "distance_method_version": _DISTANCE_METHOD,
        "distance_to_coast_m": value["distanceToShorelineMeters"],
        "is_coastal": value["coastalCovers"],
        "catalog_membership_json": _canonical(value["catalogMembership"]).decode(),
        "lineage_json": _canonical(lineage).decode(),
        "geometry": struct.pack("<BIdd", 1, 1, place.longitude, place.latitude),
    }
    return row, source_id


def _verify_database(connection: Any, authority: _Authority) -> None:
    spatial_stage._validate_schema(connection)
    observed = dict.fromkeys(_COUNT_KEYS, 0)
    hashes = {name: hashlib.sha256() for name in ("spatial_places", "spatial_rejections")}
    for table in ("spatial_places", "spatial_rejections"):
        previous = 0
        for values in spatial_stage._stored_rows(connection, table):
            geoname_id, place_id, document = values[0], values[1], values[-1]
            match = _PLACE.fullmatch(place_id) if type(place_id) is str else None
            if (
                not match
                or type(geoname_id) is not int
                or int(match.group(1)) != geoname_id
                or geoname_id <= previous
            ):
                raise SpatialGeoParquetError(f"{table} keys are duplicate, unordered, or invalid")
            previous = geoname_id
            if table == "spatial_places":
                _, source_id = _row(document, authority)
                if source_id != geoname_id:
                    raise SpatialGeoParquetError("spatial place key differs from its document")
                data = source_stage._strict_json(document, "spatial place")
                observed["classifiedPlaces"] += 1
                observed["europeCoreMemberships"] += int("europe-core" in data["catalogMembership"])
                observed["europeCoastalMemberships"] += int(
                    "europe-coastal" in data["catalogMembership"]
                )
            else:
                data = source_stage._strict_json(document, "spatial rejection")
                if (
                    _canonical(data).decode() != document
                    or set(data) != {"lineage", "placeId", "reason"}
                    or data["placeId"] != place_id
                    or data["reason"] != "outside-support"
                    or values[2] != "outside-support"
                ):
                    raise SpatialGeoParquetError(
                        "spatial rejection differs from its exact contract"
                    )
                observed["spatialRejections"] += 1
                observed["outsideSupportRejections"] += 1
            hashes[table].update(document.encode() + b"\n")
    observed["normalizedPlaces"] = observed["classifiedPlaces"] + observed["spatialRejections"]
    if (
        observed != authority.counts
        or hashes["spatial_places"].hexdigest() != authority.source_hash
        or hashes["spatial_rejections"].hexdigest() != authority.rejection_hash
    ):
        raise SpatialGeoParquetError(
            "spatial database counts or classified hash differ from receipt"
        )


def _envelope(release_id: str, authority: _Authority) -> Mapping[str, Any]:
    fields = [dict(zip(("name", "type", "nullable"), field)) for field in _FIELDS]
    if hashlib.sha256(_canonical(fields)).hexdigest() != _FIELDS_SHA256:
        raise SpatialGeoParquetError("GeoParquet Arrow fields differ from public v3")
    return {
        "$schema": _ENVELOPE,
        "schemaVersion": "3.0.0",
        "dataReleaseId": release_id,
        "dataProvenanceClass": authority.geometry["dataProvenanceClass"],
        "artifactType": "settlement-geoparquet",
        "mediaType": "application/vnd.apache.parquet",
        "formatVersion": "1.1.0",
        "placeSchema": _PLACE_SCHEMA,
        "spatialIdentity": authority.spatial_identity,
        "geometryStatus": authority.geometry["geometryStatus"],
        "canonicalGeometryClaim": False,
        "hazardExtentClaim": False,
        "scientificApprovalClaim": False,
        "ownerApprovalClaim": False,
        "publicationEligible": False,
        "rowCount": authority.row_count,
        "arrowFieldsCanonicalization": "lexicographic-key-json-v1",
        "arrowFieldsJsonSha256": _FIELDS_SHA256,
        "arrowFields": fields,
        "geometry": {
            "primaryColumn": "geometry",
            "encoding": "WKB",
            "crs": "OGC:CRS84",
            "geometryType": "Point",
        },
    }


def _schema(release_id: str, authority: _Authority, pa: Any) -> Any:
    import pyproj

    crs = pyproj.CRS.from_user_input("OGC:CRS84").to_json_dict()
    if crs.get("id") != {"authority": "OGC", "code": "CRS84"}:
        raise SpatialGeoParquetError("pinned PROJ cannot represent OGC:CRS84")
    geo = {
        "columns": {"geometry": {"crs": crs, "encoding": "WKB", "geometry_types": ["Point"]}},
        "creator": {"library": "searise-pipeline", "version": "0.1.0"},
        "primary_column": "geometry",
        "version": "1.1.0",
    }
    receipt = {
        "receiptSha256": authority.receipt_sha256,
        "deterministicIdentity": authority.receipt_identity,
        "candidateDeterministicIdentity": authority.candidate_identity,
        "classifiedPlacesSha256": authority.source_hash,
        "publicationClaim": False,
        "scientificApprovalClaim": False,
    }
    serialization = {
        "ordering": "numeric-geonames-id-ascending",
        "sourceRowsCanonicalization": "spatial-stage-canonical-jsonl-v1",
        "logicalRowsCanonicalization": "lexicographic-key-json-lines-v1",
        "rowGroupSize": ROW_GROUP_SIZE,
        "compression": "zstd-9",
        "parquetFormat": "2.6",
        "pyarrow": pa.__version__,
    }
    kinds = {
        "utf8": pa.string(),
        "int64": pa.int64(),
        "float64": pa.float64(),
        "bool": pa.bool_(),
        "binary": pa.binary(),
    }
    return pa.schema(
        [pa.field(name, kinds[kind], nullable=nullable) for name, kind, nullable in _FIELDS],
        metadata={
            b"geo": _canonical(geo),
            b"searise:settlement": _canonical(_envelope(release_id, authority)),
            b"searise:spatial-receipt": _canonical(receipt),
            b"searise:serialization": _canonical(serialization),
        },
    )


def _logical(row: Mapping[str, Any]) -> bytes:
    return (
        _canonical({key: value.hex() if key == "geometry" else value for key, value in row.items()})
        + b"\n"
    )


def _stream_hash(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


@contextmanager
def _source(database: Path, receipt: Path, work_dir: Path) -> Iterator[tuple[Any, _Authority]]:
    try:
        with ExitStack() as stack:
            root, snapshots = stack.enter_context(
                spatial_stage._validation_snapshots(
                    {"spatial.duckdb": database, "spatial-receipt.json": receipt}, work_dir
                )
            )
            authority = _receipt(spatial_stage._read_asset(snapshots["spatial-receipt.json"]))
            duckdb, _, _ = _tools()
            connection = stack.enter_context(
                duckdb.connect(str(root / "spatial.duckdb"), read_only=True)
            )
            _verify_database(connection, authority)
            yield connection, authority
    except SpatialGeoParquetError:
        raise
    except Exception as exc:
        raise SpatialGeoParquetError(f"spatial input authority failed: {exc}") from exc


def _validate_stream(
    stream: BinaryIO,
    connection: Any,
    authority: _Authority,
    *,
    expected_release: str | None = None,
) -> SpatialGeoParquetEvidence:
    _, pa, pq = _tools()
    parquet_hash = _stream_hash(stream)
    try:
        parquet = pq.ParquetFile(stream)
        metadata = parquet.schema_arrow.metadata or {}
        envelope = json.loads(metadata[b"searise:settlement"])
        release_id = envelope["dataReleaseId"]
    except (
        OSError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        pa.ArrowException,
    ) as exc:
        raise SpatialGeoParquetError("GeoParquet schema or metadata is unreadable") from exc
    if (
        not isinstance(release_id, str)
        or not _RELEASE.fullmatch(release_id)
        or (expected_release is not None and release_id != expected_release)
    ):
        raise SpatialGeoParquetError("GeoParquet data-release identity differs")
    if not parquet.schema_arrow.equals(_schema(release_id, authority, pa), check_metadata=True):
        raise SpatialGeoParquetError("GeoParquet Arrow schema or metadata differs")
    expected_groups = [ROW_GROUP_SIZE] * (authority.row_count // ROW_GROUP_SIZE)
    if authority.row_count % ROW_GROUP_SIZE:
        expected_groups.append(authority.row_count % ROW_GROUP_SIZE)
    if parquet.metadata.num_row_groups != len(expected_groups):
        raise SpatialGeoParquetError("GeoParquet row-group count differs")
    groups = [parquet.metadata.row_group(index) for index in range(len(expected_groups))]
    if (
        parquet.metadata.num_rows != authority.row_count
        or [group.num_rows for group in groups] != expected_groups
        or any(
            group.column(index).compression != "ZSTD"
            for group in groups
            for index in range(group.num_columns)
        )
    ):
        raise SpatialGeoParquetError("GeoParquet rows, row groups, or compression differ")
    source_digest, logical_digest = hashlib.sha256(), hashlib.sha256()
    previous = rows = 0
    sources = iter(spatial_stage._stored_rows(connection, "spatial_places"))
    try:
        for batch in parquet.iter_batches(batch_size=ROW_GROUP_SIZE):
            for row in batch.to_pylist():
                try:
                    geoname_id, _, document = next(sources)
                except StopIteration as exc:
                    raise SpatialGeoParquetError(
                        "GeoParquet fabricates rows beyond its spatial authority"
                    ) from exc
                expected, current = _row(document, authority)
                if current <= previous or current != geoname_id or row != expected:
                    raise SpatialGeoParquetError(
                        "GeoParquet row differs from unique ordered spatial source"
                    )
                previous = current
                source_digest.update(document.encode() + b"\n")
                logical_digest.update(_logical(row))
                rows += 1
        if next(sources, None) is not None:
            raise SpatialGeoParquetError("GeoParquet truncates its spatial authority")
    finally:
        sources.close()
    if rows != authority.row_count or source_digest.hexdigest() != authority.source_hash:
        raise SpatialGeoParquetError("GeoParquet rows truncate or fabricate the spatial authority")
    if _stream_hash(stream) != parquet_hash:
        raise SpatialGeoParquetError("GeoParquet bytes changed during validation")
    return SpatialGeoParquetEvidence(
        rows,
        source_digest.hexdigest(),
        logical_digest.hexdigest(),
        parquet_hash,
        authority.receipt_sha256,
        authority.candidate_identity,
        envelope,
    )


def serialize_spatial_geoparquet(
    spatial_database: Path,
    spatial_receipt: Path,
    stream: BinaryIO,
    *,
    data_release_id: str,
    work_dir: Path,
) -> SpatialGeoParquetEvidence:
    """Serialize one exact descriptor-bound spatial pair to a caller-owned stream."""
    if not _RELEASE.fullmatch(data_release_id):
        raise SpatialGeoParquetError("GeoParquet data-release identity is invalid")
    with _source(spatial_database, spatial_receipt, work_dir) as (connection, authority):
        _, pa, pq = _tools()
        schema = _schema(data_release_id, authority, pa)
        stream.seek(0)
        stream.truncate(0)
        batch = []
        with pq.ParquetWriter(
            stream,
            schema,
            compression="zstd",
            compression_level=9,
            data_page_version="1.0",
            use_dictionary=False,
            version="2.6",
            write_statistics=True,
        ) as writer:
            for geoname_id, _, document in spatial_stage._stored_rows(connection, "spatial_places"):
                row, current = _row(document, authority)
                if current != geoname_id:
                    raise SpatialGeoParquetError("spatial source key changed during serialization")
                batch.append(row)
                if len(batch) == ROW_GROUP_SIZE:
                    writer.write_table(pa.Table.from_pylist(batch, schema=schema), ROW_GROUP_SIZE)
                    batch.clear()
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema), ROW_GROUP_SIZE)
        return _validate_stream(stream, connection, authority, expected_release=data_release_id)


def validate_spatial_geoparquet(
    stream: BinaryIO,
    spatial_database: Path,
    spatial_receipt: Path,
    *,
    work_dir: Path,
) -> SpatialGeoParquetEvidence:
    """Validate GeoParquet against the exact descriptor-bound spatial pair."""
    with _source(spatial_database, spatial_receipt, work_dir) as (connection, authority):
        return _validate_stream(stream, connection, authority)
