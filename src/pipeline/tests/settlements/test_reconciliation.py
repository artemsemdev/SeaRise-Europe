"""Fixture-driven settlement reconciliation production boundary tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
from datetime import date
from pathlib import Path

import duckdb
import pytest

from searise_pipeline.settlements import full_source_stage as source_stage
from searise_pipeline.settlements import normalized_catalogue_stage as catalogue_stage
from searise_pipeline.settlements import reconciliation
from searise_pipeline.settlements import spatial_classification as classification
from searise_pipeline.settlements import spatial_classification_stage as spatial_stage
from searise_pipeline.settlements.alternate_names import NameVariant
from searise_pipeline.settlements.catalogue import CataloguePlace, CatalogueRejection
from searise_pipeline.settlements.geonames import Lineage

ROOT = Path(__file__).parents[4]
GOLDEN = ROOT / "contracts/settlements/v3/fixtures/valid/settlement-reconciliation.json"
CLI_PATH = ROOT / "scripts/release/build_settlement_reconciliation.py"
RELEASE_ID = "searise-europe-v1.0.0-20260812-939053bab621"


def _canonical(value: object) -> bytes:
    return (source_stage._canonical_json(value) + "\n").encode()


def _lineage(identifier: int) -> Lineage:
    return Lineage(
        "fixture",
        "places.txt",
        "2026-08-10",
        identifier,
        identifier,
        "f" * 64,
    )


def _place(
    identifier: int,
    name: str,
    country: str,
    population: int | None,
    feature_code: str,
    language: str | None,
    script: str | None,
) -> CataloguePlace:
    return CataloguePlace(
        f"geonames:{identifier}",
        name,
        NameVariant(name, language, script),
        name,
        (NameVariant(f"{name} Alt", "de", "Latn"),),
        country,
        "A1",
        "Example",
        50.0 + identifier / 1_000_000,
        2.0 + identifier / 1_000_000,
        population,
        feature_code,
        date(2026, 8, 10),
        (_lineage(identifier),),
    )


PLACES = (
    _place(101, "Alpha", "DE", 100_000, "PPLC", "en", "Latn"),
    _place(102, "Bravo", "DE", 0, "PPL", None, "Latn"),
    _place(103, "Čarli", "HR", None, "PPL", "hr", None),
)


def _catalogue_fixture(path: Path, receipt_path: Path) -> tuple[dict, dict]:
    with duckdb.connect(str(path)) as connection:
        catalogue_stage._create_schema(connection)
        for place in PLACES:
            identifier = int(place.id.removeprefix("geonames:"))
            connection.execute(
                "INSERT INTO catalogue_places VALUES (?, ?, ?)",
                [identifier, place.id, source_stage._canonical_json(place)],
            )
        rejection = CatalogueRejection(
            "geonames:104",
            "featureCode",
            "feature-code-not-included",
            "PPLQ",
            _lineage(104),
        )
        connection.execute(
            "INSERT INTO catalogue_rejections VALUES (?, ?, ?, ?)",
            [
                104,
                rejection.place_id,
                rejection.reason,
                source_stage._canonical_json(rejection),
            ],
        )
        counts = {
            "sourcePlaceRows": 4,
            "sourceAlternateNameRows": 3,
            "normalizedPlaces": 3,
            "catalogueRejections": 1,
            "contextNotices": 0,
            "contextNoticeReasons": 0,
            "nameRejectionReasons": 0,
        }
        tables = {**catalogue_stage._DOCUMENT_TABLES, **catalogue_stage._COUNT_TABLES}
        value = {
            "catalogueStageSchemaVersion": catalogue_stage.CATALOGUE_STAGE_SCHEMA_VERSION,
            "logicalHashVersion": catalogue_stage.LOGICAL_HASH_VERSION,
            "publicationClaim": False,
            "policyVersions": {
                "catalogue": catalogue_stage.CATALOGUE_POLICY_VERSION,
                "names": catalogue_stage.NORMALIZATION_POLICY_VERSION,
                "rawSource": catalogue_stage.RAW_ANOMALY_POLICY_VERSION,
            },
            "inputStage": {"fixture": True},
            "counts": counts,
            "logicalHashes": {
                key: catalogue_stage._logical_hash(connection, table)
                for table, key in tables.items()
            },
        }
        candidate = {
            **value,
            "deterministicIdentity": hashlib.sha256(_canonical(value)).hexdigest(),
        }
    payload = catalogue_stage._receipt_payload(candidate)
    receipt = {
        **payload,
        "deterministicIdentity": catalogue_stage._receipt_identity(payload),
        "observations": {
            "completedAtUtc": "2026-08-12T00:00:00Z",
            "buildDurationSeconds": 1.0,
            "peakRssBytes": 1,
            "deterministicIdentityExcluded": True,
        },
    }
    receipt_path.write_bytes(catalogue_stage.canonical_catalogue_receipt_bytes(receipt))
    binding = {
        "receiptSha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "stageSchemaVersion": candidate["catalogueStageSchemaVersion"],
        "deterministicIdentity": candidate["deterministicIdentity"],
        "normalizedPlacesSha256": candidate["logicalHashes"]["normalizedPlaces"],
    }
    return candidate, binding


def _geometry() -> classification.GeometryBindings:
    value = classification.GeometryBindings(
        "synthetic-fixture",
        "selected-scope-approximation",
        False,
        classification.GeometryBinding(
            "support", "fixture-support", "v1", "support.json", "1" * 64, "ST_Covers"
        ),
        classification.GeometryBinding(
            "coastal", "fixture-coastal", "v1", "coastal.json", "2" * 64, "ST_Covers"
        ),
        classification.GeometryBinding(
            "shoreline",
            "fixture-shoreline",
            "v1",
            "shoreline.json",
            "3" * 64,
            "ST_Transform(EPSG:4326,EPSG:3035,always_xy=true)+"
            "CAST(ST_Distance AS BIGINT-half-even)",
        ),
        "",
    )
    return classification.GeometryBindings(
        **{**value.__dict__, "contract_sha256": classification._binding_sha256(value)}
    )


def _spatial_document(
    place: CataloguePlace, *, coastal: bool, memberships: tuple[str, ...]
) -> dict:
    return {
        "catalogMembership": memberships,
        "coastalCovers": coastal,
        "distanceToShorelineMeters": 100,
        "place": place,
        "supportCovers": True,
    }


def _spatial_fixture(path: Path, receipt_path: Path, catalogue_binding: dict) -> None:
    first = _spatial_document(
        PLACES[0], coastal=True, memberships=("europe-core", "europe-coastal")
    )
    second = _spatial_document(PLACES[1], coastal=False, memberships=())
    rejected = {
        "lineage": [source_stage._json_value(item) for item in PLACES[2].lineage],
        "placeId": PLACES[2].id,
        "reason": "outside-support",
    }
    with duckdb.connect(str(path)) as connection:
        spatial_stage._create_schema(connection)
        for place, document in ((PLACES[0], first), (PLACES[1], second)):
            identifier = int(place.id.removeprefix("geonames:"))
            connection.execute(
                "INSERT INTO spatial_places VALUES (?, ?, ?)",
                [identifier, place.id, source_stage._canonical_json(document)],
            )
        connection.execute(
            "INSERT INTO spatial_rejections VALUES (?, ?, ?, ?)",
            [103, PLACES[2].id, "outside-support", source_stage._canonical_json(rejected)],
        )
    classified_hash = hashlib.sha256()
    for document in (first, second):
        classified_hash.update(_canonical(document))
    rejected_hash = hashlib.sha256(_canonical(rejected)).hexdigest()
    geometry = _geometry()
    value = {
        "spatialStageSchemaVersion": spatial_stage.SPATIAL_STAGE_SCHEMA_VERSION,
        "logicalHashVersion": "canonical-jsonl-v1",
        "publicationClaim": False,
        "canonicalGeometryClaim": False,
        "hazardExtentClaim": False,
        "scientificApprovalClaim": False,
        "ownerApprovalClaim": False,
        "inputCatalogue": catalogue_binding,
        "geometry": {
            "contractSha256": geometry.contract_sha256,
            "dataProvenanceClass": geometry.data_provenance_class,
            "geometryStatus": geometry.geometry_status,
            "publicationEligible": geometry.publication_eligible,
            "geometries": [item.__dict__ for item in geometry.items],
        },
        "method": {"fixture": True},
        "toolchain": {"fixture": True},
        "counts": {
            "normalizedPlaces": 3,
            "classifiedPlaces": 2,
            "spatialRejections": 1,
            "europeCoreMemberships": 1,
            "europeCoastalMemberships": 1,
            "outsideSupportRejections": 1,
        },
        "logicalHashes": {
            "classifiedPlaces": classified_hash.hexdigest(),
            "spatialRejections": rejected_hash,
        },
    }
    candidate = {
        **value,
        "deterministicIdentity": hashlib.sha256(_canonical(value)).hexdigest(),
    }
    receipt_path.write_bytes(_canonical(spatial_stage.spatial_receipt(candidate)))


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    catalogue = tmp_path / "catalogue.duckdb"
    catalogue_receipt = tmp_path / "catalogue-receipt.json"
    spatial = tmp_path / "spatial.duckdb"
    spatial_receipt = tmp_path / "spatial-receipt.json"
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    _, binding = _catalogue_fixture(catalogue, catalogue_receipt)
    _spatial_fixture(spatial, spatial_receipt, binding)
    return catalogue, catalogue_receipt, spatial, spatial_receipt, work


def _build(tmp_path: Path, name: str = "report.json") -> tuple[dict, Path, tuple[Path, ...]]:
    inputs = _fixture(tmp_path)
    output = tmp_path / name
    report = reconciliation.build_settlement_reconciliation_report(
        *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
    )
    return report, output, inputs


def _residue(root: Path) -> list[Path]:
    return sorted(root.rglob(".spatial-assets-*"))


def _resign(document: dict) -> None:
    document["deterministicIdentity"] = reconciliation._unsigned_identity(document)


def _load_cli():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("settlement_reconciliation_cli", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_reconciles_distinct_stage_outcomes_and_matches_golden(tmp_path: Path) -> None:
    report, output, _ = _build(tmp_path)

    assert output.read_bytes() == _canonical(report)
    assert report == source_stage._strict_json(GOLDEN.read_bytes(), "golden")
    assert report["recordFlow"] == {
        "sourcePlaceRows": 4,
        "catalogueAccepted": 3,
        "catalogueRejected": 1,
        "spatialClassified": 2,
        "spatialRejected": 1,
    }
    assert report["rejections"] == {
        "catalogue": [{"reason": "feature-code-not-included", "count": 1}],
        "spatial": [{"reason": "outside-support", "count": 1}],
    }
    assert report["dimensions"]["coastalStatuses"] == [
        {"key": "coastal", "classified": 1, "spatialRejected": 0, "total": 1},
        {"key": "inland", "classified": 1, "spatialRejected": 0, "total": 1},
        {
            "key": "outside-support",
            "classified": 0,
            "spatialRejected": 1,
            "total": 1,
        },
    ]
    reconciliation.validate_reconciliation_report_semantics(report)


def test_report_bytes_are_deterministic_and_overwrite_is_refused(tmp_path: Path) -> None:
    report, output, inputs = _build(tmp_path)
    second = tmp_path / "second.json"
    rebuilt = reconciliation.build_settlement_reconciliation_report(
        *inputs[:4], second, data_release_id=RELEASE_ID, work_dir=inputs[4]
    )

    assert rebuilt == report
    assert second.read_bytes() == output.read_bytes()
    with pytest.raises(reconciliation.SettlementReconciliationError, match="overwrite"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )


@pytest.mark.parametrize(("database_index", "label"), [(0, "catalogue"), (2, "spatial")])
def test_reserved_database_wal_output_is_rejected_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_index: int,
    label: str,
) -> None:
    inputs = _fixture(tmp_path)
    output = Path(f"{inputs[database_index]}.wal")

    monkeypatch.setattr(
        reconciliation.authority,
        "_create_private",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("private staging must not be created")
        ),
    )

    with pytest.raises(
        reconciliation.SettlementReconciliationError,
        match=rf"reserved {label} DuckDB WAL",
    ):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )

    assert not output.exists()
    assert _residue(tmp_path) == []


@pytest.mark.parametrize(
    "failure",
    ["link", "post-link-fsync", "binding", "post-cleanup-fsync"],
)
def test_publication_failures_roll_back_owned_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "report.json"
    if failure == "link":
        monkeypatch.setattr(
            reconciliation.publication,
            "_link_no_overwrite",
            lambda *_args: (_ for _ in ()).throw(OSError("injected link failure")),
        )
    elif failure == "binding":
        monkeypatch.setattr(
            reconciliation.publication,
            "_assert_binding",
            lambda *_args: (_ for _ in ()).throw(OSError("injected binding failure")),
        )
    else:
        sync = reconciliation.publication._fsync_directory
        output_syncs = 0
        fail_on = 1 if failure == "post-link-fsync" else 2

        def fail_sync(directory) -> None:  # type: ignore[no-untyped-def]
            nonlocal output_syncs
            if directory.label == "reconciliation output directory":
                output_syncs += 1
                if output_syncs == fail_on:
                    raise OSError(f"injected {failure} failure")
            sync(directory)

        monkeypatch.setattr(reconciliation.publication, "_fsync_directory", fail_sync)

    with pytest.raises(reconciliation.SettlementReconciliationError, match="injected"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )

    assert not output.exists()
    assert _residue(tmp_path) == []


def test_private_cleanup_failure_before_commit_rolls_back_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "report.json"
    cleanup = reconciliation.authority._remove_private

    def fail_after_cleanup(*args: object) -> None:
        cleanup(*args)
        if args[0].label == "reconciliation output directory":  # type: ignore[attr-defined]
            raise OSError("injected private cleanup failure")

    monkeypatch.setattr(reconciliation.authority, "_remove_private", fail_after_cleanup)
    with pytest.raises(reconciliation.SettlementReconciliationError, match="private cleanup"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )

    assert not output.exists()
    assert _residue(tmp_path) == []


def test_racing_replacement_before_binding_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "report.json"
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(b"foreign output\n")
    sync = reconciliation.publication._fsync_directory
    output_syncs = 0

    def replace_after_link(directory) -> None:  # type: ignore[no-untyped-def]
        nonlocal output_syncs
        sync(directory)
        if directory.label == "reconciliation output directory":
            output_syncs += 1
            if output_syncs == 1:
                os.replace(foreign, output)

    monkeypatch.setattr(reconciliation.publication, "_fsync_directory", replace_after_link)
    with pytest.raises(reconciliation.SettlementReconciliationError, match="identity changed"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )

    assert output.read_bytes() == b"foreign output\n"
    assert _residue(tmp_path) == []


def test_racing_replacement_after_cleanup_fails_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "report.json"
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(b"foreign output\n")
    cleanup = reconciliation.authority._remove_private

    def replace_after_cleanup(*args: object) -> None:
        cleanup(*args)
        if args[0].label == "reconciliation output directory":  # type: ignore[attr-defined]
            os.replace(foreign, output)

    monkeypatch.setattr(reconciliation.authority, "_remove_private", replace_after_cleanup)
    with pytest.raises(reconciliation.SettlementReconciliationError, match="identity changed"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )

    assert output.read_bytes() == b"foreign output\n"
    assert _residue(tmp_path) == []


def test_commit_descriptor_close_failure_cannot_reverse_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "report.json"
    duplicate = reconciliation.os.dup
    close = reconciliation.os.close
    commit_descriptor = -1

    def record_duplicate(descriptor: int) -> int:
        nonlocal commit_descriptor
        commit_descriptor = duplicate(descriptor)
        return commit_descriptor

    def fail_commit_close(descriptor: int) -> None:
        if descriptor == commit_descriptor:
            raise OSError("injected post-commit close failure")
        close(descriptor)

    monkeypatch.setattr(reconciliation.os, "dup", record_duplicate)
    monkeypatch.setattr(reconciliation.os, "close", fail_commit_close)
    try:
        report = reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id=RELEASE_ID, work_dir=inputs[4]
        )
    finally:
        if commit_descriptor >= 0:
            close(commit_descriptor)

    assert output.read_bytes() == _canonical(report)
    assert _residue(tmp_path) == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["recordFlow"].__setitem__("sourcePlaceRows", 5),
            "catalogue accepted plus catalogue rejected",
        ),
        (
            lambda value: value["recordFlow"].__setitem__("spatialClassified", 1),
            "classified plus spatial rejected",
        ),
        (
            lambda value: value["dimensions"]["countries"][0].__setitem__("total", 3),
            "bucket arithmetic",
        ),
        (
            lambda value: value["dimensions"]["countries"].reverse(),
            "ordered and unique",
        ),
        (
            lambda value: value["nameFlow"].__setitem__("selectedNames", 7),
            "selected-name flow",
        ),
    ],
)
def test_semantic_validator_rejects_schema_valid_cross_field_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    report, _, _ = _build(tmp_path)
    changed = copy.deepcopy(report)
    mutation(changed)
    _resign(changed)

    with pytest.raises(reconciliation.SettlementReconciliationError, match=message):
        reconciliation.validate_reconciliation_report_semantics(changed)


@pytest.mark.parametrize("ledger", ["catalogue", "spatial"])
def test_semantic_validator_rejects_invented_rejection_reasons(
    tmp_path: Path, ledger: str
) -> None:
    report, _, _ = _build(tmp_path)
    changed = copy.deepcopy(report)
    changed["rejections"][ledger][0]["reason"] = f"invented-{ledger}-reason"
    _resign(changed)

    with pytest.raises(reconciliation.SettlementReconciliationError, match="unsupported"):
        reconciliation.validate_reconciliation_report_semantics(changed)


def test_source_database_drift_is_rejected_before_reporting(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    with duckdb.connect(str(inputs[2])) as connection:
        connection.execute("DELETE FROM spatial_places WHERE geoname_id=101")

    with pytest.raises(reconciliation.SettlementReconciliationError, match="receipt"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4],
            tmp_path / "report.json",
            data_release_id=RELEASE_ID,
            work_dir=inputs[4],
        )


def test_catalogue_wal_is_rejected_before_snapshot(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    Path(f"{inputs[0]}.wal").write_bytes(b"uncheckpointed")

    with pytest.raises(reconciliation.SettlementReconciliationError, match="WAL"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4],
            tmp_path / "report.json",
            data_release_id=RELEASE_ID,
            work_dir=inputs[4],
        )


def test_dimension_cardinality_is_bounded(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    inputs = _fixture(tmp_path)
    monkeypatch.setattr(reconciliation, "MAX_DIMENSION_KEYS", 1)

    with pytest.raises(reconciliation.SettlementReconciliationError, match="key limit"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4],
            tmp_path / "report.json",
            data_release_id=RELEASE_ID,
            work_dir=inputs[4],
        )


def test_invalid_release_id_fails_before_output_creation(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "report.json"

    with pytest.raises(reconciliation.SettlementReconciliationError, match="release id"):
        reconciliation.build_settlement_reconciliation_report(
            *inputs[:4], output, data_release_id="latest", work_dir=inputs[4]
        )
    assert not output.exists()


def test_cli_forwards_all_explicit_inputs_and_prints_identity(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    cli = _load_cli()
    captured = {}

    def build(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["args"], captured["kwargs"] = args, kwargs
        return {"deterministicIdentity": "a" * 64}

    monkeypatch.setattr(cli, "build_settlement_reconciliation_report", build)
    paths = [
        tmp_path / name
        for name in (
            "catalogue",
            "catalogue.json",
            "spatial",
            "spatial.json",
            "report.json",
            "work",
        )
    ]
    assert (
        cli.main(
            [
                "--catalogue-db",
                str(paths[0]),
                "--catalogue-receipt",
                str(paths[1]),
                "--spatial-db",
                str(paths[2]),
                "--spatial-receipt",
                str(paths[3]),
                "--output",
                str(paths[4]),
                "--data-release-id",
                RELEASE_ID,
                "--work-dir",
                str(paths[5]),
            ]
        )
        == 0
    )
    assert captured == {
        "args": tuple(paths[:5]),
        "kwargs": {"data_release_id": RELEASE_ID, "work_dir": paths[5]},
    }
    assert capsys.readouterr().out == "a" * 64 + "\n"
