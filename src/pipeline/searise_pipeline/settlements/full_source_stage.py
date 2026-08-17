"""Streaming, disk-backed staging for the verified full GeoNames source set."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Mapping, Sequence

from .alternate_names import (
    NORMALIZATION_POLICY_VERSION,
    load_normalization_policy,
    parse_alternate_name_row,
    parse_iso_language_row,
)
from .catalogue import CATALOGUE_POLICY_VERSION, load_catalogue_policy
from .full_source_catalogue import (
    PRODUCTION_CONTRACT,
    FullSourceStageContract,
    FullSourceStageInputs,
    LockedAsset,
    LockedMember,
    full_source_bindings,
)
from .geonames import RAW_ANOMALY_POLICY_VERSION, parse_admin1_row, parse_geoname_row

DUCKDB_VERSION = "1.5.4"
PYARROW_VERSION = "16.1.0"
STAGE_SCHEMA_VERSION = "full-source-catalogue-stage-v1"
LOGICAL_HASH_VERSION = "canonical-jsonl-v1"
MAX_ARROW_BATCH_ROWS = 16_384
MEMORY_LIMIT = "1GiB"

_TABLES = {
    "stage_admin1": "admin1Rows",
    "stage_alternates": "alternateNameRows",
    "stage_languages": "languageRows",
    "stage_places": "placeRows",
}
_COLUMNS = {
    "stage_places": (
        ("geoname_id", "UBIGINT"),
        ("source_line", "UBIGINT"),
        ("document", "VARCHAR"),
    ),
    "stage_admin1": (
        ("admin_key", "VARCHAR"),
        ("geoname_id", "UBIGINT"),
        ("source_line", "UBIGINT"),
        ("document", "VARCHAR"),
    ),
    "stage_languages": (
        ("sort_key", "VARCHAR"),
        ("source_line", "UBIGINT"),
        ("document", "VARCHAR"),
    ),
    "stage_alternates": (
        ("alternate_name_id", "UBIGINT"),
        ("geoname_id", "UBIGINT"),
        ("source_line", "UBIGINT"),
        ("document", "VARCHAR"),
    ),
}


class FullSourceStageError(ValueError):
    """The local full-source stage cannot be verified or promoted."""


@contextmanager
def _open_regular(path: Path, label: str) -> Iterator[BinaryIO]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise FullSourceStageError(f"{label} must be a regular non-symlink file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            yield stream
    except FullSourceStageError:
        raise
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise FullSourceStageError(f"{label} must be a regular non-symlink file") from exc
        raise FullSourceStageError(f"cannot open or read {label}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _sha256(path: Path, label: str) -> tuple[str, int]:
    with _open_regular(path, label) as stream:
        return _sha256_stream(stream)


def _regular_identity(path: Path, label: str) -> tuple[int, int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FullSourceStageError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FullSourceStageError(f"{label} must be a regular non-symlink file")
    return metadata.st_dev, metadata.st_ino, metadata.st_size


def _require_regular(path: Path, label: str) -> None:
    _regular_identity(path, label)


def _require_directory(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise FullSourceStageError(f"cannot inspect {label}: {exc}") from exc
    if path.is_symlink() or not stat.S_ISDIR(mode):
        raise FullSourceStageError(f"{label} must be a directory, not a symlink")


def _verify_file(path: Path, locked: LockedAsset, label: str) -> None:
    if _sha256(path, label) != (locked.sha256, locked.byte_size):
        raise FullSourceStageError(f"{label} bytes differ from the locked identity")


def _verify_outer_inputs(
    inputs: FullSourceStageInputs,
    contract: FullSourceStageContract,
    *,
    validate_policies: bool,
) -> None:
    for path, locked, label in (
        (inputs.all_countries_zip, contract.all_countries, "allCountries archive"),
        (inputs.alternate_names_zip, contract.alternate_names, "alternateNames archive"),
        (inputs.admin1, contract.admin1, "admin1 input"),
        (inputs.readme, contract.readme, "GeoNames readme"),
    ):
        _verify_file(path, locked, label)
    for path, expected, label in (
        (inputs.source_lock, contract.source_lock_sha256, "source lock"),
        (inputs.catalogue_policy, contract.catalogue_policy_sha256, "catalogue policy"),
        (inputs.normalization_policy, contract.normalization_policy_sha256, "normalization policy"),
    ):
        if _sha256(path, label)[0] != expected:
            raise FullSourceStageError(f"{label} bytes differ from the reviewed identity")
    if validate_policies:
        load_catalogue_policy(inputs.catalogue_policy)
        load_normalization_policy(inputs.normalization_policy)


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise FullSourceStageError(f"value cannot be canonicalized as JSON: {exc}") from exc


def _strict_json(raw: str | bytes, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise FullSourceStageError(f"{label} contains non-finite JSON value {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise FullSourceStageError(f"{label} contains duplicate key {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except FullSourceStageError:
        raise
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullSourceStageError(f"{label} contains invalid JSON: {exc}") from exc


def canonical_stage_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return deterministic receipt bytes without local paths or observations."""
    try:
        value = dict(receipt)
    except (TypeError, ValueError) as exc:
        raise FullSourceStageError(f"stage receipt is not a mapping: {exc}") from exc
    try:
        return (_canonical_json(value) + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise FullSourceStageError(f"stage receipt cannot be encoded as UTF-8: {exc}") from exc


def _fsync_file(path: Path, label: str) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise FullSourceStageError(f"cannot fsync {label}: {exc}") from exc


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise FullSourceStageError(f"cannot fsync output directory: {exc}") from exc


def _load_tools() -> tuple[Any, Any]:
    try:
        import duckdb  # type: ignore[import-untyped]
        import pyarrow as pa  # type: ignore[import-untyped]
    except ImportError as exc:
        raise FullSourceStageError(f"cannot import the pinned staging toolchain: {exc}") from exc
    if duckdb.__version__ != DUCKDB_VERSION or pa.__version__ != PYARROW_VERSION:
        raise FullSourceStageError("staging tool versions differ from the pinned contract")
    return duckdb, pa


class _ArrowSink:
    def __init__(self, connection: Any, pa: Any, table: str, batch_size: int):
        self.connection = connection
        self.pa = pa
        self.table = table
        self.batch_size = batch_size
        self.rows: list[dict[str, Any]] = []

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if len(self.rows) == self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        batch = self.pa.Table.from_pylist(self.rows)
        self.connection.register("_arrow_batch", batch)
        try:
            self.connection.execute(f"INSERT INTO {self.table} SELECT * FROM _arrow_batch")
        finally:
            self.connection.unregister("_arrow_batch")
        self.rows.clear()


def _zip_inventory(archive: zipfile.ZipFile, asset: LockedAsset) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if tuple(item.filename for item in entries) != tuple(item.path for item in asset.members):
        raise FullSourceStageError("ZIP member inventory differs from the locked contract")
    infos = {item.filename: item for item in entries}
    for member in asset.members:
        info = infos[member.path]
        if (info.file_size, info.compress_size, f"{info.CRC:08x}") != (
            member.byte_size,
            member.compressed_byte_size,
            member.crc32,
        ):
            raise FullSourceStageError(f"{member.path} ZIP metadata differs from the lock")
    return infos


def _consume_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    member: LockedMember,
    consume: Callable[[bytes, int], None],
) -> None:
    digest = hashlib.sha256()
    size = count = 0
    with archive.open(info) as stream:
        line_number = 1
        if member.header is not None:
            header = stream.readline()
            digest.update(header)
            size += len(header)
            if header.rstrip(b"\r\n") != member.header:
                raise FullSourceStageError(f"{member.path} header differs from the contract")
            line_number = 2
        for raw in stream:
            digest.update(raw)
            size += len(raw)
            consume(raw.rstrip(b"\r\n"), line_number)
            count += 1
            line_number += 1
    if (digest.hexdigest(), size, count) != (member.sha256, member.byte_size, member.row_count):
        raise FullSourceStageError(f"{member.path} content or row count differs from the lock")


