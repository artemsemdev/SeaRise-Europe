"""Load and validate the audited source lock."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]


class RegistryError(ValueError):
    """The source lock is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Asset:
    id: str
    url: str
    resolved_url: str
    resolved_version: str
    media_type: str
    cache_path: str
    availability: str
    byte_size: int | None
    sha256: str | None


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
class Source:
    id: str
    selection_status: str
    publisher: str
    canonical_record: str
    version: str
    snapshot_date: str
    licence: Licence
    assets: tuple[Asset, ...]


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
            f"{source.id}: redistribution status is "
            f"{source.licence.redistribution_status}"
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
            assets.append(
                Asset(
                    id=asset_id,
                    url=raw_asset["url"],
                    resolved_url=raw_asset["resolvedUrl"],
                    resolved_version=raw_asset["resolvedVersion"],
                    media_type=raw_asset["mediaType"].lower(),
                    cache_path=raw_asset["cachePath"],
                    availability=raw_asset["availability"],
                    byte_size=raw_asset.get("byteSize"),
                    sha256=raw_asset.get("sha256"),
                )
            )

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
                    required_acknowledgements=tuple(
                        raw_licence["requiredAcknowledgements"]
                    ),
                ),
                assets=tuple(assets),
            )
        )
    return Registry(tuple(sources))
