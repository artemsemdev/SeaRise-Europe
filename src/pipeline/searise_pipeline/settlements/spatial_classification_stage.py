from __future__ import annotations

import hashlib
import os
from collections import namedtuple
from contextlib import ExitStack, closing, contextmanager
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import full_source_stage as source_stage
from . import normalized_catalogue_stage as catalogue_stage
from . import spatial_asset_authority as asset_authority
from .catalogue import CataloguePlace
from .spatial_asset_authority import (
    SpatialAssetAuthorityError,
    SpatialAssetPaths,
    prepare_spatial_asset_authority,
)
from .spatial_classification import (
    CORE_CAPITAL_FEATURE_CODES,
    SPATIAL_TOOLCHAIN_MANIFEST_SHA256,
    SpatialClassificationError,
    SpatialResultRow,
    _numeric_place_id,
    classification_sql,
)

SPATIAL_STAGE_SCHEMA_VERSION = "spatial-classification-stage-v1"
MAX_BATCH_ROWS = source_stage.MAX_ARROW_BATCH_ROWS
SpatialAssetInputs = namedtuple(
    "SpatialAssetInputs",
    "repository_root spatial_cache_root work_dir toolchain_manifest_path evidence geometry",
)

_COLUMNS = {
    "spatial_places": (
        ("geoname_id", "UBIGINT"),
        ("place_id", "VARCHAR"),
        ("document", "VARCHAR"),
    ),
    "spatial_rejections": (
        ("geoname_id", "UBIGINT"),
        ("place_id", "VARCHAR"),
        ("reason", "VARCHAR"),
        ("document", "VARCHAR"),
    ),
}
_INSERTS = {
    table: f"INSERT INTO {table} VALUES ({','.join('?' for _ in columns)})"
    for table, columns in _COLUMNS.items()
}
_COLUMN_SQL = (
    "SELECT column_name, data_type, NOT is_nullable FROM duckdb_columns() WHERE "
    "database_name=current_database() AND schema_name='main' AND table_name=? ORDER BY column_index"
)
_OBJECTS_SQL = (
    "WITH current AS (SELECT current_database() AS name) SELECT 'table',schema_name,table_name FROM duckdb_tables(),current WHERE database_name IN (current.name,'temp') AND NOT internal "  # noqa: E501
    "UNION ALL SELECT 'view',schema_name,view_name FROM duckdb_views(),current WHERE database_name IN (current.name,'temp') AND NOT internal UNION ALL SELECT 'schema',schema_name,schema_name FROM duckdb_schemas(),current WHERE database_name IN (current.name,'temp') AND NOT internal "  # noqa: E501
    "UNION ALL SELECT 'sequence',schema_name,sequence_name FROM duckdb_sequences(),current WHERE database_name IN (current.name,'temp') UNION ALL SELECT 'type',schema_name,type_name FROM duckdb_types(),current WHERE database_name IN (current.name,'temp') AND NOT internal "  # noqa: E501
    "UNION ALL SELECT 'function',schema_name,function_name FROM duckdb_functions(),current WHERE database_name IN (current.name,'temp') AND NOT internal "  # noqa: E501
    "UNION ALL SELECT 'index',schema_name,index_name FROM duckdb_indexes(),current WHERE database_name IN (current.name,'temp')"  # noqa: E501
)


class SpatialStageError(ValueError):
    """A spatial candidate, receipt, or bound authority is invalid."""


_CAPABILITY_KEY = object()


class _NativeSpatialCapability:
    __slots__ = ("_active", "_assets")

    def __init__(self, key, assets, geometry):  # type: ignore[no-untyped-def]
        expected = tuple((item.role, item.sha256) for item in geometry.items)
        observed = tuple((item.role, item.sha256) for item in assets.geometries)
        if (
            key is not _CAPABILITY_KEY
            or type(assets) is not SpatialAssetPaths
            or assets.manifest_sha256 != SPATIAL_TOOLCHAIN_MANIFEST_SHA256
            or assets.extension_sha256 != assets.evidence.extension_sha256
            or assets.geometry_contract_sha256 != geometry.contract_sha256
            or observed != expected
        ):
            raise SpatialStageError("native spatial capability identity differs")
        self._active, self._assets = True, assets

    def _use(self) -> SpatialAssetPaths:
        if not self._active:
            raise SpatialStageError("native spatial capability expired")
        return self._assets

    def _load(self, connection: Any) -> None:
        path = str(self._use().extension_path).replace("'", "''")
        connection.execute(f"LOAD '{path}'")

    def _read_geometries(self, connection: Any) -> None:
        for item in self._use().geometries:
            connection.execute(
                "INSERT INTO spatial_geometry_parts SELECT ?, geom FROM ST_Read(?)",
                [item.role, str(item.path)],
            )


