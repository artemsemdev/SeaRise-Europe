"""Behavior coverage for the streaming, verified full-source stage."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator

import duckdb
import pytest

import searise_pipeline.settlements.full_source_stage as stage
from searise_pipeline.settlements.full_source_catalogue import (
    ISO_LANGUAGE_HEADER,
    FullSourceStageContract,
    FullSourceStageInputs,
    LockedAsset,
    LockedMember,
)
from searise_pipeline.settlements.full_source_stage import (
    FullSourceStageError,
    build_full_source_stage,
    canonical_stage_receipt_bytes,
    validate_full_source_stage,
)

ROOT = Path(__file__).parents[4]
FIXTURES = Path(__file__).with_name("fixtures") / "geonames"
SOURCE_LOCK = ROOT / "src/pipeline/sources/source-lock.phase-1-settlements.json"
CATALOGUE_POLICY = ROOT / "src/pipeline/settlements/catalogue-policy-v1.json"
NORMALIZATION_POLICY = ROOT / "src/pipeline/settlements/normalization-policy-v2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zip_asset(path: Path, rows: dict[str, int]) -> LockedAsset:
    with zipfile.ZipFile(path) as archive:
        members = tuple(
            LockedMember(
                info.filename,
                hashlib.sha256(archive.read(info)).hexdigest(),
                info.file_size,
                info.compress_size,
                f"{info.CRC:08x}",
                rows[info.filename],
                ISO_LANGUAGE_HEADER if info.filename == "iso-languagecodes.txt" else None,
            )
            for info in archive.infolist()
        )
    return LockedAsset(_sha(path), path.stat().st_size, members)


def _row(path: Path, prefix: bytes) -> bytes:
    return next(item for item in path.read_bytes().splitlines() if item.startswith(prefix))


def _fixture(
    tmp_path: Path,
    *,
    duplicate_place: bool = False,
    duplicate_alternate: bool = False,
    duplicate_admin: bool = False,
    orphan_alternate: bool = False,
    invalid_place: bool = False,
) -> tuple[FullSourceStageInputs, FullSourceStageContract]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    place_rows = [
        (FIXTURES / "catalogue-allCountries.rows.txt").read_bytes().rstrip(b"\n"),
        _row(FIXTURES / "allCountries.rows.txt", b"1134032\t"),
    ]
    if duplicate_place:
        place_rows.append(place_rows[0])
    if invalid_place:
        place_rows[0] = b"invalid"
    all_countries = tmp_path / "allCountries.zip"
    with zipfile.ZipFile(all_countries, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("allCountries.txt", b"\n".join(place_rows) + b"\n")

    alternate_rows = [
        item
        for item in (FIXTURES / "alternateNamesV2.rows.txt").read_bytes().splitlines()
        if item.split(b"\t", 2)[1] == b"3128760"
    ]
    rejected_columns = _row(FIXTURES / "alternateNamesV2.rows.txt", b"2170607\t").split(b"\t")
    rejected_columns[1] = b"1134032"
    alternate_rows.append(b"\t".join(rejected_columns))
    if orphan_alternate:
        columns = alternate_rows[0].split(b"\t")
        columns[1] = b"1"
        alternate_rows[0] = b"\t".join(columns)
    if duplicate_alternate:
        alternate_rows.append(alternate_rows[0])
    language_rows = (FIXTURES / "iso-languagecodes.rows.txt").read_bytes().splitlines()
    alternate_names = tmp_path / "alternateNamesV2.zip"
    with zipfile.ZipFile(alternate_names, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "iso-languagecodes.txt",
            ISO_LANGUAGE_HEADER + b"\r\n" + b"\n".join(language_rows) + b"\n",
        )
        archive.writestr("alternateNamesV2.txt", b"\n".join(alternate_rows) + b"\n")

    admin = tmp_path / "admin1CodesASCII.txt"
    admin_rows = (FIXTURES / "catalogue-admin1CodesASCII.rows.txt").read_bytes()
    if duplicate_admin:
        admin_rows += admin_rows
    admin.write_bytes(admin_rows)
    readme = tmp_path / "readme.txt"
    readme.write_bytes(b"GeoNames fixture readme\n")
    source_lock = tmp_path / "source-lock.json"
    catalogue_policy = tmp_path / "catalogue-policy.json"
    normalization_policy = tmp_path / "normalization-policy.json"
    shutil.copyfile(SOURCE_LOCK, source_lock)
    shutil.copyfile(CATALOGUE_POLICY, catalogue_policy)
    shutil.copyfile(NORMALIZATION_POLICY, normalization_policy)

    contract = FullSourceStageContract(
        _sha(source_lock),
        _sha(catalogue_policy),
        _sha(normalization_policy),
        _zip_asset(all_countries, {"allCountries.txt": len(place_rows)}),
        _zip_asset(
            alternate_names,
            {
                "alternateNamesV2.txt": len(alternate_rows),
                "iso-languagecodes.txt": len(language_rows),
            },
        ),
        LockedAsset(_sha(admin), admin.stat().st_size, row_count=2 if duplicate_admin else 1),
        LockedAsset(_sha(readme), readme.stat().st_size),
        minimum_free_bytes=0,
    )
    return (
        FullSourceStageInputs(
            all_countries,
            alternate_names,
            admin,
            readme,
            source_lock,
            catalogue_policy,
            normalization_policy,
        ),
        contract,
    )


def _build(
    tmp_path: Path,
    inputs: FullSourceStageInputs,
    contract: FullSourceStageContract,
    name: str,
    **kwargs: object,
) -> tuple[Path, Path, dict[str, object]]:
    work = tmp_path / f"{name}-work"
    work.mkdir()
    output = tmp_path / f"{name}.duckdb"
    receipt = tmp_path / f"{name}.receipt.json"
    document = build_full_source_stage(inputs, output, receipt, work, contract=contract, **kwargs)
    return output, receipt, document


def test_stage_is_ordered_and_deterministic_across_batching(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    first = _build(tmp_path, inputs, contract, "first", batch_size=1)
    second = _build(
        tmp_path,
        inputs,
        contract,
        "second",
        batch_size=3,
        source_order=("alternate_names", "admin1", "places"),
    )
    assert first[2] == second[2]
    assert canonical_stage_receipt_bytes(first[2]) == first[1].read_bytes()
    assert first[2]["stagingPerformed"] is True
    assert first[2]["publicationClaim"] is False
    assert "claimBoundary" not in first[2]["sourceBindings"]
    assert first[2]["counts"] == {
        "admin1Rows": 1,
        "alternateNameRows": 4,
        "languageRows": 8,
        "placeRows": 2,
    }
    assert set(first[2]["logicalHashes"]) == set(first[2]["counts"])
    validate_full_source_stage(first[0], first[1], contract=contract)
    with duckdb.connect(str(first[0]), read_only=True) as connection:
        places = connection.execute(
            "SELECT geoname_id FROM stage_places ORDER BY geoname_id"
        ).fetchall()
        alternates = connection.execute(
            "SELECT alternate_name_id FROM stage_alternates ORDER BY alternate_name_id"
        ).fetchall()
    assert [row[0] for row in places] == [1134032, 3128760]
    assert [row[0] for row in alternates] == sorted([1567725, 1567726, 2039069, 2170607])
    database_only = tmp_path / "database-only.duckdb"
    receipt_only = tmp_path / "receipt-only.json"
    shutil.copyfile(first[0], database_only)
    shutil.copyfile(first[1], receipt_only)
    with pytest.raises(FullSourceStageError, match="stage receipt"):
        validate_full_source_stage(
            database_only, tmp_path / "missing-receipt.json", contract=contract
        )
    with pytest.raises(FullSourceStageError, match="stage database"):
        validate_full_source_stage(tmp_path / "missing.duckdb", receipt_only, contract=contract)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_place", "duplicate GeoNames place id 3128760"),
        ("duplicate_alternate", "duplicate alternateNameId 1567725"),
        ("duplicate_admin", "duplicate admin1 key ES.56"),
        ("orphan_alternate", "orphan alternate place id 1"),
    ],
)
def test_duplicate_and_orphan_failures_are_lowest_id_deterministic(
    tmp_path: Path, mutation: str, message: str
) -> None:
    inputs, contract = _fixture(tmp_path, **{mutation: True})
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "stage.duckdb"
    receipt = tmp_path / "stage.receipt.json"
    with pytest.raises(FullSourceStageError) as error:
        build_full_source_stage(inputs, output, receipt, work, contract=contract, batch_size=2)
    assert str(error.value) == message
    assert not output.exists() and not receipt.exists()
    assert not list(tmp_path.glob(".full-source-*"))


def test_identity_parser_receipt_and_database_tampering_fail_closed(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    inputs.readme.write_bytes(b"drift\n")
    with pytest.raises(FullSourceStageError, match="readme bytes differ"):
        _build(tmp_path, inputs, contract, "identity")

    invalid_inputs, invalid_contract = _fixture(tmp_path / "invalid", invalid_place=True)
    work = tmp_path / "invalid-work"
    work.mkdir()
    with pytest.raises(FullSourceStageError, match="allCountries.txt:1"):
        build_full_source_stage(
            invalid_inputs,
            tmp_path / "invalid.duckdb",
            tmp_path / "invalid.receipt.json",
            work,
            contract=invalid_contract,
        )

    clean = tmp_path / "clean"
    clean.mkdir()
    clean_inputs, clean_contract = _fixture(clean)
    output, receipt_path, receipt = _build(clean, clean_inputs, clean_contract, "clean")
    raw = receipt_path.read_bytes()
    mutations = {
        "duplicate": b'{"counts":{},"counts":' + raw.removeprefix(b'{"counts":'),
        "nan": raw.replace(b'"schemaVersion":1', b'"schemaVersion":NaN', 1),
        "infinity": raw.replace(b'"schemaVersion":1', b'"schemaVersion":Infinity', 1),
    }
    for name, payload in mutations.items():
        changed_receipt = clean / f"{name}.json"
        changed_receipt.write_bytes(payload)
        with pytest.raises(FullSourceStageError, match="duplicate key|non-finite JSON"):
            validate_full_source_stage(output, changed_receipt, contract=clean_contract)
    with pytest.raises(FullSourceStageError, match="cannot be canonicalized"):
        canonical_stage_receipt_bytes({"invalid": object()})
    with pytest.raises(FullSourceStageError, match="encoded as UTF-8"):
        canonical_stage_receipt_bytes({"invalid": "\ud800"})
    noncanonical = clean / "noncanonical.json"
    noncanonical.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    with pytest.raises(FullSourceStageError, match="not canonical JSON"):
        validate_full_source_stage(output, noncanonical, contract=clean_contract)
    tampered = copy.deepcopy(receipt)
    tampered["logicalHashes"]["placeRows"] = "0" * 64
    with pytest.raises(FullSourceStageError, match="counts or logical hashes"):
        validate_full_source_stage(output, tampered, contract=clean_contract)
    exact_type_mutations = []
    for path in (
        ("schemaVersion",),
        ("toolchain", "threads"),
        ("counts", "admin1Rows"),
        ("sourceBindings", "assets", "admin1", "byteSize"),
    ):
        changed = copy.deepcopy(receipt)
        target = changed
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = True
        exact_type_mutations.append(changed)
    for changed in exact_type_mutations:
        with pytest.raises(FullSourceStageError, match=r"exact (source )?contract"):
            validate_full_source_stage(output, changed, contract=clean_contract)
    with duckdb.connect(str(output)) as connection:
        connection.execute(
            "UPDATE stage_places SET document='{\"value\":NaN}' WHERE geoname_id=1134032"
        )
    with pytest.raises(FullSourceStageError, match="non-finite JSON"):
        validate_full_source_stage(output, receipt_path, contract=clean_contract)
    with duckdb.connect(str(output)) as connection:
        connection.execute("UPDATE stage_places SET document='{}' WHERE geoname_id=1134032")
    with pytest.raises(FullSourceStageError, match="key columns differ"):
        validate_full_source_stage(output, receipt_path, contract=clean_contract)


def test_policy_member_and_symlink_drift_fail_before_promotion(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    inputs.normalization_policy.write_text("{}", encoding="utf-8")
    with pytest.raises(FullSourceStageError, match="normalization policy bytes differ"):
        _build(tmp_path, inputs, contract, "policy")

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    inputs, contract = _fixture(fresh)
    member = replace(contract.all_countries.members[0], crc32="00000000")
    changed = replace(contract, all_countries=replace(contract.all_countries, members=(member,)))
    with pytest.raises(FullSourceStageError, match="ZIP metadata differs"):
        _build(fresh, inputs, changed, "member")

    link_root = tmp_path / "link"
    link_root.mkdir()
    inputs, contract = _fixture(link_root)
    linked = link_root / "linked-readme.txt"
    linked.symlink_to(inputs.readme)
    with pytest.raises(FullSourceStageError, match="regular non-symlink"):
        _build(link_root, replace(inputs, readme=linked), contract, "link")


def test_validator_rejects_self_consistent_truncation_and_schema_drift(tmp_path: Path) -> None:
    inputs, contract = _fixture(tmp_path)
    output, _, receipt = _build(tmp_path, inputs, contract, "truncated")
    truncated = copy.deepcopy(receipt)
    with duckdb.connect(str(output)) as connection:
        connection.execute("DELETE FROM stage_alternates WHERE geoname_id=1134032")
        connection.execute("DELETE FROM stage_places WHERE geoname_id=1134032")
        truncated["counts"]["placeRows"] = 1
        truncated["counts"]["alternateNameRows"] = 3
        truncated["logicalHashes"]["placeRows"] = stage._logical_hash(connection, "stage_places")
        truncated["logicalHashes"]["alternateNameRows"] = stage._logical_hash(
            connection, "stage_alternates"
        )
    with pytest.raises(FullSourceStageError, match="exact source contract"):
        validate_full_source_stage(output, truncated, contract=contract)

    schema_root = tmp_path / "schema"
    schema_root.mkdir()
    inputs, contract = _fixture(schema_root)
    output, receipt_path, _ = _build(schema_root, inputs, contract, "schema")
    with duckdb.connect(str(output)) as connection:
        connection.execute("ALTER TABLE stage_places ADD COLUMN unexpected INTEGER")
    with pytest.raises(FullSourceStageError, match="columns differ"):
        validate_full_source_stage(output, receipt_path, contract=contract)


def test_source_mutation_during_streaming_is_rehashed_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    original = stage._stage_rows

    def mutate_after_stage(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        inputs.readme.write_bytes(b"changed during staging\n")

    monkeypatch.setattr(stage, "_stage_rows", mutate_after_stage)
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "stage.duckdb"
    receipt = tmp_path / "stage.receipt.json"
    with pytest.raises(FullSourceStageError, match="readme bytes differ"):
        build_full_source_stage(inputs, output, receipt, work, contract=contract)
    assert not output.exists() and not receipt.exists()
    assert not list(tmp_path.glob(".full-source-*"))


def test_receipt_path_swap_after_open_keeps_parsing_bound_to_opened_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    output, receipt, document = _build(tmp_path, inputs, contract, "receipt-swap")
    replacement = tmp_path / "replacement.receipt.json"
    changed = copy.deepcopy(document)
    changed["schemaVersion"] = True
    replacement.write_bytes(canonical_stage_receipt_bytes(changed))
    locked_path = tmp_path / "opened.receipt.json"
    original_open = stage._open_regular

    @contextmanager
    def open_with_swap(path: Path, label: str) -> Iterator[object]:
        with original_open(path, label) as stream:
            if path != receipt:
                yield stream
                return
            path.rename(locked_path)
            replacement.rename(path)
            try:
                yield stream
            finally:
                path.rename(replacement)
                locked_path.rename(path)

    monkeypatch.setattr(stage, "_open_regular", open_with_swap)
    validate_full_source_stage(output, receipt, contract=contract)


def test_database_path_identity_change_during_validation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    output, receipt, _ = _build(tmp_path, inputs, contract, "database-swap")
    original_receipt = stage._receipt
    opened_path = tmp_path / "opened.duckdb"

    def swap_after_database_read(
        connection: object, stage_contract: FullSourceStageContract
    ) -> object:
        document = original_receipt(connection, stage_contract)
        output.rename(opened_path)
        shutil.copyfile(opened_path, output)
        return document

    monkeypatch.setattr(stage, "_receipt", swap_after_database_read)
    try:
        with pytest.raises(FullSourceStageError, match="identity changed"):
            validate_full_source_stage(output, receipt, contract=contract)
    finally:
        output.unlink(missing_ok=True)
        opened_path.rename(output)


def test_consumed_admin1_path_swap_fails_against_opened_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    replacement = tmp_path / "admin1-replacement.txt"
    replacement.write_bytes(inputs.admin1.read_bytes().replace(b"Catalonia", b"Catalunya"))
    locked_path = tmp_path / "admin1-locked.txt"
    original_consume = stage._consume_plain_rows

    def consume_swapped(
        path: Path,
        locked: LockedAsset,
        consume: object,
    ) -> None:
        path.rename(locked_path)
        replacement.rename(path)
        try:
            original_consume(path, locked, consume)  # type: ignore[arg-type]
        finally:
            path.rename(replacement)
            locked_path.rename(path)

    monkeypatch.setattr(stage, "_consume_plain_rows", consume_swapped)
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "stage.duckdb"
    receipt = tmp_path / "stage.receipt.json"
    with pytest.raises(FullSourceStageError, match="content or row count differs"):
        build_full_source_stage(inputs, output, receipt, work, contract=contract)
    assert not output.exists() and not receipt.exists()


def test_consumed_zip_path_swap_fails_against_opened_outer_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, contract = _fixture(tmp_path)
    replacement = tmp_path / "allCountries-replacement.zip"
    shutil.copyfile(inputs.all_countries_zip, replacement)
    with zipfile.ZipFile(replacement, "a") as archive:
        archive.comment = b"different outer archive, identical member bytes"
    locked_path = tmp_path / "allCountries-locked.zip"
    original_open = stage._open_verified_zip

    @contextmanager
    def open_swapped(
        path: Path,
        locked: LockedAsset,
        label: str,
    ) -> Iterator[zipfile.ZipFile]:
        if path != inputs.all_countries_zip:
            with original_open(path, locked, label) as archive:
                yield archive
            return
        path.rename(locked_path)
        replacement.rename(path)
        try:
            with original_open(path, locked, label) as archive:
                yield archive
        finally:
            path.rename(replacement)
            locked_path.rename(path)

    monkeypatch.setattr(stage, "_open_verified_zip", open_swapped)
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "stage.duckdb"
    receipt = tmp_path / "stage.receipt.json"
    with pytest.raises(FullSourceStageError, match="archive bytes differ"):
        build_full_source_stage(inputs, output, receipt, work, contract=contract)
    assert not output.exists() and not receipt.exists()


def test_receipt_and_database_link_failures_leave_no_requested_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = stage.os.link
    for fail_on in (1, 2):
        root = tmp_path / f"failure-{fail_on}"
        inputs, contract = _fixture(root)
        work = root / "work"
        work.mkdir()
        output = root / "stage.duckdb"
        receipt = root / "stage.receipt.json"
        calls = 0

        def fail_link(source: Path, target: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == fail_on:
                raise OSError("injected link failure")
            real_link(source, target)

        monkeypatch.setattr(stage.os, "link", fail_link)
        with pytest.raises(FullSourceStageError, match="injected link failure"):
            build_full_source_stage(inputs, output, receipt, work, contract=contract)
        monkeypatch.setattr(stage.os, "link", real_link)
        assert not output.exists() and not receipt.exists()
        assert not list(root.rglob(".full-source-*"))


def test_existing_and_identical_requested_paths_fail_without_overwrite(tmp_path: Path) -> None:
    for existing_name in ("stage.duckdb", "stage.receipt.json"):
        root = tmp_path / existing_name.replace(".", "-")
        inputs, contract = _fixture(root)
        work = root / "work"
        work.mkdir()
        output = root / "stage.duckdb"
        receipt = root / "stage.receipt.json"
        existing = output if existing_name == output.name else receipt
        existing.write_bytes(b"preserve me")
        with pytest.raises(FullSourceStageError, match="overwrite is refused"):
            build_full_source_stage(inputs, output, receipt, work, contract=contract)
        assert existing.read_bytes() == b"preserve me"
        assert not (receipt if existing == output else output).exists()

    root = tmp_path / "identical"
    inputs, contract = _fixture(root)
    work = root / "work"
    work.mkdir()
    same = root / "stage.duckdb"
    with pytest.raises(FullSourceStageError, match="distinct paths"):
        build_full_source_stage(inputs, same, same, work, contract=contract)
    assert not same.exists()


@pytest.mark.parametrize("failure", ["final-validation", "directory-fsync"])
def test_final_pair_validation_and_fsync_failures_roll_back_requested_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    inputs, contract = _fixture(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    output = tmp_path / "stage.duckdb"
    receipt = tmp_path / "stage.receipt.json"
    if failure == "final-validation":
        original_validate = stage.validate_full_source_stage
        calls = 0

        def fail_final(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise FullSourceStageError("injected final pair validation failure")
            original_validate(*args, **kwargs)

        monkeypatch.setattr(stage, "validate_full_source_stage", fail_final)
    else:
        original_fsync = stage._fsync_directory
        calls = 0

        def fail_first_fsync(path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FullSourceStageError("injected directory fsync failure")
            original_fsync(path)

        monkeypatch.setattr(stage, "_fsync_directory", fail_first_fsync)

    with pytest.raises(FullSourceStageError, match="injected"):
        build_full_source_stage(inputs, output, receipt, work, contract=contract)
    assert not output.exists() and not receipt.exists()
    assert not list(tmp_path.glob(".full-source-*"))
