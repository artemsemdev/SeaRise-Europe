"""Streaming normalized-catalogue candidate core over opened DuckDB connections."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import math
import os
import re
import secrets
import stat
import sys
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import UnionType
from typing import Any, Iterator, Mapping, Union, get_args, get_origin, get_type_hints

from . import full_source_stage as source_stage
from .alternate_names import (
    NORMALIZATION_POLICY_VERSION,
    AlternateNameRecord,
    IsoLanguageRecord,
    language_codes,
)
from .catalogue import (
    CATALOGUE_POLICY_VERSION,
    CatalogueContextNotice,
    CatalogueNormalizationError,
    CataloguePlace,
    CatalogueRecordNormalization,
    CatalogueRejection,
    normalize_catalogue_record,
)
from .full_source_catalogue import PRODUCTION_CONTRACT, FullSourceStageContract
from .full_source_stage import FullSourceStageError
from .geonames import RAW_ANOMALY_POLICY_VERSION, Admin1Record, GeoNameRecord

CATALOGUE_STAGE_SCHEMA_VERSION = "normalized-catalogue-stage-v1"
LOGICAL_HASH_VERSION = "canonical-jsonl-v1"
MAX_BATCH_ROWS = source_stage.MAX_ARROW_BATCH_ROWS
MAX_ALTERNATE_ROWS_PER_PLACE = MAX_BATCH_ROWS
_UTC_SECONDS = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

_DOCUMENT_TABLES = {
    "catalogue_places": "normalizedPlaces",
    "catalogue_rejections": "catalogueRejections",
    "catalogue_context_notices": "contextNotices",
}
_COUNT_TABLES = {
    "catalogue_context_notice_counts": "contextNoticeReasons",
    "catalogue_name_rejection_counts": "nameRejectionReasons",
}
_COLUMNS = {
    "catalogue_places": (
        ("geoname_id", "UBIGINT"),
        ("place_id", "VARCHAR"),
        ("document", "VARCHAR"),
    ),
    "catalogue_rejections": (
        ("geoname_id", "UBIGINT"),
        ("place_id", "VARCHAR"),
        ("reason", "VARCHAR"),
        ("document", "VARCHAR"),
    ),
    "catalogue_context_notices": (
        ("geoname_id", "UBIGINT"),
        ("place_id", "VARCHAR"),
        ("reason", "VARCHAR"),
        ("document", "VARCHAR"),
    ),
    "catalogue_context_notice_counts": (("reason", "VARCHAR"), ("count", "UBIGINT")),
    "catalogue_name_rejection_counts": (("reason", "VARCHAR"), ("count", "UBIGINT")),
}


class CatalogueStageError(ValueError):
    """An opened source or normalized-catalogue candidate is invalid."""


def _decode(annotation: Any, value: Any, label: str) -> Any:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        for candidate in get_args(annotation):
            try:
                return _decode(candidate, value, label)
            except CatalogueStageError:
                pass
        raise CatalogueStageError(f"{label} has an invalid union value")
    if annotation is type(None):
        if value is not None:
            raise CatalogueStageError(f"{label} must be null")
        return None
    if annotation is date:
        if type(value) is not str:
            raise CatalogueStageError(f"{label} date must be a string")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CatalogueStageError(f"{label} date is invalid") from exc
    if origin is tuple:
        if type(value) is not list:
            raise CatalogueStageError(f"{label} tuple must be a JSON array")
        return tuple(_decode(get_args(annotation)[0], item, label) for item in value)
    if is_dataclass(annotation):
        names = {item.name for item in fields(annotation)}
        if type(value) is not dict or set(value) != names:
            raise CatalogueStageError(f"{label} fields differ from the staged contract")
        hints = get_type_hints(annotation)
        return annotation(
            **{
                item.name: _decode(hints[item.name], value[item.name], f"{label}.{item.name}")
                for item in fields(annotation)
            }
        )
    if type(value) is not annotation:
        raise CatalogueStageError(f"{label} has an invalid JSON type")
    return value


def _document(kind: Any, raw: str, label: str) -> Any:
    value = source_stage._strict_json(raw, label)
    result = _decode(kind, value, label)
    if source_stage._canonical_json(result) != raw:
        raise CatalogueStageError(f"{label} is not canonical JSON")
    return result


def _rows(cursor: Any, batch_size: int) -> Iterator[tuple[Any, ...]]:
    while batch := cursor.fetchmany(batch_size):
        yield from batch


def _configure_connection(connection: Any, work_dir: Path, label: str) -> None:
    source_stage._require_directory(work_dir, "catalogue work directory")
    spill = work_dir / f"duckdb-{label}-spill"
    try:
        spill.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise CatalogueStageError(f"cannot create {label} spill directory: {exc}") from exc
    source_stage._require_directory(spill, f"{label} spill directory")
    resolved_spill = spill.resolve(strict=True)
    connection.execute("SET threads=1")
    connection.execute(f"SET memory_limit='{source_stage.MEMORY_LIMIT}'")
    connection.execute("SET temp_directory=?", [str(resolved_spill)])
    actual = connection.execute(
        "SELECT current_setting('threads'), current_setting('memory_limit'), "
        "current_setting('temp_directory')"
    ).fetchone()
    if actual != (1, "1.0 GiB", str(resolved_spill)):
        raise CatalogueStageError(f"{label} DuckDB resource limits were not applied")


def _table_names(connection: Any) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }


def _create_schema(connection: Any) -> None:
    if _table_names(connection):
        raise CatalogueStageError("catalogue candidate connection must start empty")
    for table, columns in _COLUMNS.items():
        definition = ", ".join(f"{name} {kind} NOT NULL" for name, kind in columns)
        connection.execute(f"CREATE TABLE {table}({definition})")


def _validate_schema(connection: Any) -> None:
    if _table_names(connection) != set(_COLUMNS):
        raise CatalogueStageError("catalogue database tables differ from the versioned schema")
    for table, columns in _COLUMNS.items():
        actual = tuple(
            (row[1], row[2], bool(row[3]))
            for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        )
        if actual != tuple((name, kind, True) for name, kind in columns):
            raise CatalogueStageError(f"{table} columns differ from the versioned schema")


def _validate_source(
    connection: Any,
    receipt: Mapping[str, Any],
    contract: FullSourceStageContract,
) -> None:
    source_stage._validate_receipt_contract(receipt, contract)
    if _table_names(connection) != set(source_stage._TABLES):
        raise CatalogueStageError("source database tables differ from the stage schema")
    source_stage._validate_schema(connection)
    source_stage._reconcile(connection)
    if not source_stage._exact_json_equal(receipt, source_stage._receipt(connection, contract)):
        raise CatalogueStageError("source stage differs from its exact receipt")


def _input_binding(receipt: Mapping[str, Any]) -> dict[str, Any]:
    raw = source_stage.canonical_stage_receipt_bytes(receipt)
    return {
        "receiptSha256": hashlib.sha256(raw).hexdigest(),
        "stageSchemaVersion": receipt["stageSchemaVersion"],
        "logicalHashVersion": receipt["logicalHashVersion"],
        "counts": receipt["counts"],
        "logicalHashes": receipt["logicalHashes"],
    }


def _logical_hash(connection: Any, table: str) -> str:
    columns = "geoname_id, place_id, document"
    if table != "catalogue_places" and table in _DOCUMENT_TABLES:
        columns = "geoname_id, place_id, reason, document"
    query = (
        f"SELECT {columns} FROM {table} ORDER BY geoname_id"
        if table in _DOCUMENT_TABLES
        else f"SELECT reason, count FROM {table} ORDER BY reason"
    )
    kinds = {
        "catalogue_places": CataloguePlace,
        "catalogue_rejections": CatalogueRejection,
        "catalogue_context_notices": CatalogueContextNotice,
    }
    digest = hashlib.sha256()
    last_key: Any = None
    for row in _rows(connection.execute(query), MAX_BATCH_ROWS):
        if table in kinds:
            item = _document(kinds[table], row[-1], f"{table} document")
            geoname_id, place_id = row[:2]
            identifier = item.id if table == "catalogue_places" else item.place_id
            if identifier != place_id or place_id != f"geonames:{geoname_id}":
                raise CatalogueStageError(f"{table} keys differ from canonical JSON")
            if table != "catalogue_places" and item.reason != row[2]:
                raise CatalogueStageError(f"{table} reason differs from canonical JSON")
            key, raw = geoname_id, row[-1]
        else:
            reason, count = row
            if type(reason) is not str or not reason or type(count) is not int or count < 1:
                raise CatalogueStageError(f"{table} contains an invalid count")
            key, raw = reason, source_stage._canonical_json({"count": count, "reason": reason})
        if last_key is not None and key <= last_key:
            raise CatalogueStageError(f"{table} keys must be unique and ordered")
        last_key = key
        digest.update(raw.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _candidate_identity(
    connection: Any,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    tables = {**_DOCUMENT_TABLES, **_COUNT_TABLES}
    counts = {
        "sourcePlaceRows": receipt["counts"]["placeRows"],
        "sourceAlternateNameRows": receipt["counts"]["alternateNameRows"],
        **{
            key: int(source_stage._first_scalar(connection, f"SELECT count(*) FROM {table}"))
            for table, key in tables.items()
        },
    }
    if counts["sourcePlaceRows"] != counts["normalizedPlaces"] + counts["catalogueRejections"]:
        raise CatalogueStageError("source place count does not equal normalized plus rejected")
    value = {
        "catalogueStageSchemaVersion": CATALOGUE_STAGE_SCHEMA_VERSION,
        "logicalHashVersion": LOGICAL_HASH_VERSION,
        "publicationClaim": False,
        "policyVersions": {
            "catalogue": CATALOGUE_POLICY_VERSION,
            "names": NORMALIZATION_POLICY_VERSION,
            "rawSource": RAW_ANOMALY_POLICY_VERSION,
        },
        "inputStage": _input_binding(receipt),
        "counts": counts,
        "logicalHashes": {key: _logical_hash(connection, table) for table, key in tables.items()},
    }
    raw = (source_stage._canonical_json(value) + "\n").encode("utf-8")
    return {**value, "deterministicIdentity": hashlib.sha256(raw).hexdigest()}


def validate_catalogue_candidate(
    source: Any,
    candidate: Any,
    stage_receipt: Mapping[str, Any],
    *,
    work_dir: Path,
    batch_size: int = MAX_BATCH_ROWS,
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
) -> dict[str, Any]:
    """Return the deterministic identity of one opened logical candidate."""
    try:
        if not 1 <= batch_size <= MAX_BATCH_ROWS:
            raise CatalogueStageError(f"batch size must be within 1..{MAX_BATCH_ROWS}")
        _configure_connection(source, work_dir, "source")
        _configure_connection(candidate, work_dir, "candidate")
        _validate_source(source, stage_receipt, contract)
        _validate_schema(candidate)
        identity = _candidate_identity(candidate, stage_receipt)
        _replay_normalization(source, candidate, stage_receipt, batch_size)
        return identity
    except CatalogueStageError:
        raise
    except (CatalogueNormalizationError, FullSourceStageError, OSError, ValueError) as exc:
        raise CatalogueStageError(f"catalogue candidate validation failed: {exc}") from exc


def _lookups(
    source: Any,
    batch_size: int,
    receipt: Mapping[str, Any],
) -> tuple[dict[str, Admin1Record], frozenset[str]]:
    admins = {}
    for (raw,) in _rows(
        source.execute("SELECT document FROM stage_admin1 ORDER BY admin_key"), batch_size
    ):
        item = _document(Admin1Record, raw, "stage admin1 document")
        if item.key in admins:
            raise CatalogueStageError(f"duplicate admin1 key {item.key}")
        admins[item.key] = item
    languages = [
        _document(IsoLanguageRecord, raw, "stage language document")
        for (raw,) in _rows(
            source.execute("SELECT document FROM stage_languages ORDER BY sort_key, source_line"),
            batch_size,
        )
    ]
    if (
        len(admins) != receipt["counts"]["admin1Rows"]
        or len(languages) != receipt["counts"]["languageRows"]
    ):
        raise CatalogueStageError("lookup row counts differ from the source receipt")
    return admins, language_codes(languages)


def _normalizations(
    source: Any,
    receipt: Mapping[str, Any],
    batch_size: int,
) -> Iterator[tuple[int, CatalogueRecordNormalization]]:
    admins, codes = _lookups(source, batch_size, receipt)
    places = _rows(
        source.cursor().execute(
            "SELECT geoname_id, document FROM stage_places ORDER BY geoname_id"
        ),
        batch_size,
    )
    alternates = iter(
        _rows(
            source.cursor().execute(
                "SELECT geoname_id, alternate_name_id, document FROM stage_alternates "
                "ORDER BY geoname_id, alternate_name_id"
            ),
            batch_size,
        )
    )
    current = next(alternates, None)
    last_place = place_count = alternate_count = 0
    for geoname_id, raw in places:
        if geoname_id <= last_place:
            raise CatalogueStageError(f"duplicate or unordered GeoNames place id {geoname_id}")
        if current is not None and current[0] < geoname_id:
            raise CatalogueStageError(f"orphan alternate place id {current[0]}")
        bucket = []
        last_alternate = 0
        while current is not None and current[0] == geoname_id:
            if current[1] <= last_alternate:
                raise CatalogueStageError(f"duplicate alternateNameId {current[1]}")
            if len(bucket) >= MAX_ALTERNATE_ROWS_PER_PLACE:
                raise CatalogueStageError(
                    f"alternate-name group {geoname_id} exceeds the "
                    f"{MAX_ALTERNATE_ROWS_PER_PLACE}-row memory bound"
                )
            bucket.append(_document(AlternateNameRecord, current[2], "stage alternate document"))
            last_alternate, alternate_count = current[1], alternate_count + 1
            current = next(alternates, None)
        place = _document(GeoNameRecord, raw, "stage place document")
        result = normalize_catalogue_record(
            place,
            admins_by_key=admins,
            alternate_records=bucket,
            known_language_codes=codes,
        )
        yield geoname_id, result
        last_place, place_count = geoname_id, place_count + 1
    if current is not None:
        raise CatalogueStageError(f"orphan alternate place id {current[0]}")
    if (
        place_count != receipt["counts"]["placeRows"]
        or alternate_count != receipt["counts"]["alternateNameRows"]
    ):
        raise CatalogueStageError("streamed row counts differ from the source receipt")


def _materialize(
    source: Any,
    candidate: Any,
    pa: Any,
    receipt: Mapping[str, Any],
    batch_size: int,
) -> None:
    sinks = {
        table: source_stage._ArrowSink(candidate, pa, table, batch_size)
        for table in _DOCUMENT_TABLES
    }
    notice_counts: Counter[str] = Counter()
    name_counts: Counter[str] = Counter()
    for geoname_id, result in _normalizations(source, receipt, batch_size):
        if result.place is not None:
            sinks["catalogue_places"].add(
                {
                    "geoname_id": geoname_id,
                    "place_id": result.place.id,
                    "document": source_stage._canonical_json(result.place),
                }
            )
        else:
            assert result.rejection is not None
            sinks["catalogue_rejections"].add(
                {
                    "geoname_id": geoname_id,
                    "place_id": result.rejection.place_id,
                    "reason": result.rejection.reason,
                    "document": source_stage._canonical_json(result.rejection),
                }
            )
        if result.context_notice is not None:
            notice = result.context_notice
            sinks["catalogue_context_notices"].add(
                {
                    "geoname_id": geoname_id,
                    "place_id": notice.place_id,
                    "reason": notice.reason,
                    "document": source_stage._canonical_json(notice),
                }
            )
            notice_counts[notice.reason] += 1
        name_counts.update(dict(result.name_rejection_counts))
    for sink in sinks.values():
        sink.flush()
    for table, counts in (
        ("catalogue_context_notice_counts", notice_counts),
        ("catalogue_name_rejection_counts", name_counts),
    ):
        if counts:
            candidate.executemany(f"INSERT INTO {table} VALUES (?, ?)", sorted(counts.items()))


def _require_row(rows: Iterator[tuple[Any, ...]], expected: tuple[Any, ...], label: str) -> None:
    if next(rows, None) != expected:
        raise CatalogueStageError(f"{label} differs from exact normalization replay")


def _require_exhausted(rows: Iterator[tuple[Any, ...]], label: str) -> None:
    if next(rows, None) is not None:
        raise CatalogueStageError(f"{label} contains rows absent from normalization replay")


def _replay_normalization(
    source: Any,
    candidate: Any,
    receipt: Mapping[str, Any],
    batch_size: int,
) -> None:
    places = iter(
        _rows(
            candidate.cursor().execute(
                "SELECT geoname_id, place_id, document FROM catalogue_places ORDER BY geoname_id"
            ),
            batch_size,
        )
    )
    rejections = iter(
        _rows(
            candidate.cursor().execute(
                "SELECT geoname_id, place_id, reason, document FROM catalogue_rejections "
                "ORDER BY geoname_id"
            ),
            batch_size,
        )
    )
    notices = iter(
        _rows(
            candidate.cursor().execute(
                "SELECT geoname_id, place_id, reason, document "
                "FROM catalogue_context_notices ORDER BY geoname_id"
            ),
            batch_size,
        )
    )
    notice_counts: Counter[str] = Counter()
    name_counts: Counter[str] = Counter()
    for geoname_id, result in _normalizations(source, receipt, batch_size):
        if result.place is not None:
            _require_row(
                places,
                (
                    geoname_id,
                    result.place.id,
                    source_stage._canonical_json(result.place),
                ),
                "normalized place",
            )
        else:
            assert result.rejection is not None
            _require_row(
                rejections,
                (
                    geoname_id,
                    result.rejection.place_id,
                    result.rejection.reason,
                    source_stage._canonical_json(result.rejection),
                ),
                "catalogue rejection",
            )
        if result.context_notice is not None:
            notice = result.context_notice
            _require_row(
                notices,
                (
                    geoname_id,
                    notice.place_id,
                    notice.reason,
                    source_stage._canonical_json(notice),
                ),
                "catalogue context notice",
            )
            notice_counts[notice.reason] += 1
        name_counts.update(dict(result.name_rejection_counts))
    for rows, label in (
        (places, "normalized places"),
        (rejections, "catalogue rejections"),
        (notices, "catalogue context notices"),
    ):
        _require_exhausted(rows, label)
    for table, expected in (
        ("catalogue_context_notice_counts", notice_counts),
        ("catalogue_name_rejection_counts", name_counts),
    ):
        actual = tuple(
            _rows(
                candidate.cursor().execute(f"SELECT reason, count FROM {table} ORDER BY reason"),
                batch_size,
            )
        )
        if actual != tuple(sorted(expected.items())):
            raise CatalogueStageError(f"{table} differs from exact normalization replay")


def materialize_catalogue_candidate(
    source: Any,
    candidate: Any,
    stage_receipt: Mapping[str, Any],
    *,
    work_dir: Path,
    batch_size: int = MAX_BATCH_ROWS,
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
) -> dict[str, Any]:
    """Populate an empty caller-owned connection and return its logical identity."""
    try:
        if sys.version_info[:2] != (3, 11):
            raise CatalogueStageError("catalogue materialization requires pinned Python 3.11")
        if not 1 <= batch_size <= MAX_BATCH_ROWS:
            raise CatalogueStageError(f"batch size must be within 1..{MAX_BATCH_ROWS}")
        _configure_connection(source, work_dir, "source")
        _configure_connection(candidate, work_dir, "candidate")
        _validate_source(source, stage_receipt, contract)
        _, pa = source_stage._load_tools()
        candidate.execute("SET preserve_insertion_order=false")
        _create_schema(candidate)
        _materialize(source, candidate, pa, stage_receipt, batch_size)
        _validate_source(source, stage_receipt, contract)
        _validate_schema(candidate)
        identity = _candidate_identity(candidate, stage_receipt)
        _replay_normalization(source, candidate, stage_receipt, batch_size)
        return identity
    except CatalogueStageError:
        raise
    except (CatalogueNormalizationError, FullSourceStageError, OSError, ValueError) as exc:
        raise CatalogueStageError(f"catalogue candidate materialization failed: {exc}") from exc


def _receipt_payload(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "materializationPerformed": True,
        "candidate": identity,
        "toolchain": {
            "python": "3.11",
            "duckdb": source_stage.DUCKDB_VERSION,
            "pyarrow": source_stage.PYARROW_VERSION,
            "threads": 1,
            "memoryLimit": source_stage.MEMORY_LIMIT,
            "maxBatchRows": MAX_BATCH_ROWS,
        },
    }


def _receipt_identity(payload: Mapping[str, Any]) -> str:
    raw = (source_stage._canonical_json(payload) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def canonical_catalogue_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return canonical receipt bytes with observations outside deterministic identity."""
    try:
        value = dict(receipt)
        return (source_stage._canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CatalogueStageError(f"catalogue receipt cannot be encoded: {exc}") from exc


def _load_catalogue_receipt_bytes(raw: bytes) -> dict[str, Any]:
    try:
        value = source_stage._strict_json(raw, "catalogue receipt")
    except FullSourceStageError as exc:
        raise CatalogueStageError(str(exc)) from exc
    if type(value) is not dict or raw != canonical_catalogue_receipt_bytes(value):
        raise CatalogueStageError("catalogue receipt is not canonical JSON")
    return value


def _validate_observations(value: Any) -> None:
    if type(value) is not dict or set(value) != {
        "completedAtUtc",
        "buildDurationSeconds",
        "peakRssBytes",
        "deterministicIdentityExcluded",
    }:
        raise CatalogueStageError("catalogue receipt observations differ from the schema")
    timestamp = value["completedAtUtc"]
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise CatalogueStageError("catalogue build timestamp is invalid") from exc
    if (
        type(timestamp) is not str
        or _UTC_SECONDS.fullmatch(timestamp) is None
        or parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != timestamp
        or type(value["buildDurationSeconds"]) is not float
        or not math.isfinite(value["buildDurationSeconds"])
        or value["buildDurationSeconds"] < 0
        or type(value["peakRssBytes"]) is not int
        or value["peakRssBytes"] < 1
        or value["deterministicIdentityExcluded"] is not True
    ):
        raise CatalogueStageError("catalogue receipt observations are invalid")


def _validate_receipt(identity: Mapping[str, Any], document: Mapping[str, Any]) -> None:
    payload = _receipt_payload(identity)
    if set(document) != {*payload, "deterministicIdentity", "observations"} or any(
        not source_stage._exact_json_equal(document.get(key), value)
        for key, value in payload.items()
    ):
        raise CatalogueStageError("catalogue receipt differs from the exact candidate")
    if document["deterministicIdentity"] != _receipt_identity(payload):
        raise CatalogueStageError("catalogue receipt deterministic identity differs")
    _validate_observations(document["observations"])


@dataclass(frozen=True)
class _OpenedRegular:
    descriptor: int
    label: str
    device: int
    inode: int
    size: int
    sha256: str | None


@dataclass(frozen=True)
class _OpenedDirectory:
    descriptor: int
    path: Path
    label: str
    device: int
    inode: int


def _regular_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size


def _opened_identity(opened: _OpenedRegular) -> tuple[int, int, int]:
    return opened.device, opened.inode, opened.size


def _sha256_descriptor(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise CatalogueStageError("opened file ended before its recorded size")
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _opened_regular(descriptor: int, label: str, *, hash_bytes: bool) -> _OpenedRegular:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise CatalogueStageError(f"{label} must be a regular non-symlink file")
    digest = _sha256_descriptor(descriptor, metadata.st_size) if hash_bytes else None
    if _regular_identity(os.fstat(descriptor)) != _regular_identity(metadata):
        raise CatalogueStageError(f"{label} identity changed while it was opened")
    return _OpenedRegular(
        descriptor,
        label,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        digest,
    )


@contextmanager
def _open_regular(path: Path, label: str, *, hash_bytes: bool = False) -> Iterator[_OpenedRegular]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        yield _opened_regular(descriptor, label, hash_bytes=hash_bytes)
    except CatalogueStageError:
        raise
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise CatalogueStageError(f"{label} must be a regular non-symlink file") from exc
        raise CatalogueStageError(f"cannot open {label}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def _open_relative_regular(
    directory: _OpenedDirectory,
    name: str,
    label: str,
    *,
    hash_bytes: bool = False,
) -> Iterator[_OpenedRegular]:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory.descriptor,
        )
        yield _opened_regular(descriptor, label, hash_bytes=hash_bytes)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _assert_opened(opened: _OpenedRegular) -> None:
    if _regular_identity(os.fstat(opened.descriptor)) != _opened_identity(opened):
        raise CatalogueStageError(f"{opened.label} identity changed while in use")
    if opened.sha256 is not None and (
        _sha256_descriptor(opened.descriptor, opened.size) != opened.sha256
    ):
        raise CatalogueStageError(f"{opened.label} exact bytes changed while in use")


def _read_opened(opened: _OpenedRegular) -> bytes:
    _assert_opened(opened)
    raw = os.pread(opened.descriptor, opened.size, 0)
    if len(raw) != opened.size:
        raise CatalogueStageError(f"{opened.label} ended before its recorded size")
    _assert_opened(opened)
    return raw


def _descriptor_path(descriptor: int, label: str) -> Path:
    try:
        if sys.platform == "darwin":
            raw = fcntl.fcntl(descriptor, 50, b"\0" * 1024)
            path = Path(os.fsdecode(raw.split(b"\0", 1)[0]))
        else:
            path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        metadata = path.lstat()
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise CatalogueStageError(f"cannot resolve opened {label}: {exc}") from exc
    if (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino):
        raise CatalogueStageError(f"opened {label} path no longer names its inode")
    return path


@contextmanager
def _open_directory(path: Path, label: str) -> Iterator[_OpenedDirectory]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise CatalogueStageError(f"{label} must be a directory, not a symlink")
        yield _OpenedDirectory(descriptor, path, label, metadata.st_dev, metadata.st_ino)
    except CatalogueStageError:
        raise
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise CatalogueStageError(f"{label} must be a directory, not a symlink") from exc
        raise CatalogueStageError(f"cannot open {label}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _assert_directory_path(directory: _OpenedDirectory) -> None:
    try:
        metadata = directory.path.lstat()
    except OSError as exc:
        raise CatalogueStageError(f"{directory.label} path identity changed: {exc}") from exc
    if (metadata.st_dev, metadata.st_ino) != (directory.device, directory.inode):
        raise CatalogueStageError(f"{directory.label} path identity changed")


def _assert_path_binding(path: Path, opened: _OpenedRegular) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CatalogueStageError(f"{opened.label} path identity changed: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or _regular_identity(metadata) != _opened_identity(
        opened
    ):
        raise CatalogueStageError(f"{opened.label} path identity changed")
    _assert_opened(opened)


def _create_private_directory(
    parent: _OpenedDirectory, prefix: str, label: str
) -> tuple[str, _OpenedDirectory]:
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(12)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent.descriptor)
        except FileExistsError:
            continue
        created = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
        created_identity = created.st_dev, created.st_ino
        if not stat.S_ISDIR(created.st_mode):
            raise CatalogueStageError(f"created {label} entry is not a directory")
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent.descriptor,
            )
            metadata = os.fstat(descriptor)
            if (metadata.st_dev, metadata.st_ino) != created_identity:
                raise CatalogueStageError(f"created {label} entry was replaced before open")
            return name, _OpenedDirectory(
                descriptor,
                _descriptor_path(descriptor, label),
                label,
                metadata.st_dev,
                metadata.st_ino,
            )
        except Exception as exc:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                current = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
            except FileNotFoundError:
                raise exc
            if (current.st_dev, current.st_ino) != created_identity:
                raise CatalogueStageError(
                    f"created {label} entry was replaced; cleanup refused"
                ) from exc
            os.rmdir(name, dir_fd=parent.descriptor)
            raise exc
    raise CatalogueStageError(f"cannot allocate a private {label}")


