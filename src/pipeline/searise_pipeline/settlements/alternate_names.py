"""Strict GeoNames alternate-name parsing and deterministic normalization."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from .geonames import GeoNamesParseError, Lineage, SourceIdentity

NORMALIZATION_POLICY_VERSION = "settlement-normalization-v2"

ALTERNATE_NAMES_SOURCE = SourceIdentity(
    asset_id="alternate-names-v2",
    source_file="alternateNamesV2.txt",
    source_release="2026-08-10",
    asset_sha256="eaea640b50b7081f7270d9563720b66d6b345af81522a6eb8ee55873507b17fe",
    asset_byte_size=202510374,
    source_sha256="63453d348543a363bbd33a461c41e769de59d293c3fd62ca408eb3e2b0b47612",
    source_byte_size=777625687,
    source_compressed_byte_size=202448178,
    source_crc32="e311a5a6",
)
ISO_LANGUAGE_SOURCE = SourceIdentity(
    asset_id="alternate-names-v2",
    source_file="iso-languagecodes.txt",
    source_release="2026-08-10",
    asset_sha256=ALTERNATE_NAMES_SOURCE.asset_sha256,
    asset_byte_size=ALTERNATE_NAMES_SOURCE.asset_byte_size,
    source_sha256="cb0d34f492775deec8ec5713da6efa4463dad99b5e7ba2172bd094cfdcb76571",
    source_byte_size=137908,
    source_compressed_byte_size=61908,
    source_crc32="4e1f14da",
)

NON_LANGUAGE_NAMESPACES = frozenset(
    {
        "abbr",
        "faac",
        "fr_1793",
        "geoid",
        "iata",
        "icao",
        "lauc",
        "link",
        "nuts",
        "phon",
        "piny",
        "post",
        "tcid",
        "uicn",
        "unlc",
        "wkdt",
    }
)

_UINT = re.compile(r"^[1-9][0-9]*$")
_LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}|[0-9]{3}))?$")
_CODE_2 = re.compile(r"^[a-z]{2}$")
_CODE_3 = re.compile(r"^[a-z]{3}$")
_PERIOD = re.compile(r"^(?:[0-9]{4}|[0-9]{6}|[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})$")


@dataclass(frozen=True)
class NameVariant:
    value: str
    language: str | None
    script: str | None


@dataclass(frozen=True)
class AlternateNameRecord:
    alternate_name_id: int
    geoname_id: int
    language_tag: str | None
    name: str
    preferred: bool
    short: bool
    colloquial: bool
    historic: bool
    valid_from: str | None
    valid_to: str | None
    anomalies: tuple[str, ...]
    lineage: Lineage

    def as_name_variant(self) -> NameVariant:
        language = self.language_tag.split("-", 1)[0] if self.language_tag else None
        return NameVariant(
            unicodedata.normalize("NFC", self.name), language, detect_script(self.name)
        )


@dataclass(frozen=True)
class IsoLanguageRecord:
    iso639_3: str | None
    iso639_2: tuple[str, ...]
    iso639_1: str | None
    name: str
    source_line: int


@dataclass(frozen=True)
class NameSelection:
    canonical: NameVariant
    alternates: tuple[NameVariant, ...]
    selected_records: tuple[AlternateNameRecord, ...]
    rejections: tuple[tuple[str, int], ...]


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
            identity, source_line, f"expected exactly {expected} tab columns, found {len(columns)}"
        )
    return columns


def _positive_int(value: str, *, identity: SourceIdentity, source_line: int, field: str) -> int:
    if not _UINT.fullmatch(value):
        raise _fail(identity, source_line, f"{field} must be a canonical positive integer")
    return int(value)


def _flag(value: str, *, source_line: int, field: str) -> bool:
    if value not in {"", "1"}:
        raise _fail(ALTERNATE_NAMES_SOURCE, source_line, f"{field} must be empty or 1")
    return value == "1"


def parse_alternate_name_row(row: bytes, *, source_line: int) -> AlternateNameRecord:
    """Parse one exact ten-column ``alternateNamesV2.txt`` row."""
    values = _columns(row, identity=ALTERNATE_NAMES_SOURCE, source_line=source_line, expected=10)
    alternate_name_id = _positive_int(
        values[0], identity=ALTERNATE_NAMES_SOURCE, source_line=source_line, field="alternateNameId"
    )
    geoname_id = _positive_int(
        values[1], identity=ALTERNATE_NAMES_SOURCE, source_line=source_line, field="geonameId"
    )
    language_tag = values[2] or None
    if (
        language_tag
        and language_tag not in NON_LANGUAGE_NAMESPACES
        and not _LANGUAGE_TAG.fullmatch(language_tag)
    ):
        raise _fail(ALTERNATE_NAMES_SOURCE, source_line, "isoLanguage has invalid syntax")
    name = values[3]
    anomalies = []
    if not name:
        anomalies.append("empty-source-name")
    elif name != name.strip(" "):
        anomalies.append("edge-ascii-space")
    if any(0x7F <= ord(character) <= 0x9F for character in name):
        anomalies.append("provider-del-c1-codepoint")
    for field, raw in (("from", values[8]), ("to", values[9])):
        if raw and not _PERIOD.fullmatch(raw):
            anomalies.append(f"unparseable-{field}-period")
    return AlternateNameRecord(
        alternate_name_id=alternate_name_id,
        geoname_id=geoname_id,
        language_tag=language_tag,
        name=name,
        preferred=_flag(values[4], source_line=source_line, field="isPreferredName"),
        short=_flag(values[5], source_line=source_line, field="isShortName"),
        colloquial=_flag(values[6], source_line=source_line, field="isColloquial"),
        historic=_flag(values[7], source_line=source_line, field="isHistoric"),
        valid_from=values[8] or None,
        valid_to=values[9] or None,
        anomalies=tuple(anomalies),
        lineage=Lineage(
            ALTERNATE_NAMES_SOURCE.asset_id,
            ALTERNATE_NAMES_SOURCE.source_file,
            ALTERNATE_NAMES_SOURCE.source_release,
            source_line,
            alternate_name_id,
            ALTERNATE_NAMES_SOURCE.source_sha256,
        ),
    )


def parse_iso_language_row(row: bytes, *, source_line: int) -> IsoLanguageRecord:
    """Parse one four-column locked ``iso-languagecodes.txt`` data row."""
    values = _columns(row, identity=ISO_LANGUAGE_SOURCE, source_line=source_line, expected=4)
    iso639_3 = values[0] or None
    iso639_2 = (
        tuple(part.strip().removesuffix("*") for part in values[1].split("/")) if values[1] else ()
    )
    iso639_1 = values[2] or None
    name = values[3].strip(" ")
    if (
        (iso639_3 and not _CODE_3.fullmatch(iso639_3))
        or (not iso639_3 and not iso639_2)
        or any(not _CODE_3.fullmatch(code) for code in iso639_2)
    ):
        raise _fail(ISO_LANGUAGE_SOURCE, source_line, "ISO 639-3/2 code is malformed")
    if iso639_1 and not _CODE_2.fullmatch(iso639_1):
        raise _fail(ISO_LANGUAGE_SOURCE, source_line, "ISO 639-1 code is malformed")
    if not name:
        raise _fail(ISO_LANGUAGE_SOURCE, source_line, "language name is empty")
    return IsoLanguageRecord(iso639_3, iso639_2, iso639_1, name, source_line)


def language_codes(records: Iterable[IsoLanguageRecord]) -> frozenset[str]:
    codes = set()
    for record in records:
        codes.update(record.iso639_2)
        if record.iso639_3:
            codes.add(record.iso639_3)
        if record.iso639_1:
            codes.add(record.iso639_1)
    return frozenset(codes)


_SCRIPT_PREFIXES = {
    "ARABIC": "Arab",
    "ARMENIAN": "Armn",
    "BENGALI": "Beng",
    "CJK": "Hani",
    "CYRILLIC": "Cyrl",
    "DEVANAGARI": "Deva",
    "GEORGIAN": "Geor",
    "GREEK": "Grek",
    "GUJARATI": "Gujr",
    "GURMUKHI": "Guru",
    "HANGUL": "Hang",
    "HEBREW": "Hebr",
    "HIRAGANA": "Hira",
    "KANNADA": "Knda",
    "KATAKANA": "Kana",
    "LAO": "Laoo",
    "LATIN": "Latn",
    "MALAYALAM": "Mlym",
    "MYANMAR": "Mymr",
    "SINHALA": "Sinh",
    "TAMIL": "Taml",
    "TELUGU": "Telu",
    "THAI": "Thai",
    "TIBETAN": "Tibt",
}


def detect_script(value: str) -> str | None:
    scripts = set()
    for character in unicodedata.normalize("NFC", value):
        if not character.isalpha():
            continue
        name = unicodedata.name(character, "")
        script = next(
            (code for prefix, code in _SCRIPT_PREFIXES.items() if name.startswith(prefix)), None
        )
        if script:
            scripts.add(script)
    if scripts <= {"Hani", "Hira", "Kana"} and len(scripts) > 1:
        return "Jpan"
    if scripts <= {"Hani", "Hang"} and len(scripts) > 1:
        return "Kore"
    return next(iter(scripts)) if len(scripts) == 1 else None


def _period_date(raw: str | None, *, start: bool) -> date | None:
    if raw is None or not _PERIOD.fullmatch(raw):
        return None
    compact = raw.replace("-", "")
    try:
        if len(compact) == 4:
            return date(int(compact), 1 if start else 12, 1 if start else 31)
        if len(compact) == 6:
            year, month = int(compact[:4]), int(compact[4:])
            if start:
                return date(year, month, 1)
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            return date.fromordinal(next_month.toordinal() - 1)
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:]))
    except ValueError:
        return None


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def alternate_name_rejection(
    record: AlternateNameRecord,
    *,
    known_language_codes: frozenset[str],
    as_of: date,
) -> str | None:
    """Return the first fail-closed source-level normalization rejection."""
    language = record.language_tag.split("-", 1)[0] if record.language_tag else None
    if "empty-source-name" in record.anomalies:
        return "empty-source-name"
    if record.language_tag in NON_LANGUAGE_NAMESPACES:
        return "non-language-namespace"
    if language and language not in known_language_codes:
        return "unknown-language"
    if record.historic:
        return "historic-name"
    start = _period_date(record.valid_from, start=True)
    end = _period_date(record.valid_to, start=False)
    if (record.valid_from and start is None) or (record.valid_to and end is None):
        return "unparseable-period"
    if start and as_of < start:
        return "not-yet-valid"
    if end and as_of > end:
        return "expired-name"
    if any(item in {"edge-ascii-space", "provider-del-c1-codepoint"} for item in record.anomalies):
        return "unsafe-source-name"
    return None


def select_names(
    *,
    geoname_id: int,
    source_name: str,
    records: Iterable[AlternateNameRecord],
    known_language_codes: frozenset[str],
    as_of: date,
) -> NameSelection:
    """Keep the provider canonical name and deterministically select safe alternates."""
    canonical_value = unicodedata.normalize("NFC", source_name)
    if not canonical_value or canonical_value != canonical_value.strip(" "):
        raise ValueError("source canonical name is empty or has edge whitespace")
    canonical = NameVariant(canonical_value, None, detect_script(canonical_value))
    selected: dict[str, tuple[tuple[object, ...], AlternateNameRecord]] = {}
    rejections: Counter[str] = Counter()
    for record in records:
        if record.geoname_id != geoname_id:
            raise ValueError("alternate row belongs to a different GeoNames place")
        language = record.language_tag.split("-", 1)[0] if record.language_tag else None
        rejection = alternate_name_rejection(
            record,
            known_language_codes=known_language_codes,
            as_of=as_of,
        )
        if rejection:
            rejections[rejection] += 1
            continue
        key = _name_key(record.name)
        if key == _name_key(canonical_value):
            rejections["duplicate-name"] += 1
            continue
        rank = (
            not record.preferred,
            not record.short,
            record.colloquial,
            language or "",
            key,
            record.alternate_name_id,
        )
        prior = selected.get(key)
        if prior is None or rank < prior[0]:
            if prior is not None:
                rejections["duplicate-name"] += 1
            selected[key] = (rank, record)
        else:
            rejections["duplicate-name"] += 1
    selected_records = tuple(record for _, record in sorted(selected.values()))
    alternates = tuple(record.as_name_variant() for record in selected_records)
    return NameSelection(
        canonical,
        alternates,
        selected_records,
        tuple(sorted(rejections.items())),
    )


def load_normalization_policy(path: Path) -> Mapping[str, object]:
    """Load the exact v2 policy and reject code/config semantic drift."""
    document = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schemaVersion": 1,
        "policyVersion": NORMALIZATION_POLICY_VERSION,
        "sourceSnapshot": "2026-08-10",
        "inclusion": {
            "featureClass": "P",
            "featureCodes": [
                "PPL",
                "PPLA",
                "PPLA2",
                "PPLA3",
                "PPLA4",
                "PPLA5",
                "PPLC",
                "PPLF",
                "PPLG",
                "PPLL",
                "PPLR",
            ],
            "countryCodeRequired": True,
            "coordinates": "finite-wgs84",
            "population": {"minimum": 0, "nullAllowed": True, "zeroAllowed": True},
            "supportPredicate": "covers",
            "spatialRule": "versioned-geometry-not-bounding-box",
            "transcontinentalRule": "support-geometry-only",
        },
        "canonicalName": {
            "source": "allCountries.name",
            "alternatePromotion": False,
            "unicodeNormalization": "NFC",
            "script": "unicode-script-detection-v1",
        },
        "alternateNames": {
            "source": "alternateNamesV2.txt",
            "languageMetadata": "iso-languagecodes.txt",
            "iso639ThreeOnlyMetadata": "accept",
            "excludedNamespaces": sorted(NON_LANGUAGE_NAMESPACES),
            "historic": "exclude",
            "temporalRule": "snapshot-date-within-inclusive-period",
            "unparseablePeriod": "exclude",
            "unknownLanguage": "exclude",
            "emptySourceName": "exclude",
            "colloquial": "include-noncanonical",
            "ordering": [
                "preferred-desc",
                "short-desc",
                "colloquial-asc",
                "language-asc",
                "nfc-casefold-name-asc",
                "alternate-name-id-asc",
            ],
        },
        "deduplication": {
            "placeIdentity": "geonames-id",
            "nameKey": "unicode-nfc-casefold",
            "crossPlaceMerge": False,
            "canonicalWins": True,
        },
        "geography": {"status": "selected-scope-approximation", "publicationEligible": False},
    }
    if document != expected:
        raise ValueError("normalization policy differs from the implemented v2 contract")
    return document