@contextmanager
def _native_authority(inputs: SpatialAssetInputs) -> Iterator[_NativeSpatialCapability]:
    if type(inputs) is not SpatialAssetInputs:
        raise SpatialStageError("spatial asset inputs are invalid")
    try:
        with prepare_spatial_asset_authority(**inputs._asdict()) as assets:
            capability = _NativeSpatialCapability(_CAPABILITY_KEY, assets, inputs.geometry)
            try:
                yield capability
            finally:
                capability._active = False
    except SpatialAssetAuthorityError as exc:
        raise SpatialStageError(f"spatial asset authority failed: {exc}") from exc


def _schema_objects(connection: Any) -> set[tuple[str, str, str]]:
    return set(catalogue_stage._rows(connection.execute(_OBJECTS_SQL), MAX_BATCH_ROWS))


def _create_schema(connection: Any) -> None:
    if _schema_objects(connection):
        raise SpatialStageError("spatial candidate connection must start empty")
    for table, columns in _COLUMNS.items():
        definition = ", ".join(f"{name} {kind} NOT NULL" for name, kind in columns)
        connection.execute(f"CREATE TABLE {table}({definition})")


def _validate_schema(connection: Any) -> None:
    expected = {("table", "main", table) for table in _COLUMNS}
    if _schema_objects(connection) != expected:
        raise SpatialStageError("spatial database objects differ from the versioned schema")
    for table, columns in _COLUMNS.items():
        actual = tuple(
            catalogue_stage._rows(connection.execute(_COLUMN_SQL, [table]), MAX_BATCH_ROWS)
        )
        if actual != tuple((name, kind, True) for name, kind in columns):
            raise SpatialStageError(f"{table} columns differ from the versioned schema")


def _catalogue_authority(connection: Any, receipt: Mapping[str, Any]) -> dict[str, Any]:
    identity = receipt.get("candidate")
    if type(identity) is not dict:
        raise SpatialStageError("catalogue receipt candidate is invalid")
    catalogue_stage._validate_receipt(identity, receipt)
    unsigned = {key: value for key, value in identity.items() if key != "deterministicIdentity"}
    canonical = (source_stage._canonical_json(unsigned) + "\n").encode()
    if identity.get("deterministicIdentity") != hashlib.sha256(canonical).hexdigest():
        raise SpatialStageError("catalogue authority deterministic identity differs")
    catalogue_stage._validate_schema(connection)
    if identity.get("publicationClaim") is not False:
        raise SpatialStageError("catalogue authority makes a publication claim")
    tables = {**catalogue_stage._DOCUMENT_TABLES, **catalogue_stage._COUNT_TABLES}
    for table, count_name in tables.items():
        count = source_stage._first_scalar(connection, f"SELECT count(*) FROM {table}")
        if count != identity["counts"][count_name]:
            raise SpatialStageError(f"catalogue authority {table} count differs")
        observed_hash = catalogue_stage._logical_hash(connection, table)
        if observed_hash != identity["logicalHashes"][count_name]:
            raise SpatialStageError(f"catalogue authority {table} hash differs")
    return {
        "receiptSha256": hashlib.sha256(
            catalogue_stage.canonical_catalogue_receipt_bytes(receipt)
        ).hexdigest(),
        "stageSchemaVersion": identity["catalogueStageSchemaVersion"],
        "deterministicIdentity": identity["deterministicIdentity"],
        "normalizedPlacesSha256": identity["logicalHashes"]["normalizedPlaces"],
    }


def _catalogue_places(connection: Any) -> Iterator[CataloguePlace]:
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            "SELECT geoname_id, place_id, document FROM catalogue_places ORDER BY geoname_id"
        )
        last_id = 0
        for geoname_id, place_id, document in catalogue_stage._rows(cursor, MAX_BATCH_ROWS):
            place = catalogue_stage._document(CataloguePlace, document, "catalogue place")
            source_id = _numeric_place_id(place.id)
            if (
                geoname_id <= last_id
                or source_id != geoname_id
                or place_id != place.id
                or not place.lineage
                or place.lineage[0].source_record_id != source_id
            ):
                raise SpatialStageError("catalogue place keys are duplicate, unordered, or drifted")
            last_id = geoname_id
            yield place


