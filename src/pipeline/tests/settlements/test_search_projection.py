"""Receipt-bound streaming search-projection contract tests."""

from __future__ import annotations

import copy
import hashlib
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterator

import duckdb
import pytest

from searise_pipeline.settlements import full_source_stage as source_stage
from searise_pipeline.settlements import search_projection as projection
from searise_pipeline.settlements import spatial_classification as classification
from searise_pipeline.settlements import spatial_classification_stage as spatial_stage
from searise_pipeline.settlements.alternate_names import NameVariant
from searise_pipeline.settlements.catalogue import CataloguePlace
from searise_pipeline.settlements.geonames import Lineage


def _canonical(value: object) -> bytes:
    return (source_stage._canonical_json(value) + "\n").encode()


def _place(identifier: int, name: str, population: int | None) -> CataloguePlace:
    return CataloguePlace(
        f"geonames:{identifier}",
        name,
        NameVariant(name, "en", "Latn"),
        name,
        (NameVariant(f"{name} Alt", "en", "Latn"),),
        "XX",
        "A1",
        "Example",
        50.0 + identifier / 1_000_000,
        2.0 + identifier / 1_000_000,
        population,
        "PPL",
        date(2026, 8, 10),
        (Lineage("fixture", "places.txt", "2026-08-10", identifier, identifier, "f" * 64),),
    )


def _spatial_document(
    place: CataloguePlace, *, memberships: list[str], coastal: bool, distance: int
) -> dict[str, object]:
    return {
        "catalogMembership": memberships,
        "coastalCovers": coastal,
        "distanceToShorelineMeters": distance,
        "place": place,
        "supportCovers": True,
    }


def _candidate(
    places: list[dict[str, object]], rejections: list[dict[str, object]]
) -> dict[str, object]:
    classified = hashlib.sha256()
    rejected = hashlib.sha256()
    core = coastal = 0
    for item in places:
        classified.update(_canonical(item))
        core += int("europe-core" in item["catalogMembership"])
        coastal += int(item["coastalCovers"] is True)
    for item in rejections:
        rejected.update(_canonical(item))
    geometry = classification.GeometryBindings(
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
    geometry = classification.GeometryBindings(
        **{**geometry.__dict__, "contract_sha256": classification._binding_sha256(geometry)}
    )
    value = {
        "spatialStageSchemaVersion": spatial_stage.SPATIAL_STAGE_SCHEMA_VERSION,
        "logicalHashVersion": "canonical-jsonl-v1",
        "publicationClaim": False,
        "canonicalGeometryClaim": False,
        "hazardExtentClaim": False,
        "scientificApprovalClaim": False,
        "ownerApprovalClaim": False,
        "inputCatalogue": {"fixture": True},
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
            "normalizedPlaces": len(places) + len(rejections),
            "classifiedPlaces": len(places),
            "spatialRejections": len(rejections),
            "europeCoreMemberships": core,
            "europeCoastalMemberships": coastal,
            "outsideSupportRejections": len(rejections),
        },
        "logicalHashes": {
            "classifiedPlaces": classified.hexdigest(),
            "spatialRejections": rejected.hexdigest(),
        },
    }
    return {**value, "deterministicIdentity": hashlib.sha256(_canonical(value)).hexdigest()}


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    database = tmp_path / "spatial.duckdb"
    receipt = tmp_path / "spatial-receipt.json"
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    first = _spatial_document(
        _place(101, "Alpha", 1_000), memberships=["europe-core"], coastal=False, distance=20
    )
    second = _spatial_document(
        _place(102, "Bravo", None),
        memberships=["europe-coastal"],
        coastal=True,
        distance=1,
    )
    rejection = {
        "lineage": [source_stage._json_value(item) for item in _place(103, "Excluded", 0).lineage],
        "placeId": "geonames:103",
        "reason": "outside-support",
    }
    candidate = _candidate([first, second], [rejection])
    document = {
        "schemaVersion": 1,
        "materializationPerformed": True,
        "publicationEligible": False,
        "candidate": candidate,
    }
    receipt.write_bytes(
        _canonical(
            {
                **document,
                "deterministicIdentity": hashlib.sha256(_canonical(document)).hexdigest(),
            }
        )
    )
    with duckdb.connect(str(database)) as connection:
        spatial_stage._create_schema(connection)
        for item in first, second:
            place = item["place"]
            connection.execute(
                "INSERT INTO spatial_places VALUES (?, ?, ?)",
                [
                    int(place.id.removeprefix("geonames:")),
                    place.id,
                    source_stage._canonical_json(item),
                ],
            )
        connection.execute(
            "INSERT INTO spatial_rejections VALUES (?, ?, ?, ?)",
            [103, "geonames:103", "outside-support", source_stage._canonical_json(rejection)],
        )
    return database, receipt, work