@contextmanager
def _open_verified_zip(
    path: Path,
    locked: LockedAsset,
    label: str,
) -> Iterator[zipfile.ZipFile]:
    with _open_regular(path, label) as stream:
        if _sha256_stream(stream) != (locked.sha256, locked.byte_size):
            raise FullSourceStageError(f"{label} bytes differ from the locked identity")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            yield archive


def _consume_plain_rows(
    path: Path,
    locked: LockedAsset,
    consume: Callable[[bytes, int], None],
) -> None:
    digest = hashlib.sha256()
    size = count = 0
    with _open_regular(path, "admin1 input") as stream:
        for line_number, raw in enumerate(stream, 1):
            digest.update(raw)
            size += len(raw)
            consume(raw.rstrip(b"\r\n"), line_number)
            count += 1
    if (digest.hexdigest(), size, count) != (locked.sha256, locked.byte_size, locked.row_count):
        raise FullSourceStageError(f"{path.name} content or row count differs from the lock")


def _create_schema(connection: Any) -> None:
    for table, columns in _COLUMNS.items():
        definition = ", ".join(f"{name} {kind} NOT NULL" for name, kind in columns)
        connection.execute(f"CREATE TABLE {table}({definition})")


def _stage_rows(
    connection: Any,
    pa: Any,
    inputs: FullSourceStageInputs,
    contract: FullSourceStageContract,
    batch_size: int,
    source_order: Sequence[str],
) -> None:
    sinks = {name: _ArrowSink(connection, pa, name, batch_size) for name in _TABLES}

    def places() -> None:
        with _open_verified_zip(
            inputs.all_countries_zip, contract.all_countries, "allCountries archive"
        ) as archive:
            member = contract.all_countries.members[0]
            infos = _zip_inventory(archive, contract.all_countries)

            def consume(row: bytes, line: int) -> None:
                record = parse_geoname_row(row, source_line=line)
                sinks["stage_places"].add(
                    {
                        "geoname_id": record.geoname_id,
                        "source_line": line,
                        "document": _canonical_json(record),
                    }
                )

            _consume_member(archive, infos[member.path], member, consume)

    def admin1() -> None:
        def consume(row: bytes, line: int) -> None:
            record = parse_admin1_row(row, source_line=line)
            sinks["stage_admin1"].add(
                {
                    "admin_key": record.key,
                    "geoname_id": record.geoname_id,
                    "source_line": line,
                    "document": _canonical_json(record),
                }
            )

        _consume_plain_rows(inputs.admin1, contract.admin1, consume)

    def alternate_names() -> None:
        with _open_verified_zip(
            inputs.alternate_names_zip, contract.alternate_names, "alternateNames archive"
        ) as archive:
            infos = _zip_inventory(archive, contract.alternate_names)
            by_path = {item.path: item for item in contract.alternate_names.members}

            def consume_language(row: bytes, line: int) -> None:
                record = parse_iso_language_row(row, source_line=line)
                key = record.iso639_3 or (
                    record.iso639_2[0] if record.iso639_2 else record.iso639_1
                )
                if key is None:
                    raise FullSourceStageError("ISO language row has no sortable language code")
                sinks["stage_languages"].add(
                    {"sort_key": key, "source_line": line, "document": _canonical_json(record)}
                )

            def consume_alternate(row: bytes, line: int) -> None:
                record = parse_alternate_name_row(row, source_line=line)
                sinks["stage_alternates"].add(
                    {
                        "alternate_name_id": record.alternate_name_id,
                        "geoname_id": record.geoname_id,
                        "source_line": line,
                        "document": _canonical_json(record),
                    }
                )

            language = by_path["iso-languagecodes.txt"]
            _consume_member(archive, infos[language.path], language, consume_language)
            alternate = by_path["alternateNamesV2.txt"]
            _consume_member(archive, infos[alternate.path], alternate, consume_alternate)

    expected_sources = {"places", "admin1", "alternate_names"}
    if len(source_order) != len(expected_sources) or set(source_order) != expected_sources:
        raise FullSourceStageError("staging source order is incomplete or duplicated")
    for name in source_order:
        if name == "places":
            places()
        elif name == "admin1":
            admin1()
        else:
            alternate_names()
        for sink in sinks.values():
            sink.flush()