def _spatial_rows(connection, catalogue, capability):  # type: ignore[no-untyped-def]
    created = []

    def cleanup(_: None) -> None:
        command = ";".join(f"DROP TABLE temp.main.{name}" for name in reversed(created))
        if command:
            connection.execute(command)

    with asset_authority._validated(None, (None,), cleanup):
        for definition in (
            "spatial_place_input(place_id VARCHAR NOT NULL,latitude DOUBLE NOT NULL,longitude DOUBLE NOT NULL)",  # noqa: E501
            "spatial_geometry_parts(role VARCHAR NOT NULL,geometry GEOMETRY NOT NULL)",
            "spatial_geometry_input(role VARCHAR NOT NULL,geometry GEOMETRY NOT NULL)",
        ):
            name = definition.partition("(")[0]
            connection.execute(f"CREATE TEMP TABLE {definition}")
            created.append(name)
        batch = []
        for place in _catalogue_places(catalogue):
            batch.append((place.id, place.latitude, place.longitude))
            if len(batch) == MAX_BATCH_ROWS:
                connection.executemany("INSERT INTO spatial_place_input VALUES (?, ?, ?)", batch)
                batch.clear()
        if batch:
            connection.executemany("INSERT INTO spatial_place_input VALUES (?, ?, ?)", batch)
        capability._read_geometries(connection)
        connection.execute(
            "INSERT INTO spatial_geometry_input "
            "SELECT role, ST_Collect(list(geometry ORDER BY rowid)) "
            "FROM spatial_geometry_parts GROUP BY role"
        )
        for row in catalogue_stage._rows(connection.execute(classification_sql()), MAX_BATCH_ROWS):
            yield SpatialResultRow(*row)


def _expected_rows(places, rows):  # type: ignore[no-untyped-def]
    missing = object()
    previous = 0
    for place, row in zip_longest(places, rows, fillvalue=missing):
        if place is missing:
            if _numeric_place_id(row.place_id) <= previous:
                raise SpatialClassificationError(
                    f"duplicate or unordered spatial result {row.place_id}"
                )
            raise SpatialClassificationError(f"orphan spatial result {row.place_id}")
        if row is missing:
            raise SpatialClassificationError(f"missing spatial result {place.id}")
        source_id = _numeric_place_id(row.place_id)
        if source_id <= previous:
            raise SpatialClassificationError(
                f"duplicate or unordered spatial result {row.place_id}"
            )
        previous = source_id
        if row.place_id != place.id:
            kind = "orphan" if source_id < _numeric_place_id(place.id) else "missing"
            identifier = row.place_id if kind == "orphan" else place.id
            raise SpatialClassificationError(f"{kind} spatial result {identifier}")
        distance = row.distance_to_shoreline_meters
        if (
            type(row.support_covers) is not bool
            or type(row.coastal_covers) is not bool
            or type(distance) is not int
            or distance < 0
        ):
            raise SpatialClassificationError(f"invalid spatial result {place.id}")
        if row.coastal_covers and not row.support_covers:
            raise SpatialClassificationError(f"coastal coverage exceeds support {place.id}")
        if not row.support_covers:
            document = {"lineage": place.lineage, "placeId": place.id, "reason": "outside-support"}
            yield (
                "spatial_rejections",
                (source_id, place.id, "outside-support", source_stage._canonical_json(document)),
                False,
                False,
            )
            continue
        core = (place.population is not None and place.population >= 500) or (
            place.feature_code in CORE_CAPITAL_FEATURE_CODES
        )
        membership = (("europe-core",) if core else ()) + (
            ("europe-coastal",) if row.coastal_covers else ()
        )
        document = {
            "catalogMembership": membership,
            "coastalCovers": row.coastal_covers,
            "distanceToShorelineMeters": distance,
            "place": place,
            "supportCovers": True,
        }
        yield (
            "spatial_places",
            (source_id, place.id, source_stage._canonical_json(document)),
            core,
            row.coastal_covers,
        )


def _stored_rows(connection: Any, table: str) -> Iterator[tuple[Any, ...]]:
    columns = ", ".join(name for name, _ in _COLUMNS[table])
    with closing(connection.cursor()) as cursor:
        yield from catalogue_stage._rows(
            cursor.execute(f"SELECT {columns} FROM {table} ORDER BY geoname_id"), MAX_BATCH_ROWS
        )


