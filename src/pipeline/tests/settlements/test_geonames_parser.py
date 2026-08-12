"""Strict parser tests for pinned GeoNames place and admin1 rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from searise_pipeline.settlements.geonames import (
    ADMIN1_SOURCE,
    ALL_COUNTRIES_SOURCE,
    RAW_ANOMALY_POLICY_VERSION,
    FieldAnomaly,
    GeoNamesParseError,
    Lineage,
    parse_admin1_row,
    parse_geoname_row,
)

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "geonames"
REPO_ROOT = Path(__file__).parents[4]
MANIFEST = json.loads((FIXTURE_DIR / "fixture-manifest.json").read_text(encoding="utf-8"))


def _source(fixture_file: str) -> dict:
    return next(item for item in MANIFEST["sources"] if item["fixtureFile"] == fixture_file)


def _rows(fixture_file: str) -> list[tuple[bytes, dict]]:
    source = _source(fixture_file)
    lines = (FIXTURE_DIR / fixture_file).read_bytes().splitlines()
    return [(lines[item["fixtureLine"] - 1], item) for item in source["rows"]]


def _mutate(row: bytes, index: int, value: bytes) -> bytes:
    columns = row.split(b"\t")
    columns[index] = value
    return b"\t".join(columns)


def test_committed_rows_are_hash_bound_real_format_excerpts() -> None:
    assert MANIFEST["snapshotDate"] == "2026-08-10"
    assert MANIFEST["rawAnomalyPolicyVersion"] == RAW_ANOMALY_POLICY_VERSION
    assert MANIFEST["fixtureClass"] == "hash-verified-real-format-excerpt"
    assert MANIFEST["productionInput"] is False
    widths = {"allCountries.rows.txt": 19, "admin1CodesASCII.rows.txt": 4}
    identities = {
        "allCountries.rows.txt": ALL_COUNTRIES_SOURCE,
        "admin1CodesASCII.rows.txt": ADMIN1_SOURCE,
    }
    lock_path = REPO_ROOT / MANIFEST["sourceLock"]["path"]
    assert hashlib.sha256(lock_path.read_bytes()).hexdigest() == MANIFEST["sourceLock"]["sha256"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    locked_source = next(
        item for item in lock["sources"] if item["id"] == "geonames-settlement-catalogue"
    )
    for source in MANIFEST["sources"]:
        identity = identities[source["fixtureFile"]]
        asset = next(item for item in locked_source["assets"] if item["id"] == source["assetId"])
        assert (
            (source["sourceAssetSha256"], source["sourceAssetByteSize"])
            == (asset["sha256"], asset["byteSize"])
            == (identity.asset_sha256, identity.asset_byte_size)
        )
        member = next(iter(asset.get("members", ())), asset)
        assert (
            (
                source["sourceFile"],
                source["sourceSha256"],
                source["sourceByteSize"],
                source["sourceCompressedByteSize"],
                source["sourceCrc32"],
            )
            == (
                member.get("path", asset["cachePath"]),
                member["sha256"],
                member["byteSize"],
                member.get("compressedByteSize"),
                member.get("crc32"),
            )
            == (
                identity.source_file,
                identity.source_sha256,
                identity.source_byte_size,
                identity.source_compressed_byte_size,
                identity.source_crc32,
            )
        )
        contents = (FIXTURE_DIR / source["fixtureFile"]).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == source["fixtureSha256"]
        contents.decode("utf-8", errors="strict")
        assert all(
            len(line.split(b"\t")) == widths[source["fixtureFile"]]
            for line in contents.splitlines()
        )
        parser = parse_geoname_row if identity is ALL_COUNTRIES_SOURCE else parse_admin1_row
        for row, metadata in _rows(source["fixtureFile"]):
            record = parser(row, source_line=metadata["sourceLine"])
            assert record.geoname_id == metadata["sourceRecordId"]
            assert record.lineage == Lineage(
                identity.asset_id,
                identity.source_file,
                identity.source_release,
                metadata["sourceLine"],
                metadata["sourceRecordId"],
                identity.source_sha256,
            )


def test_real_rows_parse_diacritics_zero_population_and_exact_lineage() -> None:
    places = {
        metadata["sourceRecordId"]: parse_geoname_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows("allCountries.rows.txt")
    }
    ramio = places[3039322]
    assert (ramio.name, ramio.ascii_name, ramio.population) == ("Ràmio", "Ramio", 0)
    assert (ramio.country_code, ramio.admin1_code) == ("AD", "08")
    assert ramio.lineage.source_line == 513
    assert ramio.lineage.source_sha256 == ALL_COUNTRIES_SOURCE.source_sha256
    assert places[1134032].name == "Mana’ī "
    assert places[6638545].feature_code is None
    assert (places[6638554].feature_class, places[6638554].feature_code) == (None, None)
    assert places[3344077].admin2_code == "Kanton Sarajevo"
    assert places[2967788].ascii_name == "Vœlfling-les-Bouzonville"
    assert places[1524311].admin1_code == "Shymkent (undefined)"
    assert places[6546165].admin3_code == "1e+010"
    assert places[1482375].admin4_code == "Deshiwal (undefined)"
    placeholder = places[281173]
    assert placeholder.alternate_country_codes_raw == ",PS"
    assert placeholder.alternate_country_codes == ("PS",)
    assert placeholder.anomalies == (
        FieldAnomaly("alternate_country_codes", "leading-empty-source-token"),
    )

    edge = places[290854]
    assert edge.convenience_alternate_names_raw.startswith("Wadi Al Shaikh ,")
    assert edge.convenience_alternate_names[0] == "Wadi Al Shaikh "
    assert edge.anomalies == (FieldAnomaly("convenience_alternate_names", "edge-ascii-space"),)
    c1 = places[12564634]
    assert c1.anomalies == (
        FieldAnomaly("name", "provider-del-c1-codepoint"),
        FieldAnomaly("convenience_alternate_names", "provider-del-c1-codepoint"),
    )
    for record_id, value in ((7576740, -12), (7576827, -3)):
        assert (places[record_id].population, places[record_id].anomalies) == (
            value,
            (FieldAnomaly("population", "negative-source-value"),),
        )

    admins = [
        parse_admin1_row(row, source_line=metadata["sourceLine"])
        for row, metadata in _rows("admin1CodesASCII.rows.txt")
    ]
    assert (admins[2].key, admins[2].name) == ("AE.01", "Abu Dhabi")
    assert admins[2].lineage.source_line == 14


@pytest.mark.parametrize(
    ("parser", "fixture_file"),
    [(parse_geoname_row, "allCountries.rows.txt"), (parse_admin1_row, "admin1CodesASCII.rows.txt")],
)
@pytest.mark.parametrize("column_delta", [-1, 1])
def test_fixed_width_rows_reject_missing_and_extra_columns(
    parser, fixture_file: str, column_delta: int
) -> None:
    row = _rows(fixture_file)[0][0]
    columns = row.split(b"\t")
    mutated = b"\t".join(columns[:-1] if column_delta < 0 else [*columns, b"extra"])
    with pytest.raises(GeoNamesParseError, match="column"):
        parser(mutated, source_line=1)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        (0, b"0"),
        (0, b"01"),
        (4, b"NaN"),
        (4, b"Inf"),
        (4, b"+01."),
        (4, b".5"),
        (4, b"1."),
        (4, b"01"),
        (4, b"-0"),
        (4, b"-0.0"),
        (4, b"90.0001"),
        (5, b"-180.0001"),
        (14, b"01"),
        (14, b"-0"),
        (18, b"2026-02-30"),
    ],
)
def test_geoname_numeric_coordinate_and_date_fields_fail_closed(column: int, value: bytes) -> None:
    row = _rows("allCountries.rows.txt")[0][0]
    with pytest.raises(GeoNamesParseError):
        parse_geoname_row(_mutate(row, column, value), source_line=179)


@pytest.mark.parametrize(
    ("parser", "fixture_file"),
    [(parse_geoname_row, "allCountries.rows.txt"), (parse_admin1_row, "admin1CodesASCII.rows.txt")],
)
def test_rows_reject_invalid_utf8_controls_and_nonpositive_lineage(
    parser, fixture_file: str
) -> None:
    row = _rows(fixture_file)[0][0]
    for mutated, source_line in ((b"\xff", 1), (row + b"\x00", 1), (row, 0)):
        with pytest.raises(GeoNamesParseError):
            parser(mutated, source_line=source_line)


def test_geoname_codes_and_admin1_contracts_fail_closed() -> None:
    geoname = _rows("allCountries.rows.txt")[0][0]
    for column, value in ((6, b"PP"), (7, b"PPL!"), (8, b"and"), (10, b" bad ")):
        with pytest.raises(GeoNamesParseError):
            parse_geoname_row(_mutate(geoname, column, value), source_line=179)
    for aliases in (b",name", b"name,", b"name,,alias"):
        with pytest.raises(GeoNamesParseError, match="empty token"):
            parse_geoname_row(_mutate(geoname, 3, aliases), source_line=179)
    for countries in (b"AE,", b"AE,,FR", b",", b",,AE", b",AE,"):
        with pytest.raises(GeoNamesParseError, match="empty token"):
            parse_geoname_row(_mutate(geoname, 9, countries), source_line=179)
    with pytest.raises(GeoNamesParseError, match="requires no country"):
        parse_geoname_row(_mutate(geoname, 9, b",AE"), source_line=179)

    admin = _rows("admin1CodesASCII.rows.txt")[0][0]
    for column, value in ((0, b"AD"), (0, b"ad.05"), (1, b"Bad\xc2\x81"), (3, b"0")):
        with pytest.raises(GeoNamesParseError):
            parse_admin1_row(_mutate(admin, column, value), source_line=2)


def test_source_identities_pin_exact_complete_assets() -> None:
    assert (ALL_COUNTRIES_SOURCE.source_file, ADMIN1_SOURCE.source_file) == (
        "allCountries.txt",
        "admin1CodesASCII.txt",
    )
    assert len(ALL_COUNTRIES_SOURCE.source_sha256) == 64
    assert len(ADMIN1_SOURCE.source_sha256) == 64
