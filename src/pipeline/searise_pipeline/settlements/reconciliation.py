"""Receipt-bound settlement reconciliation evidence."""

from __future__ import annotations

import hashlib
import heapq
import os
import re
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
from itertools import zip_longest
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from . import full_source_stage as source_stage
from . import normalized_catalogue_stage as catalogue_stage
from . import search_projection as projection
from . import spatial_asset_authority as authority
from . import spatial_classification_stage as spatial_stage
from . import spatial_stage_runner as publication
from .catalogue import REJECTION_PRECEDENCE, CataloguePlace, CatalogueRejection

RECONCILIATION_SCHEMA_VERSION = "1.0.0"
RECONCILIATION_SCHEMA_ID = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v3/"
    "reconciliation-report.schema.json"
)
POPULATION_BAND_VERSION = "settlement-population-band-v1"
POPULATION_BANDS = (
    "unknown",
    "zero",
    "1-499",
    "500-999",
    "1000-9999",
    "10000-99999",
    "100000-plus",
)
PLACE_DIMENSIONS = (
    "countries",
    "featureClasses",
    "featureCodes",
    "populationBands",
    "coastalStatuses",
)
NAME_DIMENSIONS = ("languages", "scripts")
MAX_DIMENSION_KEYS = 8192
RECONCILIATION_MEMORY_LIMIT = "4GiB"
CATALOGUE_REJECTION_REASONS = frozenset(REJECTION_PRECEDENCE)
SPATIAL_REJECTION_REASONS = frozenset({"outside-support"})

_RELEASE_ID = re.compile(r"^searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}$")
_FALSE_CLAIMS = (
    "productionClaim",
    "publicationClaim",
    "signingClaim",
    "canonicalGeometryClaim",
    "hazardExtentClaim",
    "scientificApprovalClaim",
    "ownerApprovalClaim",
)
_CATALOGUE_KEYS = {
    "catalogueStageSchemaVersion",
    "logicalHashVersion",
    "publicationClaim",
    "policyVersions",
    "inputStage",
    "counts",
    "logicalHashes",
    "deterministicIdentity",
}
_CATALOGUE_COUNT_KEYS = {
    "sourcePlaceRows",
    "sourceAlternateNameRows",
    "normalizedPlaces",
    "catalogueRejections",
    "contextNotices",
    "contextNoticeReasons",
    "nameRejectionReasons",
}


class SettlementReconciliationError(ValueError):
    """A reconciliation source, report, or publication is invalid."""


def _assert_connection_limits(connection: Any) -> None:
    actual = connection.execute(
        "SELECT current_setting('threads'), current_setting('memory_limit'), "
        "current_setting('temp_directory')"
    ).fetchone()
    if actual != (1, "4.0 GiB", ""):
        raise SettlementReconciliationError(
            "reconciliation DuckDB limits were not retained"
        )


def _configure_connection(connection: Any) -> None:
    """Keep full-corpus ordered scans bounded without unsafe external spill."""

    connection.execute("SET threads=1")
    connection.execute(f"SET memory_limit='{RECONCILIATION_MEMORY_LIMIT}'")
    connection.execute("SET temp_directory=''")
    _assert_connection_limits(connection)


