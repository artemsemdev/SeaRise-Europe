"""Strict parsing for the complete, pinned GeoNames settlement inputs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date


class GeoNamesParseError(ValueError):
    """The pinned GeoNames input is incomplete, malformed, or contradictory."""


@dataclass(frozen=True)
class SourceIdentity:
    asset_id: str
    source_file: str
    source_release: str
    asset_sha256: str
    asset_byte_size: int
    source_sha256: str
    source_byte_size: int
    source_compressed_byte_size: int | None
    source_crc32: str | None


ALL_COUNTRIES_SOURCE = SourceIdentity(
    asset_id="all-countries",
    source_file="allCountries.txt",
    source_release="2026-08-10",
    asset_sha256="06f423eaf760d28101cd11a9744ade90f65c618d073ac2168501c388e1bd4afa",
    asset_byte_size=419923777,
    source_sha256="4217bcadfce0d86d7f39244259dbbb96e5d1a610faedc3b4761bb96dcc492bf8",
    source_byte_size=1782635669,
    source_compressed_byte_size=419923631,
    source_crc32="27133946",
)
ADMIN1_SOURCE = SourceIdentity(
    asset_id="admin1-codes-ascii",
    source_file="admin1CodesASCII.txt",
    source_release="2026-08-10",
    asset_sha256="34784457b76b988a669dff7c3e4b104e4902c0875643cff019281ac79dfa2992",
    asset_byte_size=151572,
    source_sha256="34784457b76b988a669dff7c3e4b104e4902c0875643cff019281ac79dfa2992",
    source_byte_size=151572,
    source_compressed_byte_size=None,
    source_crc32=None,
)
RAW_ANOMALY_POLICY_VERSION = "geonames-place-raw-anomalies-v1"

_UINT = re.compile(r"^[1-9][0-9]*$")
_NONNEGATIVE_INT = re.compile(r"^(?:0|[1-9][0-9]*)$")
_SIGNED_INT = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FEATURE_CODE = re.compile(r"^[A-Z][A-Z0-9]*$")


@dataclass(frozen=True)
class Lineage:
    asset_id: str
    source_file: str
    source_release: str
    source_line: int
    source_record_id: int
    source_sha256: str


@dataclass(frozen=True)
class FieldAnomaly:
    field: str
    code: str


@dataclass(frozen=True)
class GeoNameRecord:
    geoname_id: int
    name: str
    ascii_name: str
    convenience_alternate_names_raw: str
    convenience_alternate_names: tuple[str, ...]
    latitude: float
    longitude: float
    feature_class: str | None
    feature_code: str | None
    country_code: str | None
    alternate_country_codes_raw: str
    alternate_country_codes: tuple[str, ...]
    admin1_code: str | None
    admin2_code: str | None
    admin3_code: str | None
    admin4_code: str | None
    population: int | None
    elevation: int | None
    dem: int | None
    timezone: str | None
    modification_date: date
    anomalies: tuple[FieldAnomaly, ...]
    lineage: Lineage


@dataclass(frozen=True)
class Admin1Record:
    country_code: str
    admin1_code: str
    name: str
    ascii_name: str
    geoname_id: int
    lineage: Lineage

    @property
    def key(self) -> str:
        return f"{self.country_code}.{self.admin1_code}"


def _fail(identity: SourceIdentity, source_line: int, message: str) -> GeoNamesParseError:
    return GeoNamesParseError(f"{identity.source_file}:{source_line}: {message}")


def _columns(row: bytes, *, identity: SourceIdentity, source_line: int, expected: int) -> list[str]:
    if source_line < 1:
        raise _fail(identity, source_line, "source line must be positive")
    try:
        text = row.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _fail(identity, source_line, "row is not valid UTF-8") from exc
    if any(ord(character) < 32 and character != "\t" for character in text):
        raise _fail(identity, source_line, "row contains a forbidden control character")
    columns = text.split("\t")
    if len(columns) != expected:
        raise _fail(
            identity,
            source_line,
            f"expected exactly {expected} tab columns, found {len(columns)}",
        )
    return columns


def _text(
    value: str,
    *,
    identity: SourceIdentity,
    source_line: int,
    field: str,
    required: bool,
    allow_del_c1: bool = False,
) -> str | None:
    if not value:
        if required:
            raise _fail(identity, source_line, f"{field} is empty")
        return None
    if value != value.strip(" ") or any(ord(character) < 32 for character in value):
        raise _fail(identity, source_line, f"{field} has unsafe whitespace or controls")
    if not allow_del_c1 and _has_del_c1(value):
        raise _fail(identity, source_line, f"{field} has a DEL/C1 provider codepoint")
    return value


def _has_del_c1(value: str) -> bool:
    return any(0x7F <= ord(character) <= 0x9F for character in value)


def _positive_int(value: str, *, identity: SourceIdentity, source_line: int, field: str) -> int:
    if not _UINT.fullmatch(value):
        raise _fail(identity, source_line, f"{field} must be a canonical positive integer")
    return int(value)


def _optional_int(
    value: str,
    *,
    identity: SourceIdentity,
    source_line: int,
    field: str,
    nonnegative: bool,
) -> int | None:
    if value == "":
        return None
    pattern = _NONNEGATIVE_INT if nonnegative else _SIGNED_INT
    if not pattern.fullmatch(value):
        qualifier = "non-negative " if nonnegative else ""
        raise _fail(identity, source_line, f"{field} must be a canonical {qualifier}integer")
    return int(value)


def _coordinate(
    value: str,
    *,
    identity: SourceIdentity,
    source_line: int,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    if not _DECIMAL.fullmatch(value):
        raise _fail(identity, source_line, f"{field} must be a finite decimal")
    parsed = float(value)
    if parsed == 0.0 and value.startswith("-"):
        raise _fail(identity, source_line, f"{field} uses non-canonical negative zero")
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise _fail(identity, source_line, f"{field} is outside [{minimum}, {maximum}]")
    return parsed


def _lineage(identity: SourceIdentity, source_line: int, record_id: int) -> Lineage:
    return Lineage(
        asset_id=identity.asset_id,
        source_file=identity.source_file,
        source_release=identity.source_release,
        source_line=source_line,
        source_record_id=record_id,
        source_sha256=identity.source_sha256,
    )


def parse_geoname_row(row: bytes, *, source_line: int) -> GeoNameRecord:
    """Parse one exact 19-column allCountries member row."""
    values = _columns(row, identity=ALL_COUNTRIES_SOURCE, source_line=source_line, expected=19)
    geoname_id = _positive_int(
        values[0], identity=ALL_COUNTRIES_SOURCE, source_line=source_line, field="geonameId"
    )
    name = _text(
        values[1],
        identity=ALL_COUNTRIES_SOURCE,
        source_line=source_line,
        field="name",
        required=True,
        allow_del_c1=True,
    )
    ascii_name = _text(
        values[2],
        identity=ALL_COUNTRIES_SOURCE,
        source_line=source_line,
        field="asciiName",
        required=True,
    )
    assert name is not None and ascii_name is not None
    raw_convenience = values[3]
    convenience = tuple(raw_convenience.split(",")) if raw_convenience else ()
    if any(item == "" for item in convenience):
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "alternate names contain an empty token")
    latitude = _coordinate(
        values[4],
        identity=ALL_COUNTRIES_SOURCE,
        source_line=source_line,
        field="latitude",
        minimum=-90.0,
        maximum=90.0,
    )
    longitude = _coordinate(
        values[5],
        identity=ALL_COUNTRIES_SOURCE,
        source_line=source_line,
        field="longitude",
        minimum=-180.0,
        maximum=180.0,
    )
    feature_class = values[6] or None
    if feature_class is not None and not re.fullmatch(r"^[A-Z]$", feature_class):
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "feature class is invalid")
    feature_code = values[7] or None
    if feature_code is not None and not _FEATURE_CODE.fullmatch(feature_code):
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "feature code is invalid")
    country_code = values[8] or None
    if country_code is not None and not _COUNTRY.fullmatch(country_code):
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "country code is invalid")
    raw_alternate_countries = values[9]
    alternate_tokens = raw_alternate_countries.split(",") if raw_alternate_countries else []
    leading_empty_country = len(alternate_tokens) > 1 and alternate_tokens[0] == ""
    if leading_empty_country and country_code is not None:
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "leading empty token requires no country")
    alternate_countries = tuple(alternate_tokens[int(leading_empty_country) :])
    if any(item == "" for item in alternate_countries):
        raise _fail(
            ALL_COUNTRIES_SOURCE, source_line, "alternate country codes contain an empty token"
        )
    if any(not _COUNTRY.fullmatch(item) for item in alternate_countries):
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "alternate country code is invalid")
    try:
        modified = date.fromisoformat(values[18])
    except ValueError as exc:
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "modification date is invalid") from exc
    if modified.isoformat() != values[18]:
        raise _fail(ALL_COUNTRIES_SOURCE, source_line, "modification date is not canonical")
    population = _optional_int(
        values[14],
        identity=ALL_COUNTRIES_SOURCE,
        source_line=source_line,
        field="population",
        nonnegative=False,
    )
    anomalies = []
    if _has_del_c1(name):
        anomalies.append(FieldAnomaly("name", "provider-del-c1-codepoint"))
    if _has_del_c1(raw_convenience):
        anomalies.append(FieldAnomaly("convenience_alternate_names", "provider-del-c1-codepoint"))
    if any(item != item.strip(" ") for item in convenience):
        anomalies.append(FieldAnomaly("convenience_alternate_names", "edge-ascii-space"))
    if leading_empty_country:
        anomalies.append(FieldAnomaly("alternate_country_codes", "leading-empty-source-token"))
    if population is not None and population < 0:
        anomalies.append(FieldAnomaly("population", "negative-source-value"))
    return GeoNameRecord(
        geoname_id=geoname_id,
        name=name,
        ascii_name=ascii_name,
        convenience_alternate_names_raw=raw_convenience,
        convenience_alternate_names=convenience,
        latitude=latitude,
        longitude=longitude,
        feature_class=feature_class,
        feature_code=feature_code,
        country_code=country_code,
        alternate_country_codes_raw=raw_alternate_countries,
        alternate_country_codes=alternate_countries,
        admin1_code=_text(
            values[10],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="admin1",
            required=False,
        ),
        admin2_code=_text(
            values[11],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="admin2",
            required=False,
        ),
        admin3_code=_text(
            values[12],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="admin3",
            required=False,
        ),
        admin4_code=_text(
            values[13],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="admin4",
            required=False,
        ),
        population=population,
        elevation=_optional_int(
            values[15],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="elevation",
            nonnegative=False,
        ),
        dem=_optional_int(
            values[16],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="dem",
            nonnegative=False,
        ),
        timezone=_text(
            values[17],
            identity=ALL_COUNTRIES_SOURCE,
            source_line=source_line,
            field="timezone",
            required=False,
        ),
        modification_date=modified,
        anomalies=tuple(anomalies),
        lineage=_lineage(ALL_COUNTRIES_SOURCE, source_line, geoname_id),
    )


def parse_admin1_row(row: bytes, *, source_line: int) -> Admin1Record:
    """Parse one exact four-column admin1CodesASCII row."""
    values = _columns(row, identity=ADMIN1_SOURCE, source_line=source_line, expected=4)
    key_parts = values[0].split(".")
    if (
        len(key_parts) != 2
        or not _COUNTRY.fullmatch(key_parts[0])
        or not _CODE.fullmatch(key_parts[1])
    ):
        raise _fail(ADMIN1_SOURCE, source_line, "admin1 composite code is invalid")
    name = _text(
        values[1], identity=ADMIN1_SOURCE, source_line=source_line, field="name", required=True
    )
    ascii_name = _text(
        values[2],
        identity=ADMIN1_SOURCE,
        source_line=source_line,
        field="asciiName",
        required=True,
    )
    assert name is not None and ascii_name is not None
    geoname_id = _positive_int(
        values[3], identity=ADMIN1_SOURCE, source_line=source_line, field="geonameId"
    )
    return Admin1Record(
        country_code=key_parts[0],
        admin1_code=key_parts[1],
        name=name,
        ascii_name=ascii_name,
        geoname_id=geoname_id,
        lineage=_lineage(ADMIN1_SOURCE, source_line, geoname_id),
    )