def _clear_directory(descriptor: int) -> None:
    for name in os.listdir(descriptor):
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            try:
                _clear_directory(child)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=descriptor)
        else:
            os.unlink(name, dir_fd=descriptor)


def _remove_private_directory(parent: _OpenedDirectory, name: str, child: _OpenedDirectory) -> None:
    try:
        _clear_directory(child.descriptor)
    finally:
        os.close(child.descriptor)
    try:
        metadata = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (metadata.st_dev, metadata.st_ino) != (child.device, child.inode):
        raise CatalogueStageError(f"{child.label} parent entry was replaced; cleanup refused")
    os.rmdir(name, dir_fd=parent.descriptor)


def _copy_snapshot(source: _OpenedRegular, directory: _OpenedDirectory, name: str) -> None:
    destination = -1
    try:
        destination = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory.descriptor,
        )
        digest = hashlib.sha256()
        offset = 0
        while offset < source.size:
            chunk = os.pread(source.descriptor, min(1024 * 1024, source.size - offset), offset)
            if not chunk:
                raise CatalogueStageError(
                    f"{source.label} ended while creating its private snapshot"
                )
            digest.update(chunk)
            written = 0
            while written < len(chunk):
                count = os.write(destination, chunk[written:])
                if count < 1:
                    raise CatalogueStageError("private snapshot produced a zero-byte write")
                written += count
            offset += len(chunk)
        os.fsync(destination)
        _assert_opened(source)
        if _sha256_descriptor(source.descriptor, source.size) != digest.hexdigest():
            raise CatalogueStageError(f"{source.label} changed while its snapshot was copied")
    finally:
        if destination >= 0:
            os.close(destination)


