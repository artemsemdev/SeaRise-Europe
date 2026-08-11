"""Streaming, receipt-bound browser search projections from a spatial candidate."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from . import full_source_stage as source_stage
from . import normalized_catalogue_stage as catalogue_stage
from . import spatial_asset_authority as authority
from . import spatial_classification_stage as spatial_stage
from . import spatial_stage_runner as stage_runner
from .catalogue import CataloguePlace
from .spatial_classification import (
    CORE_CAPITAL_FEATURE_CODES,
    GeometryBinding,
    GeometryBindings,
    SpatialClassificationError,
    _validate_geometry,
)

SEARCH_PROJECTION_SCHEMA_VERSION = "settlement-search-projection-v1"
MAX_LINE_BYTES = 1024 * 1024

_HEADER_KIND = "settlement-search-projection-header"
_DOCUMENT_KIND = "settlement-search-projection-document"
_FOOTER_KIND = "settlement-search-projection-footer"
_FALSE_CLAIMS = (
    "publicationClaim",
    "canonicalGeometryClaim",
    "hazardExtentClaim",
    "scientificApprovalClaim",
    "ownerApprovalClaim",
)
_PROJECTION_FALSE_CLAIMS = (*_FALSE_CLAIMS, "productionClaim", "signingClaim")
_CANDIDATE_KEYS = {
    "spatialStageSchemaVersion",
    "logicalHashVersion",
    *_FALSE_CLAIMS,
    "inputCatalogue",
    "geometry",
    "method",
    "toolchain",
    "counts",
    "logicalHashes",
    "deterministicIdentity",
}
_COUNT_KEYS = {
    "normalizedPlaces",
    "classifiedPlaces",
    "spatialRejections",
    "europeCoreMemberships",
    "europeCoastalMemberships",
    "outsideSupportRejections",
}
_HASH_KEYS = {"classifiedPlaces", "spatialRejections"}
_GEOMETRY_KEYS = {
    "contractSha256",
    "dataProvenanceClass",
    "geometryStatus",
    "publicationEligible",
    "geometries",
}
_GEOMETRY_ITEM_KEYS = {"role", "id", "version", "path", "sha256", "predicate"}


class SearchProjectionError(ValueError):
    """A spatial source or search projection is malformed, changed, or inconsistent."""


def _geometry(value: object) -> GeometryBindings:
    if type(value) is not dict or set(value) != _GEOMETRY_KEYS:
        raise SearchProjectionError("spatial geometry identity differs")
    entries = value["geometries"]
    if type(entries) is not list or len(entries) != 3:
        raise SearchProjectionError("spatial geometry identity differs")
    try:
        items = tuple(
            GeometryBinding(**entry)
            for entry in entries
            if type(entry) is dict and set(entry) == _GEOMETRY_ITEM_KEYS
        )
        if len(items) != 3:
            raise ValueError("geometry entries differ")
        geometry = GeometryBindings(
            data_provenance_class=value["dataProvenanceClass"],
            geometry_status=value["geometryStatus"],
            publication_eligible=value["publicationEligible"],
            support=items[0],
            coastal=items[1],
            shoreline=items[2],
            contract_sha256=value["contractSha256"],
        )
        _validate_geometry(geometry)
        return geometry
    except (SpatialClassificationError, TypeError, ValueError) as exc:
        raise SearchProjectionError("spatial geometry identity differs") from exc


def _reject_wal(directory: Any, database_name: str) -> None:
    try:
        authority._path_stat(directory.descriptor, f"{database_name}.wal")
    except FileNotFoundError:
        return
    raise SearchProjectionError("spatial source retained a DuckDB WAL")


@contextmanager
def _snapshots(paths: Mapping[str, Path], work_dir: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    database = paths["spatial.duckdb"]
    with ExitStack() as stack:
        parent = stack.enter_context(
            authority._open_directory_path(database.parent, "spatial source directory")
        )
        _reject_wal(parent, database.name)
        root, assets = stack.enter_context(spatial_stage._validation_snapshots(paths, work_dir))
        yield root, assets
        _reject_wal(parent, database.name)
        authority._assert_directory(parent)


def _assert_no_spill(connection: Any) -> None:
    actual = connection.execute(
        "SELECT current_setting('threads'), current_setting('memory_limit'), "
        "current_setting('temp_directory')"
    ).fetchone()
    if actual != (1, "1.0 GiB", ""):
        raise SearchProjectionError("search projection DuckDB limits were not retained")


def _configure_connection(connection: Any) -> None:
    connection.execute("SET threads=1")
    connection.execute(f"SET memory_limit='{source_stage.MEMORY_LIMIT}'")
    connection.execute("SET temp_directory=''")
    _assert_no_spill(connection)


def _canonical(value: Any) -> bytes:
    return (source_stage._canonical_json(value) + "\n").encode("utf-8")


def _strict_line(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = source_stage._strict_json(raw, label)
        if type(value) is not dict or _canonical(value) != raw + b"\n":
            raise SearchProjectionError(f"{label} is not canonical JSON")
        return value
    except SearchProjectionError:
        raise
    except Exception as exc:
        raise SearchProjectionError(f"{label} is invalid") from exc


def _asset_lines(asset: Any, label: str) -> Iterator[bytes]:
    """Yield bounded canonical NDJSON lines from one descriptor-bound asset."""

    buffer = bytearray()
    offset = 0
    line_number = 0
    while offset < asset.size:
        chunk = os.pread(asset.descriptor, min(64 * 1024, asset.size - offset), offset)
        if not chunk:
            raise SearchProjectionError(f"{label} changed while read")
        offset += len(chunk)
        buffer.extend(chunk)
        if len(buffer) > MAX_LINE_BYTES and b"\n" not in buffer:
            raise SearchProjectionError(f"{label} contains an oversized line")
        while (end := buffer.find(b"\n")) >= 0:
            if end > MAX_LINE_BYTES:
                raise SearchProjectionError(f"{label} contains an oversized line")
            line = bytes(buffer[:end])
            del buffer[: end + 1]
            line_number += 1
            if not line or b"\r" in line:
                raise SearchProjectionError(f"{label} line {line_number} is not canonical NDJSON")
            yield line
    if buffer:
        raise SearchProjectionError(f"{label} must end with a newline")
    authority._assert_asset(asset)


def _candidate(receipt_asset: Any) -> tuple[dict[str, Any], str]:
    raw = spatial_stage._read_asset(receipt_asset)
    receipt = source_stage._strict_json(raw, "spatial receipt")
    if type(receipt) is not dict or raw != _canonical(receipt):
        raise SearchProjectionError("spatial receipt is not canonical JSON")
    unsigned_receipt = {
        key: value for key, value in receipt.items() if key != "deterministicIdentity"
    }
    if (
        set(receipt)
        != {
            "schemaVersion",
            "materializationPerformed",
            "publicationEligible",
            "candidate",
            "deterministicIdentity",
        }
        or receipt["schemaVersion"] != 1
        or receipt["materializationPerformed"] is not True
        or receipt["publicationEligible"] is not False
        or receipt["deterministicIdentity"]
        != hashlib.sha256(_canonical(unsigned_receipt)).hexdigest()
        or type(receipt["candidate"]) is not dict
    ):
        raise SearchProjectionError("spatial receipt contract differs")
    candidate = receipt["candidate"]
    unsigned_candidate = {
        key: value for key, value in candidate.items() if key != "deterministicIdentity"
    }
    if (
        set(candidate) != _CANDIDATE_KEYS
        or candidate["spatialStageSchemaVersion"] != spatial_stage.SPATIAL_STAGE_SCHEMA_VERSION
        or candidate["logicalHashVersion"] != "canonical-jsonl-v1"
        or any(candidate[name] is not False for name in _FALSE_CLAIMS)
        or candidate["deterministicIdentity"]
        != hashlib.sha256(_canonical(unsigned_candidate)).hexdigest()
        or type(candidate["counts"]) is not dict
        or set(candidate["counts"]) != _COUNT_KEYS
        or type(candidate["logicalHashes"]) is not dict
        or set(candidate["logicalHashes"]) != _HASH_KEYS
    ):
        raise SearchProjectionError("spatial candidate identity differs")
    if any(type(value) is not int or value < 0 for value in candidate["counts"].values()):
        raise SearchProjectionError("spatial candidate counts are invalid")
    if any(
        type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef")
        for value in candidate["logicalHashes"].values()
    ):
        raise SearchProjectionError("spatial candidate hashes are invalid")
    _geometry(candidate["geometry"])
    return candidate, hashlib.sha256(raw).hexdigest()


def _spatial_documents(connection: Any) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    previous = 0
    for geoname_id, place_id, raw in spatial_stage._stored_rows(connection, "spatial_places"):
        document = source_stage._strict_json(raw, "spatial place document")
        if type(document) is not dict or source_stage._canonical_json(document) != raw:
            raise SearchProjectionError("spatial place document is not canonical JSON")
        expected = {
            "catalogMembership",
            "coastalCovers",
            "distanceToShorelineMeters",
            "place",
            "supportCovers",
        }
        if set(document) != expected or document["supportCovers"] is not True:
            raise SearchProjectionError("spatial place document fields differ")
        place = catalogue_stage._decode(CataloguePlace, document["place"], "spatial place")
        if (
            type(geoname_id) is not int
            or geoname_id <= previous
            or place.id != place_id
            or place_id != f"geonames:{geoname_id}"
            or not place.lineage
            or place.lineage[0].source_record_id != geoname_id
            or type(document["coastalCovers"]) is not bool
            or type(document["distanceToShorelineMeters"]) is not int
            or document["distanceToShorelineMeters"] < 0
            or type(document["catalogMembership"]) is not list
        ):
            raise SearchProjectionError("spatial place keys, ordering, or values differ")
        memberships = tuple(document["catalogMembership"])
        expected_core = (place.population is not None and place.population >= 500) or (
            place.feature_code in CORE_CAPITAL_FEATURE_CODES
        )
        expected_memberships = (("europe-core",) if expected_core else ()) + (
            ("europe-coastal",) if document["coastalCovers"] else ()
        )
        if memberships != expected_memberships:
            raise SearchProjectionError("spatial place membership differs")
        previous = geoname_id
        yield document, _projection_document(place, document)


def _projection_document(place: CataloguePlace, spatial: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": _DOCUMENT_KIND,
        "placeId": place.id,
        "sourceSpelling": place.source_spelling,
        "canonicalName": {
            "value": place.canonical_name.value,
            "language": place.canonical_name.language,
            "script": place.canonical_name.script,
        },
        "asciiName": place.ascii_name,
        "alternateNames": [
            {"value": item.value, "language": item.language, "script": item.script}
            for item in place.alternate_names
        ],
        "countryCode": place.country_code,
        "admin1Code": place.admin1_code,
        "admin1Name": place.admin1_name,
        "location": {"latitude": place.latitude, "longitude": place.longitude},
        "population": place.population,
        "featureCode": place.feature_code,
        "sourceUpdatedAt": place.source_updated_at.isoformat(),
        "lineage": [source_stage._json_value(item) for item in place.lineage],
        "spatialClassification": {
            "catalogMembership": spatial["catalogMembership"],
            "distanceToShorelineMeters": spatial["distanceToShorelineMeters"],
            "isCoastal": spatial["coastalCovers"],
        },
    }


def _validate_source(connection: Any, candidate: Mapping[str, Any]) -> None:
    spatial_stage._validate_schema(connection)
    counts = dict.fromkeys(_COUNT_KEYS, 0)
    hashes = {"classifiedPlaces": hashlib.sha256(), "spatialRejections": hashlib.sha256()}
    for spatial, _ in _spatial_documents(connection):
        counts["normalizedPlaces"] += 1
        counts["classifiedPlaces"] += 1
        counts["europeCoreMemberships"] += int("europe-core" in spatial["catalogMembership"])
        counts["europeCoastalMemberships"] += int(spatial["coastalCovers"])
        hashes["classifiedPlaces"].update(source_stage._canonical_json(spatial).encode() + b"\n")
    previous = 0
    for geoname_id, place_id, reason, raw in spatial_stage._stored_rows(
        connection, "spatial_rejections"
    ):
        document = source_stage._strict_json(raw, "spatial rejection document")
        if (
            type(document) is not dict
            or source_stage._canonical_json(document) != raw
            or type(geoname_id) is not int
            or geoname_id <= previous
            or place_id != f"geonames:{geoname_id}"
            or reason != "outside-support"
            or document
            != {"lineage": document.get("lineage"), "placeId": place_id, "reason": reason}
            or type(document["lineage"]) is not list
            or not document["lineage"]
        ):
            raise SearchProjectionError("spatial rejection keys, ordering, or values differ")
        previous = geoname_id
        counts["normalizedPlaces"] += 1
        counts["spatialRejections"] += 1
        counts["outsideSupportRejections"] += 1
        hashes["spatialRejections"].update(raw.encode() + b"\n")
    observed_hashes = {key: value.hexdigest() for key, value in hashes.items()}
    if candidate["counts"] != counts or candidate["logicalHashes"] != observed_hashes:
        raise SearchProjectionError("spatial database differs from its exact receipt")


def _header(
    candidate: Mapping[str, Any], database_sha256: str, receipt_sha256: str
) -> dict[str, Any]:
    return {
        "kind": _HEADER_KIND,
        "schemaVersion": SEARCH_PROJECTION_SCHEMA_VERSION,
        "normalizationVersion": "settlement-normalization-v2",
        "dataProvenanceClass": candidate["geometry"]["dataProvenanceClass"],
        "geometryStatus": candidate["geometry"]["geometryStatus"],
        "publicationEligible": False,
        **{name: False for name in _PROJECTION_FALSE_CLAIMS},
        "source": {
            "spatialDatabaseSha256": database_sha256,
            "spatialReceiptSha256": receipt_sha256,
            "spatialCandidateIdentity": candidate["deterministicIdentity"],
            "spatialStageSchemaVersion": candidate["spatialStageSchemaVersion"],
        },
    }


def _footer(header: Mapping[str, Any], count: int, digest: str) -> dict[str, Any]:
    value = {"header": header, "recordCount": count, "documentsSha256": digest}
    return {
        "kind": _FOOTER_KIND,
        "recordCount": count,
        "documentsSha256": digest,
        "deterministicIdentity": hashlib.sha256(_canonical(value)).hexdigest(),
    }


def _write(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written < 1:
            raise SearchProjectionError("search projection produced no bytes")
        offset += written


def _projection_line(value: Mapping[str, Any], label: str) -> bytes:
    content = _canonical(value)
    if len(content) - 1 > MAX_LINE_BYTES:
        raise SearchProjectionError(f"{label} exceeds the canonical line limit")
    return content


def _rollback_output(primary: BaseException, directory: Any, name: str, expected: Any) -> None:
    try:
        error = stage_runner._rollback_owned(directory, name, expected, directory)
        if error is not None:
            authority._note_cleanup(primary, error)
        os.fsync(directory.descriptor)
    except BaseException as cleanup:
        authority._note_cleanup(primary, cleanup)


def serialize_search_projection(
    spatial_database: Path, spatial_receipt: Path, output: Path, *, work_dir: Path
) -> dict[str, Any]:
    """Stream one immutable NDJSON search projection without publishing it."""

    stack = ExitStack()
    output_directory = private = expected = commit_directory = None
    private_name = ""
    owned: list[tuple] = []
    private_cleaned = promoted = False
    commit_descriptor = -1
    footer = None
    try:
        output_directory = stack.enter_context(
            authority._open_directory_path(output.parent, "search projection output directory")
        )
        authority._assert_secure_work_directory(output_directory)
        try:
            authority._path_stat(output_directory.descriptor, output.name)
        except FileNotFoundError:
            pass
        else:
            raise SearchProjectionError("search projection output exists; overwrite is refused")
        private_name, private = authority._create_private(output_directory)
        authority._stack_close(stack, private.descriptor)
        descriptor = os.open(output.name, authority._CREATE_FLAGS, 0o600, dir_fd=private.descriptor)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise SearchProjectionError("staged search projection is not a regular file")
            owned.append((output.name, metadata.st_dev, metadata.st_ino))
            with _snapshots(
                {"spatial.duckdb": spatial_database, "spatial-receipt.json": spatial_receipt},
                work_dir,
            ) as (root, sources):
                candidate, receipt_sha256 = _candidate(sources["spatial-receipt.json"])
                duckdb, _ = source_stage._load_tools()
                with duckdb.connect(str(root / "spatial.duckdb"), read_only=True) as connection:
                    _configure_connection(connection)
                    _validate_source(connection, candidate)
                    header = _header(candidate, sources["spatial.duckdb"].sha256, receipt_sha256)
                    _write(descriptor, _projection_line(header, "search projection header"))
                    count, digest = 0, hashlib.sha256()
                    for _, document in _spatial_documents(connection):
                        raw = _projection_line(document, "search projection document")
                        digest.update(raw)
                        _write(descriptor, raw)
                        count += 1
                    footer = _footer(header, count, digest.hexdigest())
                    _write(descriptor, _projection_line(footer, "search projection footer"))
                    _assert_no_spill(connection)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if footer is None:
            raise SearchProjectionError("search projection footer was not created")
        with authority._open_asset(
            private, PurePosixPath(output.name), "staged search projection"
        ) as staged:
            if (staged.device, staged.inode) != (metadata.st_dev, metadata.st_ino):
                raise SearchProjectionError("staged search projection was replaced")
            os.link(
                output.name,
                output.name,
                src_dir_fd=private.descriptor,
                dst_dir_fd=output_directory.descriptor,
                follow_symlinks=False,
            )
            expected, promoted = staged, True
            os.fsync(output_directory.descriptor)
        authority._remove_private(output_directory, private_name, private, tuple(owned), ())
        private_cleaned = True
        os.fsync(output_directory.descriptor)
        authority._assert_directory(output_directory)
        commit_descriptor = os.dup(output_directory.descriptor)
        commit_directory = output_directory._replace(descriptor=commit_descriptor)
        stack.close()
        with authority._open_directory_path(
            output.parent, "final search projection output directory"
        ) as final_directory:
            if (final_directory.device, final_directory.inode) != (
                commit_directory.device,
                commit_directory.inode,
            ):
                raise SearchProjectionError("search projection output directory changed")
            with authority._open_asset(
                final_directory, PurePosixPath(output.name), "search projection output"
            ) as published:
                if (
                    (published.device, published.inode) != (expected.device, expected.inode)
                    or published.size != expected.size
                    or published.sha256 != expected.sha256
                ):
                    raise SearchProjectionError("search projection output identity changed")
        try:
            os.close(commit_descriptor)
        except OSError:
            pass
        commit_descriptor = -1
        return footer
    except BaseException as primary:
        rollback = commit_directory or output_directory
        if promoted and expected is not None and rollback is not None:
            _rollback_output(primary, rollback, output.name, expected)
        if private is not None and output_directory is not None and not private_cleaned:
            try:
                authority._remove_private(output_directory, private_name, private, tuple(owned), ())
            except BaseException as cleanup:
                authority._note_cleanup(primary, cleanup)
        try:
            stack.close()
        except BaseException as cleanup:
            authority._note_cleanup(primary, cleanup)
        if commit_descriptor >= 0:
            try:
                os.close(commit_descriptor)
            except BaseException as cleanup:
                authority._note_cleanup(primary, cleanup)
        if isinstance(primary, SearchProjectionError):
            raise
        if isinstance(primary, Exception):
            raise SearchProjectionError(
                f"search projection serialization failed: {primary}"
            ) from primary
        raise


def validate_search_projection(
    spatial_database: Path, spatial_receipt: Path, projection: Path, *, work_dir: Path
) -> dict[str, Any]:
    """Stream-validate an NDJSON projection against its exact spatial source pair."""

    try:
        with _snapshots(
            {
                "spatial.duckdb": spatial_database,
                "spatial-receipt.json": spatial_receipt,
                "search-projection.ndjson": projection,
            },
            work_dir,
        ) as (root, assets):
            candidate, receipt_sha256 = _candidate(assets["spatial-receipt.json"])
            duckdb, _ = source_stage._load_tools()
            with duckdb.connect(str(root / "spatial.duckdb"), read_only=True) as connection:
                _configure_connection(connection)
                _validate_source(connection, candidate)
                expected_header = _header(
                    candidate, assets["spatial.duckdb"].sha256, receipt_sha256
                )
                lines = _asset_lines(assets["search-projection.ndjson"], "search projection")
                try:
                    header = _strict_line(next(lines), "search projection header")
                except StopIteration as exc:
                    raise SearchProjectionError("search projection is empty") from exc
                if header != expected_header:
                    raise SearchProjectionError("search projection source binding or claims differ")
                count, digest = 0, hashlib.sha256()
                for _, expected in _spatial_documents(connection):
                    try:
                        raw = next(lines)
                    except StopIteration as exc:
                        raise SearchProjectionError("search projection is truncated") from exc
                    actual = _strict_line(raw, f"search projection document {count + 1}")
                    if actual != expected:
                        raise SearchProjectionError(
                            "search projection differs from exact spatial source"
                        )
                    digest.update(raw + b"\n")
                    count += 1
                try:
                    footer = _strict_line(next(lines), "search projection footer")
                except StopIteration as exc:
                    raise SearchProjectionError("search projection footer is missing") from exc
                if next(lines, None) is not None:
                    raise SearchProjectionError("search projection has trailing records")
                expected_footer = _footer(header, count, digest.hexdigest())
                if footer != expected_footer:
                    raise SearchProjectionError("search projection footer differs")
                _assert_no_spill(connection)
                return footer
    except SearchProjectionError:
        raise
    except Exception as exc:
        raise SearchProjectionError(f"search projection validation failed: {exc}") from exc