def _first_scalar(connection: Any, sql: str) -> Any:
    row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


def _reconcile(connection: Any) -> None:
    checks = (
        (
            "duplicate GeoNames place id",
            "SELECT geoname_id FROM stage_places GROUP BY geoname_id "
            "HAVING count(*) > 1 ORDER BY geoname_id LIMIT 1",
        ),
        (
            "duplicate alternateNameId",
            "SELECT alternate_name_id FROM stage_alternates GROUP BY alternate_name_id "
            "HAVING count(*) > 1 ORDER BY alternate_name_id LIMIT 1",
        ),
        (
            "duplicate admin1 key",
            "SELECT admin_key FROM stage_admin1 GROUP BY admin_key "
            "HAVING count(*) > 1 ORDER BY admin_key LIMIT 1",
        ),
        (
            "orphan alternate place id",
            "SELECT a.geoname_id FROM stage_alternates a "
            "LEFT JOIN stage_places p USING (geoname_id) "
            "WHERE p.geoname_id IS NULL ORDER BY a.geoname_id LIMIT 1",
        ),
    )
    for label, sql in checks:
        value = _first_scalar(connection, sql)
        if value is not None:
            raise FullSourceStageError(f"{label} {value}")


def _validate_schema(connection: Any) -> None:
    for table, columns in _COLUMNS.items():
        actual = tuple(
            (row[1], row[2], bool(row[3]))
            for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        )
        expected = tuple((name, kind, True) for name, kind in columns)
        if actual != expected:
            raise FullSourceStageError(f"{table} columns differ from the versioned schema")


