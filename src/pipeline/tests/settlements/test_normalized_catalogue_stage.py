"""Streaming normalized-catalogue candidate behavior."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
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
    materialize_catalogue_candidate,
    validate_catalogue_candidate,
)

FIXTURES = Path(__file__).with_name("fixtures") / "geonames"
HEX = "a" * 64


def _line(path: str, prefix: bytes | None = None) -> bytes:
    rows = (FIXTURES / path).read_bytes().splitlines()
    return rows[0] if prefix is None else next(row for row in rows if row.startswith(prefix))


def _work(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}-work"
    path.mkdir(exist_ok=True)
    return path


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
