"""Pure deterministic normalization of parsed GeoNames settlement records."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from .alternate_names import (
    ALTERNATE_NAMES_SOURCE,
    NORMALIZATION_POLICY_VERSION,
    AlternateNameRecord,
    NameVariant,
    select_names,
)
from .geonames import (
    ADMIN1_SOURCE,
    ALL_COUNTRIES_SOURCE,
    Admin1Record,
    GeoNameRecord,
    Lineage,
    SourceIdentity,
)

CATALOGUE_SNAPSHOT_DATE = date.fromisoformat(ALL_COUNTRIES_SOURCE.source_release)
CATALOGUE_POLICY_VERSION = "settlement-catalogue-v1"
CATALOGUE_POLICY_SHA256 = "cd850f85c6eac4627c8995f3d4497456a5d7975d1d3cf308604c604608fd3e8f"
INCLUDED_FEATURE_CODES = frozenset(
    {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLF", "PPLG", "PPLL", "PPLR"}
)
EXPLICITLY_EXCLUDED_FEATURE_CODES = frozenset({"PPLH", "PPLQ", "PPLW"})
REJECTION_PRECEDENCE = (
    "feature-class-not-populated-place",
    "feature-code-not-included",
    "country-code-missing",
    "invalid-coordinate",
    "negative-population",
    "unsafe-canonical-name",
)


class CatalogueNormalizationError(ValueError):
    """The parsed inputs cannot produce one unambiguous normalized catalogue."""


@dataclass(frozen=True)
class CataloguePlace:
    id: str
    source_spelling: str
    canonical_name: NameVariant
    ascii_name: str
    alternate_names: tuple[NameVariant, ...]
    country_code: str
    admin1_code: str | None
    admin1_name: str | None
    latitude: float
    longitude: float
    population: int | None
    feature_code: str
    source_updated_at: date
    lineage: tuple[Lineage, ...]


@dataclass(frozen=True)
class CatalogueRejection:
    place_id: str
    field: str
    reason: str
    observed_value: str | None
    lineage: Lineage


@dataclass(frozen=True)
class CatalogueContextNotice:
    place_id: str
    field: str
    reason: str
    observed_value: str
    lineage: Lineage


@dataclass(frozen=True)
class NormalizedCatalogue:
    snapshot_date: date
    catalogue_policy_version: str
    normalization_version: str
    places: tuple[CataloguePlace, ...]
    rejections: tuple[CatalogueRejection, ...]
    context_notices: tuple[CatalogueContextNotice, ...]
    context_notice_counts: tuple[tuple[str, int], ...]
    name_rejection_counts: tuple[tuple[str, int], ...]


def settlement_id(geoname_id: int) -> str:
    """Return the stable public identifier derived only from GeoNames identity."""
    if geoname_id < 1:
        raise CatalogueNormalizationError("GeoNames place id must be positive")
    return f"geonames:{geoname_id}"


def load_catalogue_policy(path: Path) -> Mapping[str, object]:
    """Load the immutable catalogue v1 bytes and reject code/policy drift."""
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOGUE_POLICY_SHA256:
        raise ValueError("catalogue policy bytes differ from reviewed v1")
    document = json.loads(raw)
    try:
        if (
            document["schemaVersion"] != 1
            or document["policyVersion"] != CATALOGUE_POLICY_VERSION
            or document["sourceSnapshot"] != CATALOGUE_SNAPSHOT_DATE.isoformat()
            or document["nameNormalizationPolicyVersion"] != NORMALIZATION_POLICY_VERSION
            or set(document["inclusion"]["featureCodes"]) != INCLUDED_FEATURE_CODES
            or set(document["inclusion"]["explicitlyExcludedFeatureCodes"])
            != EXPLICITLY_EXCLUDED_FEATURE_CODES
            or tuple(document["inclusion"]["rejectionPrecedence"]) != REJECTION_PRECEDENCE
        ):
            raise ValueError("catalogue policy differs from the implemented v1 contract")
    except (KeyError, TypeError) as exc:
        raise ValueError("catalogue policy is incomplete") from exc
    return document


def _unsafe_canonical_name(record: GeoNameRecord) -> bool:
    return (
        not record.name
        or record.name != record.name.strip()
        or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in record.name)
    )


def _place_rejection(record: GeoNameRecord) -> tuple[str, str, str | None] | None:
    invalid_coordinate = not (
        math.isfinite(record.latitude)
        and math.isfinite(record.longitude)
        and -90 <= record.latitude <= 90
        and -180 <= record.longitude <= 180
    )
    candidates = {
        "feature-class-not-populated-place": (
            "featureClass",
            record.feature_class,
        )
        if record.feature_class != "P"
        else None,
        "feature-code-not-included": ("featureCode", record.feature_code)
        if record.feature_code not in INCLUDED_FEATURE_CODES
        else None,
        "country-code-missing": ("countryCode", None) if record.country_code is None else None,
        "invalid-coordinate": (
            "location",
            f"{record.latitude!r},{record.longitude!r}",
        )
        if invalid_coordinate
        else None,
        "negative-population": ("population", str(record.population))
        if record.population is not None and record.population < 0
        else None,
        "unsafe-canonical-name": ("sourceSpelling", None)
        if _unsafe_canonical_name(record)
        else None,
    }
    for reason in REJECTION_PRECEDENCE:
        candidate = candidates[reason]
        if candidate is not None:
            field, value = candidate
            return field, reason, value
    return None


def _admin1_index(records: Iterable[Admin1Record]) -> dict[str, Admin1Record]:
    index: dict[str, Admin1Record] = {}
    for record in records:
        _validate_lineage("admin1", record.geoname_id, record.lineage, ADMIN1_SOURCE)
        if record.key in index:
            raise CatalogueNormalizationError(f"duplicate admin1 join key {record.key}")
        index[record.key] = record
    return index


def _place_index(records: Iterable[GeoNameRecord]) -> dict[int, GeoNameRecord]:
    index: dict[int, GeoNameRecord] = {}
    for record in records:
        _validate_lineage("place", record.geoname_id, record.lineage, ALL_COUNTRIES_SOURCE)
        if record.geoname_id in index:
            raise CatalogueNormalizationError(f"duplicate GeoNames place id {record.geoname_id}")
        index[record.geoname_id] = record
    return index


def _alternate_index(
    buckets: Mapping[int, Iterable[AlternateNameRecord]],
) -> dict[int, tuple[AlternateNameRecord, ...]]:
    index = {}
    seen_ids = set()
    for geoname_id, records in buckets.items():
        bucket = tuple(records)
        for record in bucket:
            _validate_lineage(
                "alternate-name",
                record.alternate_name_id,
                record.lineage,
                ALTERNATE_NAMES_SOURCE,
            )
            if record.geoname_id != geoname_id:
                raise CatalogueNormalizationError(
                    f"alternate-name bucket {geoname_id} contains place {record.geoname_id}"
                )
            if record.alternate_name_id in seen_ids:
                raise CatalogueNormalizationError(
                    f"duplicate alternateNameId {record.alternate_name_id}"
                )
            seen_ids.add(record.alternate_name_id)
        index[geoname_id] = bucket
    return index


def _validate_lineage(
    label: str,
    record_id: int,
    lineage: Lineage,
    identity: SourceIdentity,
) -> None:
    if (
        lineage
        != Lineage(
            identity.asset_id,
            identity.source_file,
            identity.source_release,
            lineage.source_line,
            record_id,
            identity.source_sha256,
        )
        or lineage.source_line < 1
    ):
        raise CatalogueNormalizationError(f"{label} lineage differs from the pinned source")


def normalize_catalogue(
    place_records: Iterable[GeoNameRecord],
    admin1_records: Iterable[Admin1Record],
    alternate_records_by_geoname_id: Mapping[int, Iterable[AlternateNameRecord]],
    *,
    known_language_codes: frozenset[str],
) -> NormalizedCatalogue:
    """Normalize parsed records without spatial classification or artifact I/O."""
    places_by_id = _place_index(place_records)
    admins_by_key = _admin1_index(admin1_records)
    alternates_by_id = _alternate_index(alternate_records_by_geoname_id)
    orphan_ids = sorted(set(alternates_by_id) - set(places_by_id))
    if orphan_ids:
        raise CatalogueNormalizationError(f"orphan alternate-name bucket {orphan_ids[0]}")
    places = []
    rejections = []
    notices = []
    name_rejections: Counter[str] = Counter()

    for geoname_id, record in sorted(places_by_id.items()):
        identifier = settlement_id(geoname_id)
        rejected = _place_rejection(record)
        if rejected is not None:
            field, reason, value = rejected
            rejections.append(CatalogueRejection(identifier, field, reason, value, record.lineage))
            continue

        admin = None
        if record.admin1_code is not None:
            admin_key = f"{record.country_code}.{record.admin1_code}"
            admin = admins_by_key.get(admin_key)
            if admin is None:
                notices.append(
                    CatalogueContextNotice(
                        identifier,
                        "admin1Code",
                        "admin1-code-unresolved",
                        admin_key,
                        record.lineage,
                    )
                )
        selection = select_names(
            geoname_id=geoname_id,
            source_name=record.name,
            records=alternates_by_id.get(geoname_id, ()),
            known_language_codes=known_language_codes,
            as_of=CATALOGUE_SNAPSHOT_DATE,
        )
        name_rejections.update(dict(selection.rejections))
        lineage = [record.lineage]
        if admin is not None:
            lineage.append(admin.lineage)
        lineage.extend(item.lineage for item in selection.selected_records)
        if len(lineage) != len(set(lineage)):
            raise CatalogueNormalizationError(f"duplicate lineage for {identifier}")
        assert record.country_code is not None and record.feature_code is not None
        places.append(
            CataloguePlace(
                id=identifier,
                source_spelling=record.name,
                canonical_name=selection.canonical,
                ascii_name=record.ascii_name,
                alternate_names=selection.alternates,
                country_code=record.country_code,
                admin1_code=record.admin1_code,
                admin1_name=admin.name if admin else None,
                latitude=record.latitude,
                longitude=record.longitude,
                population=record.population,
                feature_code=record.feature_code,
                source_updated_at=record.modification_date,
                lineage=tuple(lineage),
            )
        )

    notice_counts = Counter(item.reason for item in notices)
    return NormalizedCatalogue(
        snapshot_date=CATALOGUE_SNAPSHOT_DATE,
        catalogue_policy_version=CATALOGUE_POLICY_VERSION,
        normalization_version=NORMALIZATION_POLICY_VERSION,
        places=tuple(places),
        rejections=tuple(rejections),
        context_notices=tuple(notices),
        context_notice_counts=tuple(sorted(notice_counts.items())),
        name_rejection_counts=tuple(sorted(name_rejections.items())),
    )