def _logical_hash(connection: Any, table: str) -> str:
    query = {
        "stage_places": (
            "SELECT geoname_id, source_line, document FROM stage_places ORDER BY geoname_id"
        ),
        "stage_admin1": (
            "SELECT admin_key, geoname_id, source_line, document "
            "FROM stage_admin1 ORDER BY geoname_id, admin_key"
        ),
        "stage_languages": (
            "SELECT sort_key, source_line, document "
            "FROM stage_languages ORDER BY sort_key, source_line"
        ),
        "stage_alternates": (
            "SELECT alternate_name_id, geoname_id, source_line, document "
            "FROM stage_alternates ORDER BY alternate_name_id"
        ),
    }[table]
    cursor = connection.execute(query)
    digest = hashlib.sha256()
    while rows := cursor.fetchmany(MAX_ARROW_BATCH_ROWS):
        for row in rows:
            document = row[-1]
            value = _strict_json(document, f"{table} document")
            if not isinstance(value, dict):
                raise FullSourceStageError(f"{table} document must be a JSON object")
            if _canonical_json(value) != document:
                raise FullSourceStageError(f"{table} contains non-canonical JSON")
            if table == "stage_places":
                valid = (row[0], row[1]) == (
                    value.get("geoname_id"),
                    value.get("lineage", {}).get("source_line"),
                )
            elif table == "stage_admin1":
                valid = (row[0], row[1], row[2]) == (
                    f"{value.get('country_code')}.{value.get('admin1_code')}",
                    value.get("geoname_id"),
                    value.get("lineage", {}).get("source_line"),
                )
            elif table == "stage_languages":
                codes = value.get("iso639_2") or []
                key = value.get("iso639_3") or (codes[0] if codes else value.get("iso639_1"))
                valid = (row[0], row[1]) == (key, value.get("source_line"))
            else:
                valid = (row[0], row[1], row[2]) == (
                    value.get("alternate_name_id"),
                    value.get("geoname_id"),
                    value.get("lineage", {}).get("source_line"),
                )
            if not valid:
                raise FullSourceStageError(f"{table} key columns differ from canonical JSON")
            digest.update(document.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _expected_counts(contract: FullSourceStageContract) -> dict[str, int]:
    members = {item.path: item for item in contract.alternate_names.members}
    return {
        "admin1Rows": contract.admin1.row_count,
        "alternateNameRows": members["alternateNamesV2.txt"].row_count,
        "languageRows": members["iso-languagecodes.txt"].row_count,
        "placeRows": contract.all_countries.members[0].row_count,
    }


def _source_bindings(contract: FullSourceStageContract) -> dict[str, Any]:
    bindings = full_source_bindings(contract)
    del bindings["claimBoundary"]
    return bindings


def _receipt_contract(contract: FullSourceStageContract) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "stageSchemaVersion": STAGE_SCHEMA_VERSION,
        "logicalHashVersion": LOGICAL_HASH_VERSION,
        "stagingPerformed": True,
        "publicationClaim": False,
        "policyVersions": {
            "catalogue": CATALOGUE_POLICY_VERSION,
            "names": NORMALIZATION_POLICY_VERSION,
            "rawSource": RAW_ANOMALY_POLICY_VERSION,
        },
        "toolchain": {
            "duckdb": DUCKDB_VERSION,
            "pyarrow": PYARROW_VERSION,
            "threads": 1,
            "memoryLimit": MEMORY_LIMIT,
            "maxArrowBatchRows": MAX_ARROW_BATCH_ROWS,
        },
        "sourceBindings": _source_bindings(contract),
    }