def test_projection_round_trip_is_deterministic_and_preserves_search_context(
    tmp_path: Path,
) -> None:
    database, receipt, work = _fixture(tmp_path)
    first, second = tmp_path / "first.ndjson", tmp_path / "second.ndjson"

    footer = projection.serialize_search_projection(database, receipt, first, work_dir=work)
    projection.serialize_search_projection(database, receipt, second, work_dir=work)

    assert first.read_bytes() == second.read_bytes()
    assert projection.validate_search_projection(database, receipt, first, work_dir=work) == footer
    lines = [
        source_stage._strict_json(line, "projection") for line in first.read_text().splitlines()
    ]
    header, document, _, footer_line = lines
    assert header["productionClaim"] is False
    assert header["signingClaim"] is False
    assert header["publicationClaim"] is False
    assert header["publicationEligible"] is False
    assert header["ownerApprovalClaim"] is False
    assert header["scientificApprovalClaim"] is False
    assert header["canonicalGeometryClaim"] is False
    assert header["hazardExtentClaim"] is False
    assert document["placeId"] == "geonames:101"
    assert document["sourceSpelling"] == document["canonicalName"]["value"] == "Alpha"
    assert document["alternateNames"] == [
        {"value": "Alpha Alt", "language": "en", "script": "Latn"}
    ]
    assert document["admin1Name"] == "Example" and document["lineage"][0]["source_record_id"] == 101
    assert document["spatialClassification"] == {
        "catalogMembership": ["europe-core"],
        "distanceToShorelineMeters": 20,
        "isCoastal": False,
    }
    assert footer_line == footer


@pytest.mark.parametrize("tamper", ["truncated", "duplicate", "reordered", "footer"])
def test_validator_rejects_tampered_or_unstable_projection(tmp_path: Path, tamper: str) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "projection.ndjson"
    projection.serialize_search_projection(database, receipt, output, work_dir=work)
    lines = output.read_bytes().splitlines(keepends=True)
    if tamper == "truncated":
        output.write_bytes(b"".join(lines[:-1]))
    elif tamper == "duplicate":
        output.write_bytes(b"".join([lines[0], lines[1], lines[1], *lines[2:]]))
    elif tamper == "reordered":
        output.write_bytes(b"".join([lines[0], lines[2], lines[1], lines[3]]))
    else:
        output.write_bytes(
            b"".join([*lines[:-1], lines[-1].replace(b'"recordCount":2', b'"recordCount":3')])
        )

    with pytest.raises(projection.SearchProjectionError):
        projection.validate_search_projection(database, receipt, output, work_dir=work)


def test_serializer_rejects_symlink_source_and_database_receipt_drift(tmp_path: Path) -> None:
    database, receipt, work = _fixture(tmp_path)
    linked = tmp_path / "linked.duckdb"
    linked.symlink_to(database)
    with pytest.raises(projection.SearchProjectionError, match="symlink|open"):
        projection.serialize_search_projection(
            linked, receipt, tmp_path / "linked.ndjson", work_dir=work
        )

    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE spatial_places SET document='{}' WHERE geoname_id=101")
    with pytest.raises(projection.SearchProjectionError, match="fields|canonical|source"):
        projection.serialize_search_projection(
            database, receipt, tmp_path / "drift.ndjson", work_dir=work
        )