@contextmanager
def _private_snapshot(
    source_path: Path,
    source: _OpenedRegular,
    directory: _OpenedDirectory,
    name: str,
) -> Iterator[_OpenedRegular]:
    copied = False
    try:
        os.link(
            source_path,
            name,
            dst_dir_fd=directory.descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        fallback_errors = {errno.EXDEV, errno.EPERM}
        if hasattr(errno, "EOPNOTSUPP"):
            fallback_errors.add(errno.EOPNOTSUPP)
        if exc.errno not in fallback_errors:
            raise
        _copy_snapshot(source, directory, name)
        copied = True
    with _open_relative_regular(
        directory,
        name,
        f"{source.label} private snapshot",
        hash_bytes=copied,
    ) as snapshot:
        if copied:
            if snapshot.size != source.size or snapshot.sha256 != _sha256_descriptor(
                source.descriptor, source.size
            ):
                raise CatalogueStageError(f"{source.label} copy differs from its private snapshot")
        elif _opened_identity(snapshot) != _opened_identity(source):
            raise CatalogueStageError(
                f"{source.label} changed before its private snapshot was bound"
            )
        yield snapshot


def _source_receipt_document(opened: _OpenedRegular) -> dict[str, Any]:
    try:
        raw = _read_opened(opened)
        value = source_stage._strict_json(raw, "source stage receipt")
        if type(value) is not dict or raw != source_stage.canonical_stage_receipt_bytes(value):
            raise CatalogueStageError("source stage receipt is not canonical JSON")
        return value
    except FullSourceStageError as exc:
        raise CatalogueStageError(f"source stage validation failed: {exc}") from exc


def validate_normalized_catalogue_stage(
    database: Path,
    receipt: Path,
    source_database: Path,
    source_receipt: Path,
    *,
    work_dir: Path,
    batch_size: int = MAX_BATCH_ROWS,
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
) -> None:
    """Validate one catalogue and receipt against inode-bound private snapshots."""
    private: tuple[str, _OpenedDirectory] | None = None
    with ExitStack() as stack:
        work = stack.enter_context(_open_directory(work_dir, "catalogue work directory"))
        opened_source = stack.enter_context(_open_regular(source_database, "source stage database"))
        opened_database = stack.enter_context(_open_regular(database, "catalogue database"))
        opened_source_receipt = stack.enter_context(
            _open_regular(source_receipt, "source stage receipt", hash_bytes=True)
        )
        opened_receipt = stack.enter_context(
            _open_regular(receipt, "catalogue receipt", hash_bytes=True)
        )
        source_document = _source_receipt_document(opened_source_receipt)
        document = _load_catalogue_receipt_bytes(_read_opened(opened_receipt))
        private = _create_private_directory(
            work, ".catalogue-validate-", "catalogue validation directory"
        )
        _, private_directory = private
        try:
            with _private_snapshot(
                source_database, opened_source, private_directory, "source.duckdb"
            ) as source_snapshot:
                with _private_snapshot(
                    database, opened_database, private_directory, "catalogue.duckdb"
                ) as database_snapshot:
                    duckdb, _ = source_stage._load_tools()
                    root = _descriptor_path(private_directory.descriptor, private_directory.label)
                    with duckdb.connect(str(root / "source.duckdb"), read_only=True) as source:
                        with duckdb.connect(
                            str(root / "catalogue.duckdb"), read_only=True
                        ) as candidate:
                            identity = validate_catalogue_candidate(
                                source,
                                candidate,
                                source_document,
                                work_dir=root,
                                batch_size=batch_size,
                                contract=contract,
                            )
                    for opened in (
                        opened_source,
                        opened_database,
                        source_snapshot,
                        database_snapshot,
                    ):
                        _assert_opened(opened)
            _validate_receipt(identity, document)
            _assert_path_binding(source_database, opened_source)
            _assert_path_binding(database, opened_database)
            _assert_path_binding(source_receipt, opened_source_receipt)
            _assert_path_binding(receipt, opened_receipt)
            _assert_directory_path(work)
        except CatalogueStageError:
            raise
        except (FullSourceStageError, OSError, ValueError) as exc:
            raise CatalogueStageError(f"catalogue stage validation failed: {exc}") from exc
        finally:
            _remove_private_directory(work, private[0], private_directory)