def _evaluate(catalogue, candidate, rows, *, write):  # type: ignore[no-untyped-def]
    names = (
        "normalizedPlaces classifiedPlaces spatialRejections europeCoreMemberships "
        "europeCoastalMemberships outsideSupportRejections"
    )
    counts = dict.fromkeys(names.split(), 0)
    digests = {table: hashlib.sha256() for table in _COLUMNS}
    pending: dict[str, list[tuple[Any, ...]]] = {table: [] for table in _COLUMNS}
    stored = {} if write else {table: iter(_stored_rows(candidate, table)) for table in _COLUMNS}
    writer = candidate.cursor() if write else None
    # fmt: off
    with asset_authority._validated(None, (getattr(rows, "close", lambda: None),), lambda close: close()):  # noqa: E501
        # fmt: on
        try:
            for table, values, core, coastal in _expected_rows(_catalogue_places(catalogue), rows):
                counts["normalizedPlaces"] += 1
                if table == "spatial_places":
                    counts["classifiedPlaces"] += 1
                    counts["europeCoreMemberships"] += int(core)
                    counts["europeCoastalMemberships"] += int(coastal)
                else:
                    counts["spatialRejections"] += 1
                    counts["outsideSupportRejections"] += 1
                digests[table].update(values[-1].encode() + b"\n")
                if write:
                    pending[table].append(values)
                    if len(pending[table]) == MAX_BATCH_ROWS:
                        writer.executemany(_INSERTS[table], pending[table])
                        pending[table].clear()
                else:
                    try:
                        actual = next(stored[table])
                    except StopIteration as exc:
                        raise SpatialStageError(
                            f"{table} differs from exact spatial replay"
                        ) from exc
                    if actual != values:
                        raise SpatialStageError(f"{table} differs from exact spatial replay")
            if write:
                for table, values in pending.items():
                    if values:
                        writer.executemany(_INSERTS[table], values)
            else:
                for table, iterator in stored.items():
                    if next(iterator, None) is not None:
                        raise SpatialStageError(f"{table} differs from exact spatial replay")
        finally:
            if writer is not None:
                writer.close()
            for iterator in stored.values():
                iterator.close()
        return counts, {
            "classifiedPlaces": digests["spatial_places"].hexdigest(),
            "spatialRejections": digests["spatial_rejections"].hexdigest(),
        }


def _candidate_identity(catalogue_binding, geometry, evidence, counts, logical_hashes):  # type: ignore[no-untyped-def]
    value = {
        "spatialStageSchemaVersion": SPATIAL_STAGE_SCHEMA_VERSION,
        "logicalHashVersion": "canonical-jsonl-v1",
        "publicationClaim": False,
        "canonicalGeometryClaim": False,
        "hazardExtentClaim": False,
        "scientificApprovalClaim": False,
        "ownerApprovalClaim": False,
        "inputCatalogue": dict(catalogue_binding),
        "geometry": {
            "contractSha256": geometry.contract_sha256,
            "dataProvenanceClass": geometry.data_provenance_class,
            "geometryStatus": geometry.geometry_status,
            "publicationEligible": geometry.publication_eligible,
            "geometries": [item.__dict__ for item in geometry.items],
        },
        "method": {
            "predicate": "ST_Covers",
            "metricCrs": "EPSG:3035",
            "distanceMethodVersion": "epsg3035-planar-whole-meter-half-even-v1",
            "classificationSqlSha256": hashlib.sha256(classification_sql().encode()).hexdigest(),
        },
        "toolchain": {
            "platform": evidence.platform,
            "duckdb": evidence.duckdb_version,
            "extensionPath": evidence.extension_path,
            "extensionSha256": evidence.extension_sha256,
            "manifestSha256": SPATIAL_TOOLCHAIN_MANIFEST_SHA256,
            "threads": 1,
            "memoryLimit": source_stage.MEMORY_LIMIT,
        },
        "counts": dict(counts),
        "logicalHashes": dict(logical_hashes),
    }
    raw = (source_stage._canonical_json(value) + "\n").encode()
    return {**value, "deterministicIdentity": hashlib.sha256(raw).hexdigest()}


def _run(catalogue, candidate, receipt, inputs, native, *, write):  # type: ignore[no-untyped-def]
    catalogue_stage._configure_connection(catalogue, inputs.work_dir, "catalogue")
    catalogue_stage._configure_connection(candidate, inputs.work_dir, "candidate")
    binding = _catalogue_authority(catalogue, receipt)
    if write:
        candidate.execute("SET preserve_insertion_order=false")
        _create_schema(candidate)
    else:
        _validate_schema(candidate)
    native._load(candidate)
    counts, hashes = _evaluate(
        catalogue, candidate, _spatial_rows(candidate, catalogue, native), write=write
    )
    _validate_schema(candidate)
    return _candidate_identity(binding, inputs.geometry, inputs.evidence, counts, hashes)