def _exact_json_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _exact_json_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _exact_json_equal(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def _validate_receipt_contract(
    document: Mapping[str, Any], contract: FullSourceStageContract
) -> None:
    expected = _receipt_contract(contract)
    if set(document) != {*expected, "counts", "logicalHashes"} or any(
        not _exact_json_equal(document.get(key), value) for key, value in expected.items()
    ):
        raise FullSourceStageError("stage receipt envelope differs from the exact contract")
    if not _exact_json_equal(document.get("counts"), _expected_counts(contract)):
        raise FullSourceStageError("stage receipt counts differ from the exact source contract")
    logical_hashes = document.get("logicalHashes")
    if (
        type(logical_hashes) is not dict
        or set(logical_hashes) != set(_expected_counts(contract))
        or any(
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in logical_hashes.values()
        )
    ):
        raise FullSourceStageError("stage receipt logical hashes differ from the exact contract")


def _receipt(connection: Any, contract: FullSourceStageContract) -> dict[str, Any]:
    counts = {
        key: int(_first_scalar(connection, f"SELECT count(*) FROM {table}"))
        for table, key in _TABLES.items()
    }
    if counts != _expected_counts(contract):
        raise FullSourceStageError("stage table counts differ from the exact source contract")
    return {
        **_receipt_contract(contract),
        "counts": counts,
        "logicalHashes": {key: _logical_hash(connection, table) for table, key in _TABLES.items()},
    }


def _load_receipt(receipt: Mapping[str, Any] | Path) -> dict[str, Any]:
    if isinstance(receipt, Path):
        with _open_regular(receipt, "stage receipt") as stream:
            raw = stream.read()
        value = _strict_json(raw, "stage receipt")
        if not isinstance(value, dict):
            raise FullSourceStageError("stage receipt must be a JSON object")
        if raw != canonical_stage_receipt_bytes(value):
            raise FullSourceStageError("stage receipt bytes are not canonical JSON")
    else:
        raw = canonical_stage_receipt_bytes(receipt)
        value = _strict_json(raw, "stage receipt")
    return value


def validate_full_source_stage(
    database: Path,
    receipt: Mapping[str, Any] | Path,
    *,
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
) -> None:
    """Reconcile one local stage and its deterministic non-publication receipt."""
    database_identity = _regular_identity(database, "stage database")
    duckdb, _ = _load_tools()
    document = _load_receipt(receipt)
    _validate_receipt_contract(document, contract)
    try:
        connection = duckdb.connect(str(database), read_only=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
                ).fetchall()
            }
            if tables != set(_TABLES):
                raise FullSourceStageError("stage database tables differ from the versioned schema")
            _validate_schema(connection)
            _reconcile(connection)
            if not _exact_json_equal(document, _receipt(connection, contract)):
                raise FullSourceStageError(
                    "stage receipt counts or logical hashes differ from the database"
                )
        finally:
            connection.close()
    finally:
        if _regular_identity(database, "stage database") != database_identity:
            raise FullSourceStageError("stage database identity changed during validation")


