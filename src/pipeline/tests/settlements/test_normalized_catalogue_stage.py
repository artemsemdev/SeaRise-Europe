"""Streaming normalized-catalogue candidate behavior."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import pytest

import searise_pipeline.settlements.full_source_stage as source_stage
import searise_pipeline.settlements.normalized_catalogue_stage as catalogue_stage
from searise_pipeline.settlements.alternate_names import (
    language_codes,
    parse_alternate_name_row,
    parse_iso_language_row,
)
from searise_pipeline.settlements.catalogue import normalize_catalogue_record
from searise_pipeline.settlements.full_source_catalogue import (
    ISO_LANGUAGE_HEADER,
    PRODUCTION_CONTRACT,
    FullSourceStageContract,
    LockedAsset,
    LockedMember,
)
from searise_pipeline.settlements.geonames import parse_admin1_row, parse_geoname_row
from searise_pipeline.settlements.normalized_catalogue_stage import (
    CatalogueStageError,
    build_normalized_catalogue_stage,
    canonical_catalogue_receipt_bytes,
    materialize_catalogue_candidate,
    validate_catalogue_candidate,
    validate_normalized_catalogue_stage,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_CATALOGUE_CLI_SPEC = importlib.util.spec_from_file_location(
    "searise_build_settlement_catalogue",
    REPOSITORY_ROOT / "scripts/release/build_settlement_catalogue.py",
)
assert _CATALOGUE_CLI_SPEC is not None and _CATALOGUE_CLI_SPEC.loader is not None
catalogue_cli = importlib.util.module_from_spec(_CATALOGUE_CLI_SPEC)
_CATALOGUE_CLI_SPEC.loader.exec_module(catalogue_cli)
FIXTURES = Path(__file__).with_name("fixtures") / "geonames"
HEX = "a" * 64


@dataclass(frozen=True)
class _DecodeChild:
    value: str


@dataclass(frozen=True)
class _DecodeFirst:
    child: _DecodeChild


@dataclass(frozen=True)
class _DecodeSecond:
    child: _DecodeChild


def _line(path: str, prefix: bytes | None = None) -> bytes:
    rows = (FIXTURES / path).read_bytes().splitlines()
    return rows[0] if prefix is None else next(row for row in rows if row.startswith(prefix))


def _work(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}-work"
    path.mkdir(exist_ok=True)
    return path


def test_document_decode_caches_nested_dataclass_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    original = catalogue_stage.get_type_hints
    resolved: list[type[object]] = []

    def count(annotation: type[object]) -> dict[str, object]:
        resolved.append(annotation)
        return original(annotation)

    catalogue_stage._dataclass_metadata.cache_clear()
    monkeypatch.setattr(catalogue_stage, "get_type_hints", count)
    raw = '{"child":{"value":"cached"}}'

    assert catalogue_stage._document(_DecodeFirst, raw, "first") == _DecodeFirst(
        _DecodeChild("cached")
    )
    assert catalogue_stage._document(_DecodeFirst, raw, "first") == _DecodeFirst(
        _DecodeChild("cached")
    )
    assert resolved == [_DecodeFirst, _DecodeChild]


def test_document_decode_cache_isolated_by_dataclass_type(monkeypatch: pytest.MonkeyPatch) -> None:
    original = catalogue_stage.get_type_hints
    resolved: list[type[object]] = []

    def count(annotation: type[object]) -> dict[str, object]:
        resolved.append(annotation)
        return original(annotation)

    catalogue_stage._dataclass_metadata.cache_clear()
    monkeypatch.setattr(catalogue_stage, "get_type_hints", count)
    raw = '{"child":{"value":"isolated"}}'

    assert type(catalogue_stage._document(_DecodeFirst, raw, "first")) is _DecodeFirst
    assert type(catalogue_stage._document(_DecodeSecond, raw, "second")) is _DecodeSecond
    assert resolved == [_DecodeFirst, _DecodeChild, _DecodeSecond]


def _contract(
    place_count: int, alternate_count: int, language_count: int
) -> FullSourceStageContract:
    def member(path: str, rows: int, header: bytes | None = None) -> LockedMember:
        return LockedMember(path, HEX, 1, 1, "00000000", rows, header)

    alternate_members = {
        "alternateNamesV2.txt": member("alternateNamesV2.txt", alternate_count),
        "iso-languagecodes.txt": member(
            "iso-languagecodes.txt", language_count, ISO_LANGUAGE_HEADER
        ),
    }
    return FullSourceStageContract(
        HEX,
        HEX,
        HEX,
        LockedAsset(HEX, 1, (member("allCountries.txt", place_count),)),
        LockedAsset(
            HEX,
            1,
            tuple(
                alternate_members[item.path] for item in PRODUCTION_CONTRACT.alternate_names.members
            ),
        ),
        LockedAsset(HEX, 1, row_count=1),
        LockedAsset(HEX, 1),
        minimum_free_bytes=0,
    )


def _source(
    tmp_path: Path, name: str, *, reverse: bool = False
) -> tuple[Path, FullSourceStageContract, dict[str, object]]:
    places = [
        parse_geoname_row(_line("allCountries.rows.txt", b"1134032\t"), source_line=1),
        parse_geoname_row(_line("allCountries.rows.txt", b"3038987\t"), source_line=2),
        parse_geoname_row(_line("catalogue-allCountries.rows.txt"), source_line=3),
    ]
    alternates = [
        replace(
            parse_alternate_name_row(
                _line("alternateNamesV2.rows.txt", b"1297839\t"), source_line=1
            ),
            geoname_id=3038987,
        ),
        parse_alternate_name_row(_line("alternateNamesV2.rows.txt", b"1567725\t"), source_line=2),
        parse_alternate_name_row(_line("alternateNamesV2.rows.txt", b"2039069\t"), source_line=3),
    ]
    languages = [
        parse_iso_language_row(row, source_line=index)
        for index, row in enumerate(
            (FIXTURES / "iso-languagecodes.rows.txt").read_bytes().splitlines(), 2
        )
    ]
    admin = parse_admin1_row(_line("catalogue-admin1CodesASCII.rows.txt"), source_line=1)
    contract = _contract(len(places), len(alternates), len(languages))
    database = tmp_path / f"{name}.duckdb"
    with duckdb.connect(str(database)) as connection:
        source_stage._create_schema(connection)
        rows = {
            "stage_places": [
                (item.geoname_id, item.lineage.source_line, source_stage._canonical_json(item))
                for item in places
            ],
            "stage_admin1": [
                (
                    admin.key,
                    admin.geoname_id,
                    admin.lineage.source_line,
                    source_stage._canonical_json(admin),
                )
            ],
            "stage_languages": [
                (
                    item.iso639_3 or item.iso639_2[0] or item.iso639_1,
                    item.source_line,
                    source_stage._canonical_json(item),
                )
                for item in languages
            ],
            "stage_alternates": [
                (
                    item.alternate_name_id,
                    item.geoname_id,
                    item.lineage.source_line,
                    source_stage._canonical_json(item),
                )
                for item in alternates
            ],
        }
        for table, values in rows.items():
            if reverse:
                values.reverse()
            placeholders = ",".join("?" for _ in values[0])
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", values)
        receipt = source_stage._receipt(connection, contract)
    return (
        database,
        contract,
        {
            "receipt": receipt,
            "places": places,
            "alternates": alternates,
            "languages": languages,
            "admin": admin,
        },
    )


def _materialize(
    tmp_path: Path,
    name: str,
    source: tuple[Path, FullSourceStageContract, dict[str, object]],
    batch_size: int,
) -> tuple[Path, dict[str, object]]:
    output = tmp_path / f"{name}-catalogue.duckdb"
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output)) as candidate:
            identity = materialize_catalogue_candidate(
                opened_source,
                candidate,
                source[2]["receipt"],  # type: ignore[arg-type]
                work_dir=_work(tmp_path, name),
                contract=source[1],
                batch_size=batch_size,
            )
    return output, identity


def test_candidate_matches_domain_and_is_order_batch_invariant(tmp_path: Path) -> None:
    source_a = _source(tmp_path, "source-a")
    source_b = _source(tmp_path, "source-b", reverse=True)
    first = _materialize(tmp_path, "first", source_a, 1)
    second = _materialize(tmp_path, "second", source_b, 3)
    assert first[1] == second[1]
    assert first[1]["publicationClaim"] is False
    counts = first[1]["counts"]
    assert (
        counts["sourcePlaceRows"] == counts["normalizedPlaces"] + counts["catalogueRejections"] == 3
    )

    values = source_a[2]
    admins = {values["admin"].key: values["admin"]}  # type: ignore[union-attr]
    codes = language_codes(values["languages"])  # type: ignore[arg-type]
    by_place = {}
    for alternate in values["alternates"]:  # type: ignore[union-attr]
        by_place.setdefault(alternate.geoname_id, []).append(alternate)
    expected = [
        normalize_catalogue_record(
            place,
            admins_by_key=admins,
            alternate_records=by_place.get(place.geoname_id, ()),
            known_language_codes=codes,
        )
        for place in values["places"]  # type: ignore[union-attr]
    ]
    with duckdb.connect(str(first[0]), read_only=True) as connection:
        actual = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT document FROM catalogue_places ORDER BY geoname_id"
            ).fetchall()
        ]
    assert actual == [source_stage._json_value(item.place) for item in expected if item.place]


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("catalogue_places", "ascii_name"),
        ("catalogue_rejections", "observed_value"),
        ("catalogue_context_notices", "observed_value"),
    ],
)
def test_candidate_validator_replays_every_normalized_document(
    tmp_path: Path, target: str, field: str
) -> None:
    source = _source(tmp_path, "source")
    output, _ = _materialize(tmp_path, "output", source, 2)
    with duckdb.connect(str(output)) as connection:
        geoname_id, raw = connection.execute(
            f"SELECT geoname_id, document FROM {target} ORDER BY geoname_id LIMIT 1"
        ).fetchone()
        document = json.loads(raw)
        document[field] = "fabricated-but-type-valid"
        connection.execute(
            f"UPDATE {target} SET document=? WHERE geoname_id=?",
            [source_stage._canonical_json(document), geoname_id],
        )
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output), read_only=True) as candidate:
            with pytest.raises(CatalogueStageError, match="exact normalization replay"):
                validate_catalogue_candidate(
                    opened_source,
                    candidate,
                    source[2]["receipt"],  # type: ignore[arg-type]
                    work_dir=_work(tmp_path, f"validate-{target}"),
                    contract=source[1],
                    batch_size=1,
                )


@pytest.mark.parametrize(
    "table",
    ["catalogue_context_notice_counts", "catalogue_name_rejection_counts"],
)
def test_candidate_validator_reconciles_both_aggregate_count_tables(
    tmp_path: Path, table: str
) -> None:
    source = _source(tmp_path, "source")
    output, _ = _materialize(tmp_path, "output", source, 2)
    with duckdb.connect(str(output)) as connection:
        connection.execute(f"UPDATE {table} SET count=count+1")
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output), read_only=True) as candidate:
            with pytest.raises(CatalogueStageError, match=table):
                validate_catalogue_candidate(
                    opened_source,
                    candidate,
                    source[2]["receipt"],  # type: ignore[arg-type]
                    work_dir=_work(tmp_path, f"validate-{table}"),
                    contract=source[1],
                    batch_size=1,
                )


def test_core_pins_all_cursor_resources_to_caller_work_area(tmp_path: Path) -> None:
    source = _source(tmp_path, "source")
    output = tmp_path / "candidate.duckdb"
    work = _work(tmp_path, "bounded")
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output)) as candidate:
            materialize_catalogue_candidate(
                opened_source,
                candidate,
                source[2]["receipt"],  # type: ignore[arg-type]
                work_dir=work,
                contract=source[1],
                batch_size=1,
            )
            expected = (
                1,
                "1.0 GiB",
                str((work / "duckdb-candidate-spill").resolve()),
            )
            assert (
                candidate.execute(
                    "SELECT current_setting('threads'), current_setting('memory_limit'), "
                    "current_setting('temp_directory')"
                ).fetchone()
                == expected
            )
        expected = (1, "1.0 GiB", str((work / "duckdb-source-spill").resolve()))
        assert (
            opened_source.cursor()
            .execute(
                "SELECT current_setting('threads'), current_setting('memory_limit'), "
                "current_setting('temp_directory')"
            )
            .fetchone()
            == expected
        )


def test_alternate_group_memory_bound_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path, "source")
    output = tmp_path / "candidate.duckdb"
    monkeypatch.setattr(catalogue_stage, "MAX_ALTERNATE_ROWS_PER_PLACE", 1)
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output)) as candidate:
            with pytest.raises(CatalogueStageError, match="1-row memory bound"):
                materialize_catalogue_candidate(
                    opened_source,
                    candidate,
                    source[2]["receipt"],  # type: ignore[arg-type]
                    work_dir=_work(tmp_path, "bounded"),
                    contract=source[1],
                    batch_size=1,
                )


def test_candidate_validator_rejects_source_receipt_and_output_drift(tmp_path: Path) -> None:
    source = _source(tmp_path, "source")
    output, _ = _materialize(tmp_path, "output", source, 2)
    changed = copy.deepcopy(source[2]["receipt"])
    changed["logicalHashes"]["placeRows"] = "0" * 64
    work = _work(tmp_path, "validate")
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output), read_only=True) as candidate:
            with pytest.raises(CatalogueStageError, match="source"):
                validate_catalogue_candidate(
                    opened_source,
                    candidate,
                    changed,
                    work_dir=work,
                    contract=source[1],
                )
    with duckdb.connect(str(output)) as connection:
        connection.execute("DELETE FROM catalogue_places WHERE geoname_id=3128760")
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output), read_only=True) as candidate:
            with pytest.raises(CatalogueStageError, match="count|partition"):
                validate_catalogue_candidate(
                    opened_source,
                    candidate,
                    source[2]["receipt"],  # type: ignore[arg-type]
                    work_dir=work,
                    contract=source[1],
                )
    with duckdb.connect(str(output)) as connection:
        connection.execute("ALTER TABLE catalogue_places ADD COLUMN drift INTEGER")
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output), read_only=True) as candidate:
            with pytest.raises(CatalogueStageError, match="schema"):
                validate_catalogue_candidate(
                    opened_source,
                    candidate,
                    source[2]["receipt"],  # type: ignore[arg-type]
                    work_dir=work,
                    contract=source[1],
                )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO stage_places SELECT * FROM stage_places LIMIT 1",
        "INSERT INTO stage_alternates SELECT * FROM stage_alternates LIMIT 1",
        "DELETE FROM stage_places WHERE geoname_id=3038987",
    ],
)
def test_source_missing_orphan_and_duplicates_fail_before_materialization(
    tmp_path: Path, sql: str
) -> None:
    source = _source(tmp_path, "source")
    with duckdb.connect(str(source[0])) as connection:
        connection.execute(sql)
    output = tmp_path / "candidate.duckdb"
    with duckdb.connect(str(source[0]), read_only=True) as opened_source:
        with duckdb.connect(str(output)) as candidate:
            with pytest.raises(CatalogueStageError, match="source|duplicate|orphan"):
                materialize_catalogue_candidate(
                    opened_source,
                    candidate,
                    source[2]["receipt"],  # type: ignore[arg-type]
                    work_dir=_work(tmp_path, "failed-materialization"),
                    contract=source[1],
                )


def _published_candidate(
    tmp_path: Path,
) -> tuple[
    tuple[Path, FullSourceStageContract, dict[str, object]],
    Path,
    Path,
    Path,
    dict[str, object],
]:
    source = _source(tmp_path, "published-source")
    database, identity = _materialize(tmp_path, "published", source, 2)
    source_receipt = tmp_path / "source.receipt.json"
    source_receipt.write_bytes(
        source_stage.canonical_stage_receipt_bytes(source[2]["receipt"])  # type: ignore[arg-type]
    )
    payload = catalogue_stage._receipt_payload(identity)
    document = {
        **payload,
        "deterministicIdentity": catalogue_stage._receipt_identity(payload),
        "observations": {
            "completedAtUtc": "2026-08-11T12:34:56Z",
            "buildDurationSeconds": 1.25,
            "peakRssBytes": 1024,
            "deterministicIdentityExcluded": True,
        },
    }
    receipt = tmp_path / "catalogue.receipt.json"
    receipt.write_bytes(canonical_catalogue_receipt_bytes(document))
    return source, source_receipt, database, receipt, document


def test_public_validator_binds_canonical_receipt_and_private_database_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, source_receipt, database, receipt, document = _published_candidate(tmp_path)
    work = _work(tmp_path, "public-validation")
    real_duckdb, pa = source_stage._load_tools()
    opened_paths: list[Path] = []

    class DuckDbProxy:
        @staticmethod
        def connect(path: str, **kwargs: object) -> object:
            opened_paths.append(Path(path))
            return real_duckdb.connect(path, **kwargs)

    monkeypatch.setattr(source_stage, "_load_tools", lambda: (DuckDbProxy, pa))
    validate_normalized_catalogue_stage(
        database,
        receipt,
        source[0],
        source_receipt,
        work_dir=work,
        contract=source[1],
        batch_size=1,
    )
    assert len(opened_paths) == 2
    assert all(path.parent.parent == work for path in opened_paths)
    assert all(path.parent.name.startswith(".catalogue-validate-") for path in opened_paths)
    assert receipt.read_bytes() == canonical_catalogue_receipt_bytes(document)
    assert not list(work.glob(".catalogue-validate-*"))


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-11T12:34:56+00:00",
        "2026-08-11T12:34:56.000Z",
        "2026-08-11T12:34:56z",
        "2026-8-11T12:34:56Z",
        "2026-02-30T12:34:56Z",
    ],
)
def test_receipt_observations_require_exact_utc_seconds(timestamp: str) -> None:
    with pytest.raises(CatalogueStageError, match="timestamp|observations"):
        catalogue_stage._validate_observations(
            {
                "completedAtUtc": timestamp,
                "buildDurationSeconds": 0.0,
                "peakRssBytes": 1,
                "deterministicIdentityExcluded": True,
            }
        )


def test_same_size_receipt_mutation_during_validation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, source_receipt, database, receipt, _ = _published_candidate(tmp_path)
    original = catalogue_stage.validate_catalogue_candidate

    def mutate(*args: object, **kwargs: object) -> dict[str, object]:
        identity = original(*args, **kwargs)
        raw = receipt.read_bytes()
        changed = raw.replace(b'"completedAtUtc":"2', b'"completedAtUtc":"3', 1)
        assert len(changed) == len(raw) and changed != raw
        receipt.write_bytes(changed)
        return identity

    monkeypatch.setattr(catalogue_stage, "validate_catalogue_candidate", mutate)
    with pytest.raises(CatalogueStageError, match="receipt exact bytes changed"):
        validate_normalized_catalogue_stage(
            database,
            receipt,
            source[0],
            source_receipt,
            work_dir=_work(tmp_path, "mutated-validation"),
            contract=source[1],
        )


def test_private_cleanup_does_not_remove_racing_parent_entry(tmp_path: Path) -> None:
    work = _work(tmp_path, "cleanup")
    with catalogue_stage._open_directory(work, "work directory") as parent:
        name, child = catalogue_stage._create_private_directory(
            parent, ".catalogue-validate-", "validation directory"
        )
        opened_path = work / name
        moved_path = work / "opened-private-directory"
        opened_path.rename(moved_path)
        opened_path.mkdir()
        (opened_path / "replacement.txt").write_bytes(b"preserve")
        with pytest.raises(CatalogueStageError, match="replaced; cleanup refused"):
            catalogue_stage._remove_private_directory(parent, name, child)
    assert (opened_path / "replacement.txt").read_bytes() == b"preserve"
    assert list(moved_path.iterdir()) == []
    shutil.rmtree(opened_path)
    moved_path.rmdir()


def test_private_creation_failure_does_not_remove_racing_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = _work(tmp_path, "create-cleanup")
    with catalogue_stage._open_directory(work, "work directory") as parent:
        real_open = catalogue_stage.os.open
        moved_path = work / "created-private-directory"
        replacement_path: Path | None = None

        def replace_before_open(path: object, *args: object, **kwargs: object) -> int:
            nonlocal replacement_path
            if (
                type(path) is str
                and path.startswith(".catalogue-validate-")
                and kwargs.get("dir_fd") == parent.descriptor
            ):
                replacement_path = work / path
                replacement_path.rename(moved_path)
                replacement_path.mkdir()
                (replacement_path / "replacement.txt").write_bytes(b"preserve")
                raise OSError("injected private-directory open failure")
            return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(catalogue_stage.os, "open", replace_before_open)
        with pytest.raises(CatalogueStageError, match="replaced; cleanup refused"):
            catalogue_stage._create_private_directory(
                parent, ".catalogue-validate-", "validation directory"
            )
    assert replacement_path is not None
    assert (replacement_path / "replacement.txt").read_bytes() == b"preserve"
    shutil.rmtree(replacement_path)
    moved_path.rmdir()


def test_public_validation_copies_descriptor_bound_snapshots_across_filesystems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, source_receipt, database, receipt, _ = _published_candidate(tmp_path)

    def cross_device(*args: object, **kwargs: object) -> None:
        raise OSError(catalogue_stage.errno.EXDEV, "injected cross-device link")

    monkeypatch.setattr(catalogue_stage.os, "link", cross_device)
    work = _work(tmp_path, "copied-validation")
    validate_normalized_catalogue_stage(
        database,
        receipt,
        source[0],
        source_receipt,
        work_dir=work,
        contract=source[1],
    )
    assert not list(work.glob(".catalogue-validate-*"))


def test_public_validation_rejects_database_path_swap_after_snapshot_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, source_receipt, database, receipt, _ = _published_candidate(tmp_path)
    moved = tmp_path / "opened-catalogue.duckdb"
    original = catalogue_stage._private_snapshot

    @contextmanager
    def swap_after_binding(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        with original(*args, **kwargs) as snapshot:
            if kwargs.get("name") == "catalogue.duckdb" or args[-1] == "catalogue.duckdb":
                database.rename(moved)
                shutil.copyfile(moved, database)
            yield snapshot

    monkeypatch.setattr(catalogue_stage, "_private_snapshot", swap_after_binding)
    try:
        with pytest.raises(CatalogueStageError, match="path identity changed"):
            validate_normalized_catalogue_stage(
                database,
                receipt,
                source[0],
                source_receipt,
                work_dir=_work(tmp_path, "swapped-validation"),
                contract=source[1],
            )
    finally:
        database.unlink(missing_ok=True)
        moved.rename(database)


def _publication_source(
    tmp_path: Path, name: str = "source"
) -> tuple[Path, Path, FullSourceStageContract, dict[str, object]]:
    source = _source(tmp_path, name)
    receipt = tmp_path / f"{name}.receipt.json"
    receipt.write_bytes(source_stage.canonical_stage_receipt_bytes(source[2]["receipt"]))
    return source[0], receipt, source[1], source[2]


def _publish(
    tmp_path: Path,
    name: str,
    source: tuple[Path, Path, FullSourceStageContract, dict[str, object]],
    *,
    batch_size: int = 2,
) -> tuple[Path, Path, dict[str, object]]:
    work = _work(tmp_path, name)
    output = tmp_path / f"{name}.catalogue.duckdb"
    receipt = tmp_path / f"{name}.catalogue.json"
    document = build_normalized_catalogue_stage(
        source[0],
        source[1],
        output,
        receipt,
        work,
        contract=source[2],
        batch_size=batch_size,
    )
    return output, receipt, document


def test_publication_receipt_is_canonical_deterministic_and_valid(tmp_path: Path) -> None:
    source = _publication_source(tmp_path)
    first = _publish(tmp_path, "first", source, batch_size=1)
    second = _publish(tmp_path, "second", source, batch_size=3)
    assert first[2]["candidate"] == second[2]["candidate"]
    assert first[2]["deterministicIdentity"] == second[2]["deterministicIdentity"]
    assert first[1].read_bytes() == canonical_catalogue_receipt_bytes(first[2])
    validate_normalized_catalogue_stage(
        first[0],
        first[1],
        source[0],
        source[1],
        work_dir=_work(tmp_path, "published-validator"),
        contract=source[2],
    )


def test_database_is_durable_before_receipt_completion_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _publication_source(tmp_path)
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    original = catalogue_stage._fsync_directory_fd
    states: list[tuple[bool, bool]] = []

    def observe(directory: object) -> None:
        states.append((output.exists(), receipt.exists()))
        original(directory)  # type: ignore[arg-type]

    monkeypatch.setattr(catalogue_stage, "_fsync_directory_fd", observe)
    build_normalized_catalogue_stage(
        source[0], source[1], output, receipt, _work(tmp_path, "order"), contract=source[2]
    )
    assert states == [(True, False), (True, True)]


def test_publication_refuses_overwrite_symlinks_and_insufficient_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _publication_source(tmp_path)
    work = _work(tmp_path, "refuse")
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    output.write_bytes(b"preserve")
    with pytest.raises(CatalogueStageError, match="overwrite"):
        build_normalized_catalogue_stage(
            source[0], source[1], output, receipt, work, contract=source[2]
        )
    assert output.read_bytes() == b"preserve"
    output.unlink()
    linked_source = tmp_path / "linked-source.db"
    linked_source.symlink_to(source[0])
    with pytest.raises(CatalogueStageError, match="non-symlink"):
        build_normalized_catalogue_stage(
            linked_source, source[1], output, receipt, work, contract=source[2]
        )
    monkeypatch.setattr(catalogue_stage, "_free_bytes", lambda _: 0)
    with pytest.raises(CatalogueStageError, match="free space"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            work,
            contract=replace(source[2], minimum_free_bytes=1),
        )


@pytest.mark.parametrize("failure", ["receipt-link", "final-validation"])
def test_publication_failures_roll_back_owned_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    source = _publication_source(tmp_path)
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    if failure == "receipt-link":
        original, calls = catalogue_stage._link_no_overwrite, 0

        def fail_second(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected receipt promotion failure")
            original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(catalogue_stage, "_link_no_overwrite", fail_second)
    else:
        original, calls = catalogue_stage.validate_normalized_catalogue_stage, 0

        def fail_final(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise CatalogueStageError("injected final validation failure")
            original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(catalogue_stage, "validate_normalized_catalogue_stage", fail_final)
    with pytest.raises(CatalogueStageError, match="injected"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            _work(tmp_path, failure),
            contract=source[2],
        )
    assert not output.exists() and not receipt.exists()
    assert not list(tmp_path.glob(".catalogue-*"))


def test_same_size_source_receipt_mutation_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _publication_source(tmp_path)
    original = catalogue_stage.materialize_catalogue_candidate

    def mutate(*args: object, **kwargs: object) -> dict[str, object]:
        identity = original(*args, **kwargs)
        raw = source[1].read_bytes()
        marker = raw.index(b'"logicalHashes":{')
        digest = raw.index(b"a", marker)
        source[1].write_bytes(raw[:digest] + b"b" + raw[digest + 1 :])
        return identity

    monkeypatch.setattr(catalogue_stage, "materialize_catalogue_candidate", mutate)
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    with pytest.raises(CatalogueStageError, match="receipt exact bytes changed"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            _work(tmp_path, "source-mutation"),
            contract=source[2],
        )
    assert not output.exists() and not receipt.exists()


def test_same_size_output_receipt_mutation_rolls_back_both_owned_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _publication_source(tmp_path)
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    original, calls = catalogue_stage._fsync_directory_fd, 0

    def mutate_after_receipt_link(directory: object) -> None:
        nonlocal calls
        original(directory)  # type: ignore[arg-type]
        calls += 1
        if calls == 2:
            raw = receipt.read_bytes()
            changed = raw.replace(b'"completedAtUtc":"2', b'"completedAtUtc":"3', 1)
            assert len(changed) == len(raw) and changed != raw
            receipt.write_bytes(changed)

    monkeypatch.setattr(catalogue_stage, "_fsync_directory_fd", mutate_after_receipt_link)
    with pytest.raises(CatalogueStageError, match="receipt exact bytes changed"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            _work(tmp_path, "receipt-mutation"),
            contract=source[2],
        )
    assert not output.exists() and not receipt.exists()


def test_output_parent_swap_rolls_back_through_held_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _publication_source(tmp_path)
    output_parent = tmp_path / "publish"
    output_parent.mkdir()
    moved_parent = tmp_path / "publish-opened"
    output = output_parent / "output.db"
    receipt = output_parent / "output.json"
    original, calls = catalogue_stage._link_no_overwrite, 0

    def swap_after_database(*args: object, **kwargs: object) -> None:
        nonlocal calls
        original(*args, **kwargs)  # type: ignore[arg-type]
        calls += 1
        if calls == 1:
            output_parent.rename(moved_parent)
            output_parent.mkdir()
            (output_parent / "replacement.txt").write_bytes(b"preserve")

    monkeypatch.setattr(catalogue_stage, "_link_no_overwrite", swap_after_database)
    with pytest.raises(CatalogueStageError, match="directory path identity changed"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            _work(tmp_path, "parent-swap"),
            contract=source[2],
        )
    assert (output_parent / "replacement.txt").read_bytes() == b"preserve"
    assert not (moved_parent / output.name).exists()
    assert not (moved_parent / receipt.name).exists()
    assert not list(moved_parent.glob(".catalogue-*"))


@pytest.mark.parametrize("target", ["database", "receipt"])
def test_rollback_preserves_racing_replacement_and_removes_owned_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    source = _publication_source(tmp_path)
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    racer = output if target == "database" else receipt
    original, calls = catalogue_stage._fsync_directory_fd, 0
    racer_identity: tuple[int, int] | None = None

    def replace_after_fsync(directory: object) -> None:
        nonlocal calls, racer_identity
        original(directory)  # type: ignore[arg-type]
        calls += 1
        trigger = calls == (1 if target == "database" else 2)
        if trigger:
            racer.unlink()
            racer.write_bytes(f"racing {target}".encode())
            metadata = racer.stat()
            racer_identity = metadata.st_dev, metadata.st_ino

    monkeypatch.setattr(catalogue_stage, "_fsync_directory_fd", replace_after_fsync)
    with pytest.raises(CatalogueStageError, match="entry identity changed"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            _work(tmp_path, f"racing-{target}"),
            contract=source[2],
        )
    metadata = racer.stat()
    assert racer.read_bytes() == f"racing {target}".encode()
    assert (metadata.st_dev, metadata.st_ino) == racer_identity
    if target == "receipt":
        assert not output.exists()
    else:
        assert not receipt.exists()
    assert not list(tmp_path.glob(".catalogue-*"))


def test_database_rollback_is_attempted_when_receipt_rollback_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _publication_source(tmp_path)
    output, receipt = tmp_path / "output.db", tmp_path / "output.json"
    original_validate, validation_calls = (
        catalogue_stage.validate_normalized_catalogue_stage,
        0,
    )

    def fail_final_validation(*args: object, **kwargs: object) -> None:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 3:
            raise CatalogueStageError("injected final validation failure")
        original_validate(*args, **kwargs)  # type: ignore[arg-type]

    original_rollback = catalogue_stage._rollback_owned_entry
    attempted: list[str] = []

    def fail_receipt_rollback(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        name = args[1]
        attempted.append(name)
        if name == receipt.name:
            raise OSError("injected receipt rollback failure")
        return original_rollback(*args, **kwargs)

    monkeypatch.setattr(
        catalogue_stage, "validate_normalized_catalogue_stage", fail_final_validation
    )
    monkeypatch.setattr(catalogue_stage, "_rollback_owned_entry", fail_receipt_rollback)
    with pytest.raises(CatalogueStageError, match="rollback was incomplete"):
        build_normalized_catalogue_stage(
            source[0],
            source[1],
            output,
            receipt,
            _work(tmp_path, "rollback-error"),
            contract=source[2],
        )
    assert attempted == [receipt.name, output.name]
    assert not output.exists()


def test_cli_requires_and_forwards_all_explicit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = ()

    def fake(*args: object, **kwargs: object) -> dict[str, str]:
        nonlocal captured
        captured = args
        return {"deterministicIdentity": "d" * 64}

    monkeypatch.setattr(catalogue_cli, "build_normalized_catalogue_stage", fake)
    paths = [tmp_path / name for name in ("source.db", "source.json", "out.db", "out.json", "work")]
    arguments = [
        "--source-stage-db",
        str(paths[0]),
        "--source-stage-receipt",
        str(paths[1]),
        "--output-db",
        str(paths[2]),
        "--output-receipt",
        str(paths[3]),
        "--work-dir",
        str(paths[4]),
    ]
    assert catalogue_cli.main(arguments) == 0
    assert captured == tuple(paths)
    assert capsys.readouterr().out.strip() == "d" * 64