def _canonical(value: object) -> bytes:
    try:
        return (source_stage._canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SettlementReconciliationError("reconciliation report is not canonical JSON") from exc


def _unsigned_identity(value: Mapping[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "deterministicIdentity"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SettlementReconciliationError(f"{label} must be a nonnegative integer")
    return value


def _catalogue_authority(
    connection: Any, receipt_asset: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw = spatial_stage._read_asset(receipt_asset)
    receipt = catalogue_stage._load_catalogue_receipt_bytes(raw)
    candidate = receipt.get("candidate")
    if (
        type(candidate) is not dict
        or set(candidate) != _CATALOGUE_KEYS
        or candidate.get("catalogueStageSchemaVersion")
        != catalogue_stage.CATALOGUE_STAGE_SCHEMA_VERSION
        or candidate.get("logicalHashVersion") != catalogue_stage.LOGICAL_HASH_VERSION
        or candidate.get("publicationClaim") is not False
        or candidate.get("policyVersions")
        != {
            "catalogue": catalogue_stage.CATALOGUE_POLICY_VERSION,
            "names": catalogue_stage.NORMALIZATION_POLICY_VERSION,
            "rawSource": catalogue_stage.RAW_ANOMALY_POLICY_VERSION,
        }
        or candidate.get("deterministicIdentity") != _unsigned_identity(candidate)
        or type(candidate.get("counts")) is not dict
        or set(candidate["counts"]) != _CATALOGUE_COUNT_KEYS
    ):
        raise SettlementReconciliationError("catalogue candidate identity differs")
    stage_binding = spatial_stage._catalogue_authority(connection, receipt)
    return (
        candidate,
        {
            "databaseSha256": "",
            "databaseByteSize": 0,
            "receiptSha256": hashlib.sha256(raw).hexdigest(),
            "receiptByteSize": len(raw),
            "stageSchemaVersion": candidate["catalogueStageSchemaVersion"],
            "candidateIdentity": candidate["deterministicIdentity"],
        },
        stage_binding,
    )


@contextmanager
def _snapshots(paths: Mapping[str, Path], work_dir: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    catalogue_database = paths["catalogue.duckdb"]
    with ExitStack() as stack:
        catalogue_parent = stack.enter_context(
            authority._open_directory_path(catalogue_database.parent, "catalogue source directory")
        )
        projection._reject_wal(catalogue_parent, catalogue_database.name)
        root, assets = stack.enter_context(projection._snapshots(paths, work_dir))
        yield root, assets
        projection._reject_wal(catalogue_parent, catalogue_database.name)
        authority._assert_directory(catalogue_parent)


def _reject_reserved_output(
    output_directory: Any,
    output_name: str,
    databases: tuple[tuple[str, Path], ...],
) -> None:
    with ExitStack() as stack:
        for label, database in databases:
            source_directory = stack.enter_context(
                authority._open_directory_path(database.parent, f"{label} source directory")
            )
            if (
                (source_directory.device, source_directory.inode)
                == (output_directory.device, output_directory.inode)
                and output_name == f"{database.name}.wal"
            ):
                raise SettlementReconciliationError(
                    f"reconciliation output collides with the reserved {label} DuckDB WAL"
                )


def _population_band(population: int | None) -> str:
    if population is None:
        return "unknown"
    if population == 0:
        return "zero"
    if population < 500:
        return "1-499"
    if population < 1_000:
        return "500-999"
    if population < 10_000:
        return "1000-9999"
    if population < 100_000:
        return "10000-99999"
    return "100000-plus"


def _increment(counter: Counter[str], key: str) -> None:
    if key not in counter and len(counter) >= MAX_DIMENSION_KEYS:
        raise SettlementReconciliationError("reconciliation dimension key limit exceeded")
    counter[key] += 1


def _decision_dimensions() -> dict[str, dict[str, Counter[str]]]:
    return {
        dimension: {"classified": Counter(), "spatialRejected": Counter()}
        for dimension in (*PLACE_DIMENSIONS, *NAME_DIMENSIONS)
    }


def _count_place(
    dimensions: dict[str, dict[str, Counter[str]]],
    name_flow: Counter[str],
    place: CataloguePlace,
    decision: str,
    coastal_status: str,
) -> None:
    keys = {
        "countries": place.country_code,
        "featureClasses": "P",
        "featureCodes": place.feature_code,
        "populationBands": _population_band(place.population),
        "coastalStatuses": coastal_status,
    }
    for dimension, key in keys.items():
        _increment(dimensions[dimension][decision], key)
    names = (place.canonical_name, *place.alternate_names)
    for name in names:
        _increment(dimensions["languages"][decision], name.language or "und")
        _increment(dimensions["scripts"][decision], name.script or "Zzzz")
    name_flow[decision] += len(names)


def _buckets(counters: Mapping[str, Counter[str]]) -> list[dict[str, Any]]:
    keys = sorted(set(counters["classified"]) | set(counters["spatialRejected"]))
    return [
        {
            "key": key,
            "classified": counters["classified"][key],
            "spatialRejected": counters["spatialRejected"][key],
            "total": counters["classified"][key] + counters["spatialRejected"][key],
        }
        for key in keys
    ]


def _catalogue_rejections(connection: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    previous = 0
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            "SELECT geoname_id, place_id, reason, document "
            "FROM catalogue_rejections ORDER BY geoname_id"
        )
        for geoname_id, place_id, reason, raw in catalogue_stage._rows(
            cursor, catalogue_stage.MAX_BATCH_ROWS
        ):
            item = catalogue_stage._document(CatalogueRejection, raw, "catalogue rejection")
            if (
                type(geoname_id) is not int
                or geoname_id <= previous
                or place_id != f"geonames:{geoname_id}"
                or item.place_id != place_id
                or item.reason != reason
            ):
                raise SettlementReconciliationError(
                    "catalogue rejection keys are duplicate, unordered, or drifted"
                )
            previous = geoname_id
            _increment(counts, reason)
    return counts


def _classified(connection: Any) -> Iterator[tuple[int, str, str, Any]]:
    for spatial, projected in projection._spatial_documents(connection):
        place_id = projected["placeId"]
        yield (
            int(place_id.removeprefix("geonames:")),
            place_id,
            "classified",
            (
                spatial,
                projected,
            ),
        )


def _rejected(connection: Any) -> Iterator[tuple[int, str, str, Any]]:
    for geoname_id, place_id, reason, raw in spatial_stage._stored_rows(
        connection, "spatial_rejections"
    ):
        document = source_stage._strict_json(raw, "spatial rejection document")
        if (
            type(document) is not dict
            or source_stage._canonical_json(document) != raw
            or document
            != {
                "lineage": document.get("lineage"),
                "placeId": place_id,
                "reason": reason,
            }
            or reason != "outside-support"
        ):
            raise SettlementReconciliationError("spatial rejection document differs")
        yield geoname_id, place_id, "spatialRejected", document


def _spatial_decisions(connection: Any) -> Iterator[tuple[int, str, str, Any]]:
    yield from heapq.merge(_classified(connection), _rejected(connection), key=lambda row: row[0])


def _reconcile(
    catalogue: Any,
    spatial: Any,
) -> tuple[dict[str, int], dict[str, int], dict[str, list[dict[str, Any]]], Counter[str]]:
    dimensions = _decision_dimensions()
    name_flow: Counter[str] = Counter()
    spatial_rejections: Counter[str] = Counter()
    missing = object()
    classified = rejected = 0
    places = spatial_stage._catalogue_places(catalogue)
    decisions = _spatial_decisions(spatial)
    for place, decision in zip_longest(places, decisions, fillvalue=missing):
        if place is missing or decision is missing:
            raise SettlementReconciliationError(
                "normalized catalogue and spatial decision inventories differ"
            )
        geoname_id, place_id, kind, payload = decision
        if place.id != place_id or int(place.id.removeprefix("geonames:")) != geoname_id:
            raise SettlementReconciliationError(
                "normalized catalogue and spatial decision identities differ"
            )
        if kind == "classified":
            spatial_document, projected = payload
            if projection._projection_document(place, spatial_document) != projected:
                raise SettlementReconciliationError(
                    "classified spatial place differs from normalized catalogue"
                )
            status = "coastal" if spatial_document["coastalCovers"] else "inland"
            _count_place(dimensions, name_flow, place, "classified", status)
            classified += 1
        else:
            expected_lineage = [source_stage._json_value(item) for item in place.lineage]
            if payload["lineage"] != expected_lineage:
                raise SettlementReconciliationError(
                    "spatial rejection lineage differs from normalized catalogue"
                )
            _count_place(dimensions, name_flow, place, "spatialRejected", "outside-support")
            _increment(spatial_rejections, payload["reason"])
            rejected += 1
    return (
        {"classified": classified, "spatialRejected": rejected},
        {
            "classifiedSelectedNames": name_flow["classified"],
            "spatialRejectedSelectedNames": name_flow["spatialRejected"],
            "selectedNames": name_flow["classified"] + name_flow["spatialRejected"],
        },
        {name: _buckets(dimensions[name]) for name in dimensions},
        spatial_rejections,
    )


def _reason_buckets(counts: Counter[str]) -> list[dict[str, Any]]:
    return [{"reason": reason, "count": counts[reason]} for reason in sorted(counts)]


def _report(
    data_release_id: str,
    catalogue_candidate: Mapping[str, Any],
    spatial_candidate: Mapping[str, Any],
    catalogue_binding: Mapping[str, Any],
    spatial_binding: Mapping[str, Any],
    decisions: Mapping[str, int],
    name_flow: Mapping[str, int],
    dimensions: Mapping[str, list[dict[str, Any]]],
    catalogue_rejections: Counter[str],
    spatial_rejections: Counter[str],
) -> dict[str, Any]:
    counts = catalogue_candidate["counts"]
    value = {
        "$schema": RECONCILIATION_SCHEMA_ID,
        "schemaVersion": RECONCILIATION_SCHEMA_VERSION,
        "reportType": "settlement-reconciliation",
        "dataReleaseId": data_release_id,
        "dataProvenanceClass": spatial_candidate["geometry"]["dataProvenanceClass"],
        "geometryStatus": spatial_candidate["geometry"]["geometryStatus"],
        **{claim: False for claim in _FALSE_CLAIMS},
        "sourceBindings": {
            "catalogue": dict(catalogue_binding),
            "spatial": dict(spatial_binding),
        },
        "method": {
            "populationBandVersion": POPULATION_BAND_VERSION,
            "populationBandOrder": list(POPULATION_BANDS),
            "placeDimensionUnit": "normalized-place",
            "nameDimensionUnit": "selected-normalized-name",
            "missingLanguageKey": "und",
            "missingScriptKey": "Zzzz",
        },
        "recordFlow": {
            "sourcePlaceRows": counts["sourcePlaceRows"],
            "catalogueAccepted": counts["normalizedPlaces"],
            "catalogueRejected": counts["catalogueRejections"],
            "spatialClassified": decisions["classified"],
            "spatialRejected": decisions["spatialRejected"],
        },
        "nameFlow": dict(name_flow),
        "rejections": {
            "catalogue": _reason_buckets(catalogue_rejections),
            "spatial": _reason_buckets(spatial_rejections),
        },
        "dimensions": {name: dimensions[name] for name in (*PLACE_DIMENSIONS, *NAME_DIMENSIONS)},
    }
    return {**value, "deterministicIdentity": hashlib.sha256(_canonical(value)).hexdigest()}


def _validate_bucket_array(
    value: object,
    label: str,
) -> tuple[int, int, int, set[str]]:
    if type(value) is not list:
        raise SettlementReconciliationError(f"{label} buckets are invalid")
    previous: str | None = None
    totals = [0, 0, 0]
    keys: set[str] = set()
    for bucket in value:
        if type(bucket) is not dict or set(bucket) != {
            "key",
            "classified",
            "spatialRejected",
            "total",
        }:
            raise SettlementReconciliationError(f"{label} bucket fields differ")
        key = bucket["key"]
        if type(key) is not str or not key or (previous is not None and key <= previous):
            raise SettlementReconciliationError(f"{label} bucket keys are not ordered and unique")
        classified = _nonnegative_integer(bucket["classified"], f"{label} classified")
        rejected = _nonnegative_integer(bucket["spatialRejected"], f"{label} spatial rejected")
        total = _nonnegative_integer(bucket["total"], f"{label} total")
        if classified + rejected != total or total == 0:
            raise SettlementReconciliationError(f"{label} bucket arithmetic differs")
        previous = key
        keys.add(key)
        totals[0] += classified
        totals[1] += rejected
        totals[2] += total
    return totals[0], totals[1], totals[2], keys


def _validate_reasons(
    value: object,
    label: str,
    expected: int,
    supported: frozenset[str],
) -> None:
    if type(value) is not list:
        raise SettlementReconciliationError(f"{label} rejection reasons are invalid")
    previous: str | None = None
    total = 0
    for bucket in value:
        if type(bucket) is not dict or set(bucket) != {"reason", "count"}:
            raise SettlementReconciliationError(f"{label} rejection reason fields differ")
        reason = bucket["reason"]
        count = bucket["count"]
        if (
            type(reason) is not str
            or not reason
            or (previous is not None and reason <= previous)
            or type(count) is not int
            or count < 1
        ):
            raise SettlementReconciliationError(
                f"{label} rejection reasons are not ordered, unique, and positive"
            )
        if reason not in supported:
            raise SettlementReconciliationError(f"{label} rejection reason is unsupported")
        previous = reason
        total += count
    if total != expected:
        raise SettlementReconciliationError(f"{label} rejection total differs")


def validate_reconciliation_report_semantics(document: Mapping[str, Any]) -> None:
    """Validate cross-field reconciliation arithmetic and deterministic identity."""

    try:
        if type(document) is not dict:
            raise SettlementReconciliationError("reconciliation report must be an object")
        flow = document["recordFlow"]
        names = document["nameFlow"]
        dimensions = document["dimensions"]
        rejections = document["rejections"]
        if any(document.get(claim) is not False for claim in _FALSE_CLAIMS):
            raise SettlementReconciliationError("reconciliation report broadened a claim")
        if document.get("deterministicIdentity") != _unsigned_identity(document):
            raise SettlementReconciliationError("reconciliation deterministic identity differs")
        source = _nonnegative_integer(flow["sourcePlaceRows"], "source place rows")
        accepted = _nonnegative_integer(flow["catalogueAccepted"], "catalogue accepted")
        catalogue_rejected = _nonnegative_integer(flow["catalogueRejected"], "catalogue rejected")
        classified = _nonnegative_integer(flow["spatialClassified"], "spatial classified")
        spatial_rejected = _nonnegative_integer(flow["spatialRejected"], "spatial rejected")
        if source != accepted + catalogue_rejected:
            raise SettlementReconciliationError(
                "source records do not equal catalogue accepted plus catalogue rejected"
            )
        if accepted != classified + spatial_rejected:
            raise SettlementReconciliationError(
                "catalogue accepted does not equal classified plus spatial rejected"
            )
        classified_names = _nonnegative_integer(
            names["classifiedSelectedNames"], "classified selected names"
        )
        rejected_names = _nonnegative_integer(
            names["spatialRejectedSelectedNames"], "spatial rejected selected names"
        )
        selected_names = _nonnegative_integer(names["selectedNames"], "selected names")
        if selected_names != classified_names + rejected_names:
            raise SettlementReconciliationError("selected-name flow arithmetic differs")
        for dimension in PLACE_DIMENSIONS:
            observed = _validate_bucket_array(dimensions[dimension], dimension)
            if observed[:3] != (classified, spatial_rejected, accepted):
                raise SettlementReconciliationError(f"{dimension} totals differ from record flow")
        for dimension in NAME_DIMENSIONS:
            observed = _validate_bucket_array(dimensions[dimension], dimension)
            if observed[:3] != (classified_names, rejected_names, selected_names):
                raise SettlementReconciliationError(f"{dimension} totals differ from name flow")
        population_keys = _validate_bucket_array(dimensions["populationBands"], "populationBands")[
            3
        ]
        if population_keys - set(POPULATION_BANDS):
            raise SettlementReconciliationError("population band key is unsupported")
        feature_classes = _validate_bucket_array(dimensions["featureClasses"], "featureClasses")[3]
        if feature_classes - {"P"}:
            raise SettlementReconciliationError("feature class key is unsupported")
        coastal = {bucket["key"]: bucket for bucket in dimensions["coastalStatuses"]}
        if set(coastal) - {"coastal", "inland", "outside-support"}:
            raise SettlementReconciliationError("coastal status key is unsupported")
        if any(
            coastal.get(key, {}).get(field, 0) != 0
            for key, field in (
                ("coastal", "spatialRejected"),
                ("inland", "spatialRejected"),
                ("outside-support", "classified"),
            )
        ):
            raise SettlementReconciliationError("coastal status decision differs")
        _validate_reasons(
            rejections["catalogue"],
            "catalogue",
            catalogue_rejected,
            CATALOGUE_REJECTION_REASONS,
        )
        _validate_reasons(
            rejections["spatial"],
            "spatial",
            spatial_rejected,
            SPATIAL_REJECTION_REASONS,
        )
    except SettlementReconciliationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SettlementReconciliationError("reconciliation report fields differ") from exc


def _build_from_snapshots(
    root: Path,
    assets: Mapping[str, Any],
    data_release_id: str,
) -> dict[str, Any]:
    duckdb, _ = source_stage._load_tools()
    with duckdb.connect(str(root / "catalogue.duckdb"), read_only=True) as catalogue:
        with duckdb.connect(str(root / "spatial.duckdb"), read_only=True) as spatial:
            _configure_connection(catalogue)
            _configure_connection(spatial)
            catalogue_candidate, catalogue_binding, catalogue_stage_binding = _catalogue_authority(
                catalogue, assets["catalogue-receipt.json"]
            )
            spatial_candidate, spatial_receipt_sha = projection._candidate(
                assets["spatial-receipt.json"]
            )
            projection._validate_source(spatial, spatial_candidate)
            if spatial_candidate["inputCatalogue"] != catalogue_stage_binding:
                raise SettlementReconciliationError(
                    "spatial candidate input catalogue binding differs"
                )
            catalogue_binding.update(
                databaseSha256=assets["catalogue.duckdb"].sha256,
                databaseByteSize=assets["catalogue.duckdb"].size,
            )
            spatial_binding = {
                "databaseSha256": assets["spatial.duckdb"].sha256,
                "databaseByteSize": assets["spatial.duckdb"].size,
                "receiptSha256": spatial_receipt_sha,
                "receiptByteSize": assets["spatial-receipt.json"].size,
                "stageSchemaVersion": spatial_candidate["spatialStageSchemaVersion"],
                "candidateIdentity": spatial_candidate["deterministicIdentity"],
                "geometryContractSha256": spatial_candidate["geometry"]["contractSha256"],
            }
            catalogue_rejections = _catalogue_rejections(catalogue)
            decisions, name_flow, dimensions, spatial_rejections = _reconcile(catalogue, spatial)
            report = _report(
                data_release_id,
                catalogue_candidate,
                spatial_candidate,
                catalogue_binding,
                spatial_binding,
                decisions,
                name_flow,
                dimensions,
                catalogue_rejections,
                spatial_rejections,
            )
            _assert_connection_limits(catalogue)
            _assert_connection_limits(spatial)
    validate_reconciliation_report_semantics(report)
    return report


def _close_after_commit(descriptor: int) -> None:
    """Best-effort close that cannot reverse an already committed report."""

    try:
        os.close(descriptor)
    except BaseException:
        pass


def build_settlement_reconciliation_report(
    catalogue_database: Path,
    catalogue_receipt: Path,
    spatial_database: Path,
    spatial_receipt: Path,
    output: Path,
    *,
    data_release_id: str,
    work_dir: Path,
) -> dict[str, Any]:
    """Build, validate, and immutably publish one canonical reconciliation report."""

    if type(data_release_id) is not str or _RELEASE_ID.fullmatch(data_release_id) is None:
        raise SettlementReconciliationError("data release id is invalid")
    stack = ExitStack()
    output_directory = private = expected = commit_directory = None
    private_name = ""
    owned: list[tuple] = []
    private_cleaned = promoted = committed = False
    commit_descriptor = -1
    try:
        output_directory = stack.enter_context(
            authority._open_directory_path(output.parent, "reconciliation output directory")
        )
        authority._assert_secure_work_directory(output_directory)
        _reject_reserved_output(
            output_directory,
            output.name,
            (
                ("catalogue", catalogue_database),
                ("spatial", spatial_database),
            ),
        )
        if not publication._absent(output_directory, output.name):
            raise SettlementReconciliationError(
                "reconciliation output exists; overwrite is refused"
            )
        private_name, private = authority._create_private(output_directory)
        authority._stack_close(stack, private.descriptor)
        with _snapshots(
            {
                "catalogue.duckdb": catalogue_database,
                "catalogue-receipt.json": catalogue_receipt,
                "spatial.duckdb": spatial_database,
                "spatial-receipt.json": spatial_receipt,
            },
            work_dir,
        ) as (root, assets):
            report = _build_from_snapshots(root, assets, data_release_id)
        publication._write_owned(private, output.name, _canonical(report), owned)
        with authority._open_asset(
            private, PurePosixPath(output.name), "staged reconciliation report"
        ) as staged:
            expected = staged
            publication._fsync_asset(staged)
            publication._fsync_directory(private)
            publication._link_no_overwrite(private, output.name, output_directory)
            promoted = True
            publication._fsync_directory(output_directory)
            publication._assert_binding(output_directory, output.name, staged)
            authority._assert_directory(output_directory)
        authority._remove_private(output_directory, private_name, private, tuple(owned), ())
        private_cleaned = True
        publication._fsync_directory(output_directory)
        authority._assert_directory(output_directory)
        commit_descriptor = os.dup(output_directory.descriptor)
        commit_directory = output_directory._replace(descriptor=commit_descriptor)
        stack.close()
        with authority._open_directory_path(
            output.parent, "final reconciliation output directory"
        ) as final_directory:
            if (final_directory.device, final_directory.inode) != (
                commit_directory.device,
                commit_directory.inode,
            ):
                raise SettlementReconciliationError(
                    "reconciliation output directory identity changed"
                )
            with authority._open_asset(
                final_directory, PurePosixPath(output.name), "reconciliation output"
            ) as published:
                if (
                    (published.device, published.inode) != (expected.device, expected.inode)
                    or published.size != expected.size
                    or published.sha256 != expected.sha256
                ):
                    raise SettlementReconciliationError("reconciliation output identity changed")
        committed = True
        _close_after_commit(commit_descriptor)
        commit_descriptor = -1
        return report
    except BaseException as primary:
        if committed:
            if commit_descriptor >= 0:
                _close_after_commit(commit_descriptor)
            return report
        rollback = commit_directory or output_directory
        if promoted and expected is not None and rollback is not None:
            publication._rollback_publication(
                primary, rollback, rollback, [(output.name, expected)]
            )
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
        if isinstance(primary, SettlementReconciliationError):
            raise
        if isinstance(primary, Exception):
            raise SettlementReconciliationError(
                f"settlement reconciliation failed: {primary}"
            ) from primary
        raise