def build_full_source_stage(
    inputs: FullSourceStageInputs,
    output: Path,
    receipt_path: Path,
    work_dir: Path,
    *,
    batch_size: int = MAX_ARROW_BATCH_ROWS,
    contract: FullSourceStageContract = PRODUCTION_CONTRACT,
    source_order: Sequence[str] = ("places", "admin1", "alternate_names"),
) -> dict[str, Any]:
    """Build, validate, and promote a no-overwrite local stage pair."""
    if not 1 <= batch_size <= MAX_ARROW_BATCH_ROWS:
        raise FullSourceStageError(f"Arrow batch size must be within 1..{MAX_ARROW_BATCH_ROWS}")
    _require_directory(work_dir, "work directory")
    _require_directory(output.parent, "output directory")
    if receipt_path.parent != output.parent or receipt_path == output:
        raise FullSourceStageError(
            "stage database and receipt need distinct paths in one directory"
        )
    if output.exists() or output.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise FullSourceStageError("stage output already exists; overwrite is refused")
    if shutil.disk_usage(work_dir).free < contract.minimum_free_bytes:
        raise FullSourceStageError("work directory has less than the required free space")
    if shutil.disk_usage(output.parent).free < contract.minimum_free_bytes:
        raise FullSourceStageError("output directory has less than the required free space")

    _verify_outer_inputs(inputs, contract, validate_policies=True)
    duckdb, pa = _load_tools()
    stage_root = Path(tempfile.mkdtemp(prefix=".full-source-stage-", dir=work_dir))
    candidate_root = Path(tempfile.mkdtemp(prefix=".full-source-candidate-", dir=output.parent))
    candidate = candidate_root / output.name
    receipt_candidate = candidate_root / receipt_path.name
    promoted: list[Path] = []
    try:
        connection = duckdb.connect(str(candidate))
        try:
            connection.execute("SET threads=1")
            connection.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
            connection.execute("SET temp_directory=?", [str(stage_root / "spill")])
            connection.execute("SET preserve_insertion_order=false")
            _create_schema(connection)
            _stage_rows(connection, pa, inputs, contract, batch_size, source_order)
            _verify_outer_inputs(inputs, contract, validate_policies=False)
            _reconcile(connection)
            connection.execute("CHECKPOINT")
            receipt = _receipt(connection, contract)
        finally:
            connection.close()
        _fsync_file(candidate, "candidate database")
        validate_full_source_stage(candidate, receipt, contract=contract)
        with receipt_candidate.open("xb") as stream:
            stream.write(canonical_stage_receipt_bytes(receipt))
            stream.flush()
        _fsync_file(receipt_candidate, "candidate receipt")
        try:
            os.link(receipt_candidate, receipt_path)
            promoted.append(receipt_path)
            os.link(candidate, output)
            promoted.append(output)
            validate_full_source_stage(output, receipt_path, contract=contract)
            _fsync_directory(output.parent)
        except Exception:
            for path in reversed(promoted):
                path.unlink(missing_ok=True)
            _fsync_directory(output.parent)
            raise
        return receipt
    except FullSourceStageError:
        raise
    except Exception as exc:
        raise FullSourceStageError(f"full-source staging failed: {exc}") from exc
    finally:
        shutil.rmtree(candidate_root, ignore_errors=True)
        shutil.rmtree(stage_root, ignore_errors=True)
