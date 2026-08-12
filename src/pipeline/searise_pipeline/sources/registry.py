"""Load and validate the audited source lock."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]


class RegistryError(ValueError):
    """The source lock is malformed or internally inconsistent."""


_GEONAMES_DUMP_ROOT = "https://download.geonames.org/export/dump/"
_GEONAMES_SETTLEMENT_SOURCE_ID = "geonames-settlement-catalogue"
_GEONAMES_SETTLEMENT_ASSETS = {
    "all-countries": (
        "allCountries.zip",
        "application/zip",
        ["settlement-place-records"],
    ),
    "alternate-names-v2": (
        "alternateNamesV2.zip",
        "application/zip",
        ["settlement-alternate-names", "settlement-language-metadata"],
    ),
    "admin1-codes-ascii": (
        "admin1CodesASCII.txt",
        "text/plain",
        ["settlement-admin1-context"],
    ),
    "format-readme": (
        "readme.txt",
        "text/plain",
        ["settlement-format-contract", "source-licence-notice"],
    ),
}
_GEONAMES_LICENCE = {
    "name": "Creative Commons Attribution 4.0 International",
    "url": "https://creativecommons.org/licenses/by/4.0/",
    "spdx": "CC-BY-4.0",
    "attribution": "GeoNames geographical database, https://www.geonames.org/.",
    "redistributionStatus": "approved",
    "reviewer": "SeaRise Europe maintainers",
    "reviewedAt": "2026-08-04",
    "requiredAcknowledgements": [
        "Retain GeoNames attribution and the CC BY 4.0 licence link in derived "
        "settlement indexes."
    ],
    "notes": (
        "The hash-locked readme binds the tab-delimited UTF-8 formats and licence "
        "notice. Daily download URLs are mutable; SHA-256 and byte size are the "
        "only byte-identity authority."
    ),
}
_GEONAMES_INSPECTION = {
    "inspectedAt": "2026-08-10",
    "method": (
        "Official HTTPS download, response metadata capture, complete SHA-256 "
        "stream, ZIP central-directory inspection, and exact member hashing"
    ),
    "evidenceRef": (
        "src/pipeline/sources/evidence/"
        "geonames-settlement-snapshot-20260810.json"
    ),
    "result": "verified",
}
_GEONAMES_ARCHIVE_MEMBERS = {
    "all-countries": [
        {
            "id": "all-countries-records",
            "path": "allCountries.txt",
            "role": "settlement-place-records",
            "byteSize": 1782635669,
            "compressedByteSize": 419923631,
            "crc32": "27133946",
            "sha256": (
                "4217bcadfce0d86d7f39244259dbbb96e5d1a610faedc3b4761bb96dcc492bf8"
            ),
        }
    ],
    "alternate-names-v2": [
        {
            "id": "alternate-name-records",
            "path": "alternateNamesV2.txt",
            "role": "settlement-alternate-names",
            "byteSize": 777625687,
            "compressedByteSize": 202448178,
            "crc32": "e311a5a6",
            "sha256": (
                "63453d348543a363bbd33a461c41e769de59d293c3fd62ca408eb3e2b0b47612"
            ),
        },
        {
            "id": "iso-language-codes",
            "path": "iso-languagecodes.txt",
            "role": "settlement-language-metadata",
            "byteSize": 137908,
            "compressedByteSize": 61908,
            "crc32": "4e1f14da",
            "sha256": (
                "cb0d34f492775deec8ec5713da6efa4463dad99b5e7ba2172bd094cfdcb76571"
            ),
        },
    ],
}


@dataclass(frozen=True)
class ObjectSet:
    contract: str
    manifest_path: str
    manifest_media_type: str
    manifest_byte_size: int
    manifest_sha256: str
    payload_sha256: str
    object_count: int
    total_byte_size: int
    key_prefix: str
    reference_start: str | None
    reference_end: str | None


@dataclass(frozen=True)
class ArchiveMember:
    id: str
    path: str
    role: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class Asset:
    id: str
    kind: str
    url: str
    resolved_url: str
    resolved_version: str
    media_type: str
    cache_path: str
    availability: str
    byte_size: int | None
    sha256: str | None
    roles: tuple[str, ...]
    members: tuple[ArchiveMember, ...]
    object_set: ObjectSet | None


@dataclass(frozen=True)
class Licence:
    name: str
    url: str
    spdx: str
    attribution: str
    redistribution_status: str
    reviewer: str | None
    reviewed_at: str | None
    required_acknowledgements: tuple[str, ...]


@dataclass(frozen=True)
class Coverage:
    region: str
    status: str
    roles: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Source:
    id: str
    selection_status: str
    publisher: str
    canonical_record: str
    version: str
    snapshot_date: str
    licence: Licence
    assets: tuple[Asset, ...]
    coverage: tuple[Coverage, ...]


@dataclass(frozen=True)
class Registry:
    sources: tuple[Source, ...]

    def targets(self, selectors: Iterable[str] = ()) -> tuple[tuple[Source, Asset], ...]:
        requested = tuple(selectors)
        if not requested:
            return tuple(
                (source, asset)
                for source in self.sources
                if source.selection_status == "selected"
                for asset in source.assets
            )

        source_map = {source.id: source for source in self.sources}
        targets: list[tuple[Source, Asset]] = []
        for selector in requested:
            source_id, separator, asset_id = selector.partition(":")
            source = source_map.get(source_id)
            if source is None:
                raise RegistryError(f"Unknown source selector: {source_id}")
            matches = (
                tuple(asset for asset in source.assets if asset.id == asset_id)
                if separator
                else source.assets
            )
            if not matches:
                raise RegistryError(f"Unknown asset selector: {selector}")
            targets.extend((source, asset) for asset in matches)
        return tuple(targets)

    def publication_issues(self) -> tuple[str, ...]:
        return tuple(
            f"{source.id}: redistribution status is {source.licence.redistribution_status}"
            for source in self.sources
            if source.selection_status == "selected"
            and source.licence.redistribution_status != "approved"
        )


def _schema_path(lock_path: Path) -> Path:
    sibling = lock_path.with_name("source-lock.schema.json")
    if sibling.exists():
        return sibling
    return Path(__file__).parents[2] / "sources" / "source-lock.schema.json"


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def _validate_geonames_source_contract(raw_source: dict[str, Any]) -> None:
    source_id = raw_source["id"]
    if source_id != _GEONAMES_SETTLEMENT_SOURCE_ID:
        return
    if (
        raw_source["selectionStatus"] != "selected"
        or raw_source["publisher"] != "GeoNames"
        or raw_source["canonicalRecord"] != _GEONAMES_DUMP_ROOT
        or raw_source["version"] != raw_source["snapshotDate"]
    ):
        raise RegistryError("GeoNames settlement snapshot identity is incomplete")
    if raw_source["licence"] != _GEONAMES_LICENCE:
        raise RegistryError("GeoNames settlement licence identity mismatch")
    if raw_source.get("inspection") != _GEONAMES_INSPECTION:
        raise RegistryError("GeoNames settlement inspection identity mismatch")
    assets = {asset["id"]: asset for asset in raw_source["assets"]}
    if set(assets) != set(_GEONAMES_SETTLEMENT_ASSETS):
        raise RegistryError("GeoNames settlement snapshot asset set is incomplete")
    for asset_id, (filename, media_type, roles) in _GEONAMES_SETTLEMENT_ASSETS.items():
        asset = assets[asset_id]
        expected_url = _GEONAMES_DUMP_ROOT + filename
        if (
            asset["kind"] != "file"
            or asset["availability"] != "locked"
            or asset["url"] != expected_url
            or asset["resolvedUrl"] != expected_url
            or asset["mediaType"] != media_type
            or asset["cachePath"] != filename
            or asset.get("roles") != roles
            or asset.get("members", [])
            != _GEONAMES_ARCHIVE_MEMBERS.get(asset_id, [])
        ):
            raise RegistryError(f"GeoNames settlement asset identity mismatch: {asset_id}")


def _manifest_path(lock_path: Path, relative_path: str) -> Path:
    root = lock_path.parent.resolve()
    path = (root / relative_path).resolve()
    if root not in path.parents:
        raise RegistryError(f"Object manifest escapes source-lock directory: {relative_path}")
    return path


def _parse_date(value: object, *, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise RegistryError(f"Invalid object manifest {field}: {value}") from exc


def _validate_monthly_rows(
    header: dict[str, Any], rows: list[dict[str, Any]], descriptor: ObjectSet
) -> None:
    if descriptor.reference_start is None or descriptor.reference_end is None:
        raise RegistryError("Monthly object manifest has no locked reference period")
    reference = header.get("referencePeriod")
    expected_reference = {
        "startInclusive": descriptor.reference_start,
        "endExclusive": descriptor.reference_end,
    }
    if reference != expected_reference:
        raise RegistryError("Monthly object manifest reference period mismatch")

    cursor = _parse_date(descriptor.reference_start, field="reference start")
    end = _parse_date(descriptor.reference_end, field="reference end")
    total_day_weight = 0
    for row in rows:
        start = _parse_date(row.get("periodStart"), field="periodStart")
        period_end = _parse_date(row.get("periodEndExclusive"), field="periodEndExclusive")
        if start != cursor or start.day != 1:
            raise RegistryError("Monthly object manifest contains a gap or unordered period")
        expected_end = (
            date(start.year + 1, 1, 1)
            if start.month == 12
            else date(start.year, start.month + 1, 1)
        )
        day_weight = row.get("dayWeight")
        if period_end != expected_end or day_weight != (expected_end - start).days:
            raise RegistryError("Monthly object manifest has an invalid calendar-day weight")
        total_day_weight += day_weight
        cursor = period_end
    if cursor != end:
        raise RegistryError("Monthly object manifest does not reach reference-period end")
    aggregation = header.get("aggregation")
    if not isinstance(aggregation, dict) or aggregation.get("totalDayWeight") != total_day_weight:
        raise RegistryError("Monthly object manifest total day weight mismatch")


def _validate_dem_rows(header: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if header.get("roles") != ["DEM", "EDM", "FLM", "HEM", "WBM"]:
        raise RegistryError("DEM control manifest must declare all mandatory layers")
    seen_controls: set[tuple[str, str]] = set()
    for row in rows:
        role = row.get("role")
        region = row.get("region")
        tile = row.get("tile")
        if role not in {"DEM", "EDM", "FLM", "HEM", "WBM"}:
            raise RegistryError("DEM control manifest has an unknown layer role")
        if not isinstance(region, str) or not region or not isinstance(tile, str) or not tile:
            raise RegistryError("DEM control manifest omits region or tile")
        control = (region, role)
        if control in seen_controls:
            raise RegistryError(f"Duplicate DEM control layer: {region}:{role}")
        seen_controls.add(control)


def _validate_object_manifest(
    lock_path: Path, source_id: str, source_version: str, asset: Asset
) -> None:
    descriptor = asset.object_set
    if descriptor is None:
        raise RegistryError(f"Object-set asset has no descriptor: {source_id}:{asset.id}")
    path = _manifest_path(lock_path, descriptor.manifest_path)
    try:
        compressed = path.read_bytes()
    except OSError as exc:
        raise RegistryError(
            f"Cannot read object manifest {descriptor.manifest_path}: {exc}"
        ) from exc
    if len(compressed) != descriptor.manifest_byte_size:
        raise RegistryError(f"Object manifest byte size mismatch: {source_id}:{asset.id}")
    if hashlib.sha256(compressed).hexdigest() != descriptor.manifest_sha256:
        raise RegistryError(f"Object manifest SHA-256 mismatch: {source_id}:{asset.id}")
    try:
        payload = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise RegistryError(f"Cannot decompress object manifest: {source_id}:{asset.id}") from exc
    if hashlib.sha256(payload).hexdigest() != descriptor.payload_sha256:
        raise RegistryError(f"Object manifest payload SHA-256 mismatch: {source_id}:{asset.id}")

    try:
        records = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Invalid JSONL object manifest: {source_id}:{asset.id}") from exc
    if not records or records[0].get("type") != "manifest":
        raise RegistryError(f"Object manifest header is missing: {source_id}:{asset.id}")
    header, rows = records[0], records[1:]
    if header.get("schemaVersion") != 1 or header.get("datasetVersion") != source_version:
        raise RegistryError(f"Object manifest version mismatch: {source_id}:{asset.id}")
    if len(rows) != descriptor.object_count or header.get("objectCount") != len(rows):
        raise RegistryError(f"Object manifest count mismatch: {source_id}:{asset.id}")

    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    total_byte_size = 0
    for row in rows:
        key, url = row.get("key"), row.get("url")
        byte_size, sha256 = row.get("byteSize"), row.get("sha256")
        if row.get("type") != "object" or not isinstance(key, str):
            raise RegistryError(f"Object manifest row is malformed: {source_id}:{asset.id}")
        expected_url = asset.resolved_url.rstrip("/") + "/" + key
        if not key.startswith(descriptor.key_prefix) or url != expected_url:
            raise RegistryError(f"Object manifest identity mismatch: {source_id}:{asset.id}")
        if key in seen_keys or url in seen_urls:
            raise RegistryError(f"Duplicate object manifest identity: {source_id}:{asset.id}")
        if not isinstance(byte_size, int) or byte_size < 1:
            raise RegistryError(f"Invalid object byte size: {source_id}:{asset.id}")
        if not isinstance(sha256, str) or re.fullmatch(r"[a-f0-9]{64}", sha256) is None:
            raise RegistryError(f"Invalid object SHA-256: {source_id}:{asset.id}")
        seen_keys.add(key)
        seen_urls.add(url)
        total_byte_size += byte_size
    if (
        total_byte_size != descriptor.total_byte_size
        or header.get("totalByteSize") != total_byte_size
    ):
        raise RegistryError(f"Object manifest total byte size mismatch: {source_id}:{asset.id}")

    if descriptor.contract == "monthly-series-v1":
        _validate_monthly_rows(header, rows, descriptor)
    elif descriptor.contract == "dem-control-set-v1":
        _validate_dem_rows(header, rows)
    else:  # guarded by JSON Schema, retained for fail-closed direct construction
        raise RegistryError(f"Unknown object manifest contract: {descriptor.contract}")


def load_registry(lock_path: Path) -> Registry:
    """Return a schema- and semantics-validated registry."""
    try:
        document = json.loads(lock_path.read_text(encoding="utf-8"))
        schema = json.loads(_schema_path(lock_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Cannot read source lock: {exc}") from exc

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        raise RegistryError("Invalid source lock: " + "; ".join(_format_error(e) for e in errors))

    seen_sources: set[str] = set()
    sources: list[Source] = []
    for raw_source in document["sources"]:
        source_id = raw_source["id"]
        if source_id in seen_sources:
            raise RegistryError(f"Duplicate source id: {source_id}")
        seen_sources.add(source_id)
        _validate_geonames_source_contract(raw_source)

        seen_assets: set[str] = set()
        assets: list[Asset] = []
        for raw_asset in raw_source["assets"]:
            asset_id = raw_asset["id"]
            if asset_id in seen_assets:
                raise RegistryError(f"Duplicate asset id: {source_id}:{asset_id}")
            if raw_asset["resolvedVersion"] != raw_source["version"]:
                raise RegistryError(
                    f"Resolved version mismatch for {source_id}:{asset_id}: "
                    f"{raw_asset['resolvedVersion']} != {raw_source['version']}"
                )
            seen_assets.add(asset_id)
            raw_object_set = raw_asset.get("objectSet")
            reference_period = raw_object_set.get("referencePeriod", {}) if raw_object_set else {}
            asset = Asset(
                id=asset_id,
                kind=raw_asset["kind"],
                url=raw_asset["url"],
                resolved_url=raw_asset["resolvedUrl"],
                resolved_version=raw_asset["resolvedVersion"],
                media_type=raw_asset["mediaType"].lower(),
                cache_path=raw_asset["cachePath"],
                availability=raw_asset["availability"],
                byte_size=raw_asset.get("byteSize"),
                sha256=raw_asset.get("sha256"),
                roles=tuple(raw_asset.get("roles", ())),
                members=tuple(
                    ArchiveMember(
                        id=member["id"],
                        path=member["path"],
                        role=member["role"],
                        byte_size=member["byteSize"],
                        sha256=member["sha256"],
                    )
                    for member in raw_asset.get("members", ())
                ),
                object_set=(
                    ObjectSet(
                        contract=raw_object_set["contract"],
                        manifest_path=raw_object_set["manifestPath"],
                        manifest_media_type=raw_object_set["manifestMediaType"],
                        manifest_byte_size=raw_object_set["manifestByteSize"],
                        manifest_sha256=raw_object_set["manifestSha256"],
                        payload_sha256=raw_object_set["payloadSha256"],
                        object_count=raw_object_set["objectCount"],
                        total_byte_size=raw_object_set["totalByteSize"],
                        key_prefix=raw_object_set["keyPrefix"],
                        reference_start=reference_period.get("startInclusive"),
                        reference_end=reference_period.get("endExclusive"),
                    )
                    if raw_object_set
                    else None
                ),
            )
            if asset.kind == "object-set":
                _validate_object_manifest(lock_path, source_id, raw_source["version"], asset)
            assets.append(asset)

        raw_licence = raw_source["licence"]
        sources.append(
            Source(
                id=source_id,
                selection_status=raw_source["selectionStatus"],
                publisher=raw_source["publisher"],
                canonical_record=raw_source["canonicalRecord"],
                version=raw_source["version"],
                snapshot_date=raw_source["snapshotDate"],
                licence=Licence(
                    name=raw_licence["name"],
                    url=raw_licence["url"],
                    spdx=raw_licence["spdx"],
                    attribution=raw_licence["attribution"],
                    redistribution_status=raw_licence["redistributionStatus"],
                    reviewer=raw_licence["reviewer"],
                    reviewed_at=raw_licence["reviewedAt"],
                    required_acknowledgements=tuple(raw_licence["requiredAcknowledgements"]),
                ),
                assets=tuple(assets),
                coverage=tuple(
                    Coverage(
                        region=item["region"],
                        status=item["status"],
                        roles=tuple(item["roles"]),
                        reason=item["reason"],
                    )
                    for item in raw_source.get("coverage", ())
                ),
            )
        )
    return Registry(tuple(sources))


def load_settlement_registry(lock_path: Path) -> Registry:
    """Return the isolated, complete Phase 1 settlement source registry."""
    registry = load_registry(lock_path)
    if [source.id for source in registry.sources] != [_GEONAMES_SETTLEMENT_SOURCE_ID]:
        raise RegistryError(
            "GeoNames Phase 1 production input must contain only the full settlement snapshot"
        )
    return registry
