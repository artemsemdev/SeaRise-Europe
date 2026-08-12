"""TDD contract for exact GeoNames alternate-name parsing and selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from searise_pipeline.settlements.alternate_names import (
    ALTERNATE_NAMES_SOURCE,
    ISO_LANGUAGE_SOURCE,
    NON_LANGUAGE_NAMESPACES,
    NORMALIZATION_POLICY_VERSION,
    NameVariant,
    language_codes,
    load_normalization_policy,
    parse_alternate_name_row,
    parse_iso_language_row,
    select_names,
)
from searise_pipeline.settlements.geonames import GeoNamesParseError, Lineage

FIXTURES = Path(__file__).with_name("fixtures") / "geonames"
ROOT = Path(__file__).parents[4]
MANIFEST = json.loads((FIXTURES / "alternate-fixture-manifest.json").read_text())
POLICY = ROOT / "src/pipeline/settlements/normalization-policy-v2.json"


def _rows(name: str) -> list[tuple[bytes, dict]]:
    source = next(item for item in MANIFEST["sources"] if item["fixtureFile"] == name)
    lines = (FIXTURES / name).read_bytes().splitlines()
    return [(lines[item["fixtureLine"] - 1], item) for item in source["rows"]]


def _alternates() -> list:
    return [
        parse_alternate_name_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows("alternateNamesV2.rows.txt")
    ]


def _languages() -> frozenset[str]:
    return language_codes(
        parse_iso_language_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows("iso-languagecodes.rows.txt")
    )


def _mutate(row: bytes, column: int, value: bytes) -> bytes:
    values = row.split(b"\t")
    values[column] = value
    return b"\t".join(values)


def test_fixtures_are_bound_to_the_locked_asset_and_members() -> None:
    lock_path = ROOT / MANIFEST["sourceLock"]["path"]
    assert hashlib.sha256(lock_path.read_bytes()).hexdigest() == MANIFEST["sourceLock"]["sha256"]
    lock = json.loads(lock_path.read_text())
    asset = next(
        item for item in lock["sources"][0]["assets"] if item["id"] == "alternate-names-v2"
    )
    assert (asset["sha256"], asset["byteSize"]) == (
        ALTERNATE_NAMES_SOURCE.asset_sha256,
        ALTERNATE_NAMES_SOURCE.asset_byte_size,
    )
    identities = {
        "alternateNamesV2.rows.txt": (ALTERNATE_NAMES_SOURCE, 10),
        "iso-languagecodes.rows.txt": (ISO_LANGUAGE_SOURCE, 4),
    }
    for source in MANIFEST["sources"]:
        identity, width = identities[source["fixtureFile"]]
        member = next(item for item in asset["members"] if item["path"] == source["sourceFile"])
        observed = (
            member["sha256"],
            member["byteSize"],
            member["compressedByteSize"],
            member["crc32"],
        )
        expected = (
            identity.source_sha256,
            identity.source_byte_size,
            identity.source_compressed_byte_size,
            identity.source_crc32,
        )
        assert observed == expected
        contents = (FIXTURES / source["fixtureFile"]).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == source["fixtureSha256"]
        assert all(len(row.split(b"\t")) == width for row in contents.splitlines())


def test_exact_rows_preserve_flags_periods_scripts_and_lineage() -> None:
    records = {record.alternate_name_id: record for record in _alternates()}
    catalan = records[1297839]
    assert (catalan.language_tag, catalan.name, catalan.preferred, catalan.short) == (
        "ca",
        "Sant Julià de Lòria",
        True,
        True,
    )
    assert catalan.lineage == Lineage(
        "alternate-names-v2",
        "alternateNamesV2.txt",
        "2026-08-10",
        128,
        1297839,
        ALTERNATE_NAMES_SOURCE.source_sha256,
    )
    assert (records[135316].historic, records[135316].valid_from, records[135316].valid_to) == (
        True,
        "1935",
        "1957",
    )
    assert records[3926787].valid_from == "20250101"
    assert records[2170607].language_tag == "post"
    assert records[11352176].as_name_variant() == NameVariant("سانت جوليا دي لوريا", "ar", "Arab")
    assert records[11352177].as_name_variant().script == "Cyrl"
    assert records[11352194].as_name_variant().script == "Hani"


def test_language_rows_preserve_identity_and_bibliographic_aliases() -> None:
    records = [
        parse_iso_language_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows("iso-languagecodes.rows.txt")
    ]
    french = next(record for record in records if record.iso639_3 == "fra")
    assert (french.iso639_2, french.iso639_1, french.source_line) == (("fra", "fre"), "fr", 2014)
    assert {"ar", "ara", "ca", "cat", "en", "eng", "fr", "fra", "fre"} <= language_codes(records)


def test_selection_is_canonical_deterministic_deduplicated_and_lineage_preserving() -> None:
    records = [item for item in _alternates() if item.geoname_id == 3039162]
    selected = select_names(
        geoname_id=3039162,
        source_name="Sant Julià de Lòria",
        records=reversed(records),
        known_language_codes=_languages(),
        as_of=date(2026, 8, 10),
    )
    assert selected.canonical == NameVariant("Sant Julià de Lòria", None, "Latn")
    assert selected.alternates == (
        NameVariant("Parròquia de Sant Julià de Lòria", "ca", "Latn"),
        NameVariant("Sant Julià de Loria", "en", "Latn"),
        NameVariant("سانت جوليا دي لوريا", "ar", "Arab"),
        NameVariant("Сан Джулия де Лория", "bg", "Cyrl"),
        NameVariant("圣胡利娅-德洛里亚", "zh", "Hani"),
    )
    assert [item.alternate_name_id for item in selected.selected_records] == [
        1297841,
        1297840,
        11352176,
        11352177,
        11352194,
    ]
    assert [item.lineage.source_line for item in selected.selected_records] == [
        130,
        129,
        136,
        137,
        154,
    ]
    assert dict(selected.rejections) == {"duplicate-name": 1, "non-language-namespace": 1}


def test_selection_excludes_historic_inactive_unknown_and_empty_names() -> None:
    records = {item.alternate_name_id: item for item in _alternates()}
    unknown = parse_alternate_name_row(
        _mutate(_rows("alternateNamesV2.rows.txt")[1][0], 2, b"zz"), source_line=129
    )
    empty = replace(unknown, language_tag="en", name="", anomalies=("empty-source-name",))
    historic, dated = records[135316], records[3926787]
    cases = [
        (historic, date(2026, 8, 10), "historic-name"),
        (dated, date(2024, 1, 1), "not-yet-valid"),
        (unknown, date(2026, 8, 10), "unknown-language"),
        (empty, date(2026, 8, 10), "empty-source-name"),
    ]
    for record, as_of, reason in cases:
        selection = select_names(
            geoname_id=record.geoname_id,
            source_name="Place",
            records=[record],
            known_language_codes=_languages(),
            as_of=as_of,
        )
        assert dict(selection.rejections) == {reason: 1}
        assert selection.selected_records == ()


@pytest.mark.parametrize(
    ("column", "value"),
    [(0, b"0"), (0, b"01"), (1, b"0"), (2, b"en_US"), (4, b"0"), (7, b"true")],
)
def test_alternate_rows_fail_closed_on_malformed_fields(column: int, value: bytes) -> None:
    row = _rows("alternateNamesV2.rows.txt")[0][0]
    with pytest.raises(GeoNamesParseError):
        parse_alternate_name_row(_mutate(row, column, value), source_line=128)


def test_rows_and_selection_fail_closed_on_contract_drift() -> None:
    row = _rows("alternateNamesV2.rows.txt")[0][0]
    for invalid, line in ((b"\t".join(row.split(b"\t")[:-1]), 128), (b"\xff", 128), (row, 0)):
        with pytest.raises(GeoNamesParseError):
            parse_alternate_name_row(invalid, source_line=line)
    with pytest.raises(ValueError, match="different GeoNames place"):
        select_names(
            geoname_id=3039162,
            source_name="Place",
            records=[_alternates()[0], replace(_alternates()[0], geoname_id=1)],
            known_language_codes=_languages(),
            as_of=date(2026, 8, 10),
        )
    iso = _rows("iso-languagecodes.rows.txt")[0][0]
    with pytest.raises(GeoNamesParseError):
        parse_iso_language_row(_mutate(iso, 0, b"ARA"), source_line=417)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "sourceSnapshot", "2099-01-01"),
        ("alternateNames", "historic", "include"),
        ("alternateNames", "unknownLanguage", "include"),
        ("alternateNames", "ordering", ["alternate-name-id-asc"]),
    ],
)
def test_policy_rejects_semantic_drift(
    tmp_path: Path, section: str | None, field: str, value: object
) -> None:
    policy = load_normalization_policy(POLICY)
    assert policy["policyVersion"] == NORMALIZATION_POLICY_VERSION
    assert tuple(policy["alternateNames"]["excludedNamespaces"]) == tuple(
        sorted(NON_LANGUAGE_NAMESPACES)
    )
    assert policy["alternateNames"]["iso639ThreeOnlyMetadata"] == "accept"
    mutated = json.loads(json.dumps(policy))
    target = mutated if section is None else mutated[section]
    target[field] = value
    bad_policy = tmp_path / "normalization-policy.json"
    bad_policy.write_text(json.dumps(mutated))
    with pytest.raises(ValueError, match="implemented v2 contract"):
        load_normalization_policy(bad_policy)