def test_serializer_refuses_existing_or_replaced_output(tmp_path: Path) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "projection.ndjson"
    output.write_bytes(b"preserve")

    with pytest.raises(projection.SearchProjectionError, match="overwrite"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert output.read_bytes() == b"preserve"


def test_geometry_and_wal_sources_fail_closed(tmp_path: Path) -> None:
    database, receipt, work = _fixture(tmp_path)
    candidate = source_stage._strict_json(receipt.read_bytes(), "receipt")["candidate"]
    geometry = copy.deepcopy(candidate["geometry"])
    geometry["geometries"][0]["predicate"] = "unsupported"
    with pytest.raises(projection.SearchProjectionError, match="geometry"):
        projection._geometry(geometry)
    (tmp_path / "spatial.duckdb.wal").write_bytes(b"unexpected")
    with pytest.raises(projection.SearchProjectionError, match="WAL"):
        projection.serialize_search_projection(
            database, receipt, tmp_path / "wal.ndjson", work_dir=work
        )


def test_serializer_does_not_leave_partial_output_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    monkeypatch.setattr(projection, "_write", lambda *_: (_ for _ in ()).throw(OSError("stop")))
    output = tmp_path / "failed.ndjson"
    with pytest.raises(projection.SearchProjectionError, match="stop"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists() and not list(tmp_path.glob(".spatial-assets-*"))


@pytest.mark.parametrize("line_kind", ["header", "document", "footer"])
def test_serializer_enforces_the_validator_limit_on_every_line_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line_kind: str
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "oversized.ndjson"
    checked_line = projection._projection_line

    def force_target_oversized(value, label):  # type: ignore[no-untyped-def]
        if label == f"search projection {line_kind}":
            value = {**value, "oversized": "x" * 1_024}
        return checked_line(value, label)

    monkeypatch.setattr(projection, "MAX_LINE_BYTES", 900)
    monkeypatch.setattr(projection, "_projection_line", force_target_oversized)

    with pytest.raises(projection.SearchProjectionError, match="canonical line limit"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists()


def test_serializer_never_publishes_a_replaced_staged_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "replaced-stage.ndjson"
    original = projection.authority._open_asset

    @contextmanager
    def replace_before_open(root, relative: PurePosixPath, label: str) -> Iterator[object]:
        if label == "staged search projection":
            os.unlink(relative.name, dir_fd=root.descriptor)
            descriptor = os.open(
                relative.name,
                projection.authority._CREATE_FLAGS,
                0o600,
                dir_fd=root.descriptor,
            )
            os.write(descriptor, b"foreign\n")
            os.close(descriptor)
        with original(root, relative, label) as asset:
            yield asset

    monkeypatch.setattr(projection.authority, "_open_asset", replace_before_open)
    with pytest.raises(projection.SearchProjectionError, match="staged.*replaced"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists()


def test_destination_replacement_during_cleanup_fails_and_preserves_foreign_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "racing-output.ndjson"
    cleanup = projection.authority._remove_private

    def replace_after_cleanup(*args: object) -> None:
        cleanup(*args)
        if args[0].label == "search projection output directory":
            output.unlink()
            output.write_bytes(b"foreign destination\n")

    monkeypatch.setattr(projection.authority, "_remove_private", replace_after_cleanup)
    with pytest.raises(projection.SearchProjectionError, match="identity changed"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert output.read_bytes() == b"foreign destination\n"


def test_private_cleanup_completes_then_raises_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "cleanup-failed.ndjson"
    cleanup = projection.authority._remove_private

    def fail_after_cleanup(*args: object) -> None:
        cleanup(*args)
        if args[0].label == "search projection output directory":
            raise OSError("private cleanup stopped")

    monkeypatch.setattr(projection.authority, "_remove_private", fail_after_cleanup)
    with pytest.raises(projection.SearchProjectionError, match="private cleanup stopped"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists()


def test_post_promotion_fsync_failure_rolls_back_owned_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output, fsync, calls = tmp_path / "fsync-failed.ndjson", projection.os.fsync, 0

    def fail_third_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("post-promotion fsync stopped")
        fsync(descriptor)

    monkeypatch.setattr(projection.os, "fsync", fail_third_fsync)
    with pytest.raises(projection.SearchProjectionError, match="post-promotion fsync"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists()


def test_late_source_cleanup_failure_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "late-source.ndjson"
    snapshots = projection._snapshots

    @contextmanager
    def fail_after_source_cleanup(*args, **kwargs):  # type: ignore[no-untyped-def]
        with snapshots(*args, **kwargs) as value:
            yield value
        raise OSError("late source cleanup stopped")

    monkeypatch.setattr(projection, "_snapshots", fail_after_source_cleanup)
    with pytest.raises(projection.SearchProjectionError, match="late source cleanup"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists() and not list(tmp_path.glob(".spatial-assets-*"))


def test_no_spill_policy_exit_failure_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work = _fixture(tmp_path)
    output = tmp_path / "spill-policy-exit.ndjson"
    check, calls = projection._assert_no_spill, 0

    def fail_second_check(connection):  # type: ignore[no-untyped-def]
        nonlocal calls
        check(connection)
        calls += 1
        if calls == 2:
            raise OSError("spill policy exit stopped")

    monkeypatch.setattr(projection, "_assert_no_spill", fail_second_check)
    with pytest.raises(projection.SearchProjectionError, match="spill policy exit"):
        projection.serialize_search_projection(database, receipt, output, work_dir=work)
    assert not output.exists()


def test_duckdb_forced_spill_fails_closed_without_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with duckdb.connect(":memory:") as connection:
        projection._configure_connection(connection)
        assert connection.execute("SELECT current_setting('temp_directory')").fetchone() == ("",)
        connection.execute("SET memory_limit='1MB'")
        with pytest.raises(duckdb.OutOfMemoryException):
            connection.execute(
                "SELECT count(*) FROM (SELECT * FROM range(1000000) ORDER BY hash(range))"
            ).fetchone()

    assert not list(tmp_path.iterdir())