def materialize_spatial_candidate(
    catalogue: Any,
    candidate: Any,
    catalogue_receipt: Mapping[str, Any],
    *,
    asset_inputs: SpatialAssetInputs,
) -> dict[str, Any]:
    with _native_authority(asset_inputs) as native:
        return _run(catalogue, candidate, catalogue_receipt, asset_inputs, native, write=True)


def spatial_receipt(identity: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schemaVersion": 1,
        "materializationPerformed": True,
        "publicationEligible": False,
        "candidate": dict(identity),
    }
    raw = (source_stage._canonical_json(payload) + "\n").encode()
    return {**payload, "deterministicIdentity": hashlib.sha256(raw).hexdigest()}


def validate_spatial_candidate(
    catalogue: Any,
    candidate: Any,
    catalogue_receipt: Mapping[str, Any],
    spatial_receipt_document: Mapping[str, Any],
    *,
    asset_inputs: SpatialAssetInputs,
) -> dict[str, Any]:
    with _native_authority(asset_inputs) as native:
        identity = _run(catalogue, candidate, catalogue_receipt, asset_inputs, native, write=False)
        if not source_stage._exact_json_equal(spatial_receipt_document, spatial_receipt(identity)):
            raise SpatialStageError("spatial receipt differs from the exact candidate")
        return identity


def _read_asset(asset: Any) -> bytes:
    if asset.size > 1024 * 1024:
        raise SpatialAssetAuthorityError(f"{asset.label} exceeds the receipt size limit")
    value = bytearray()
    while len(value) < asset.size:
        chunk = os.pread(asset.descriptor, asset.size - len(value), len(value))
        if not chunk:
            raise SpatialAssetAuthorityError(f"{asset.label} changed while read")
        value.extend(chunk)
    asset_authority._assert_asset(asset)
    return bytes(value)


@contextmanager
def _validation_snapshots(paths, work_dir):  # type: ignore[no-untyped-def]
    with ExitStack() as stack:
        work = stack.enter_context(
            asset_authority._open_directory_path(work_dir, "spatial work directory")
        )
        asset_authority._assert_secure_work_directory(work)
        filesystem = stack.enter_context(
            asset_authority._open_directory_path(Path("/"), "filesystem root")
        )
        sources = {
            label: asset_authority._enter_asset(
                stack,
                filesystem,
                asset_authority._absolute(path, label).relative_to("/"),
                label,
            )
            for label, path in paths.items()
        }
        name, private = asset_authority._create_private(work)
        asset_authority._stack_close(stack, private.descriptor)
        snapshots, owned = {}, []

        def cleanup(_: None) -> None:
            asset_authority._remove_private(
                work, name, private, tuple(owned), tuple(snapshots.values())
            )

        with asset_authority._validated(None, (None,), cleanup):
            for label, source in sources.items():
                snapshot = asset_authority._copy_asset(source, private, label, owned)
                snapshots[label] = snapshot
                asset_authority._stack_close(stack, snapshot.descriptor)
            yield asset_authority._descriptor_path(private), snapshots


def validate_spatial_stage(
    database: Path,
    receipt: Path,
    catalogue_database: Path,
    catalogue_receipt: Path,
    *,
    asset_inputs: SpatialAssetInputs,
) -> None:
    paths = {
        "catalogue.duckdb": catalogue_database,
        "spatial.duckdb": database,
        "catalogue-receipt.json": catalogue_receipt,
        "spatial-receipt.json": receipt,
    }
    try:
        with _validation_snapshots(paths, asset_inputs.work_dir) as (root, snapshots):
            catalogue_document = catalogue_stage._load_catalogue_receipt_bytes(
                _read_asset(snapshots["catalogue-receipt.json"])
            )
            raw_receipt = _read_asset(snapshots["spatial-receipt.json"])
            spatial_document = source_stage._strict_json(raw_receipt, "spatial receipt")
            canonical = (source_stage._canonical_json(spatial_document) + "\n").encode()
            if type(spatial_document) is not dict or raw_receipt != canonical:
                raise SpatialStageError("spatial receipt is not canonical JSON")
            duckdb, _ = source_stage._load_tools()
            with duckdb.connect(str(root / "catalogue.duckdb"), read_only=True) as catalogue:
                with duckdb.connect(str(root / "spatial.duckdb"), read_only=True) as candidate:
                    validate_spatial_candidate(
                        catalogue,
                        candidate,
                        catalogue_document,
                        spatial_document,
                        asset_inputs=asset_inputs,
                    )
    except SpatialStageError:
        raise
    except Exception as exc:
        raise SpatialStageError(f"spatial stage validation failed: {exc}") from exc
