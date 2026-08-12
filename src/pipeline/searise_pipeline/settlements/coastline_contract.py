"""Closed contract for the immutable settlement shoreline source and method."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from searise_pipeline.sources.registry import RegistryError, load_registry

_PIPELINE_ROOT = Path(__file__).parents[2]
_DEFAULT_SCHEMA = _PIPELINE_ROOT / "settlements/shoreline-distance-policy-v1.schema.json"


class CoastlineContractError(ValueError):
    """The shoreline source, method, or claim boundary is invalid."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def quantize_distance_meters(distance: float) -> int:
    """Mirror DuckDB's reviewed DOUBLE-to-BIGINT nearest-half-to-even cast."""
    if type(distance) not in (int, float):
        raise CoastlineContractError("shoreline distance must be a finite number")
    value = float(distance)
    if not math.isfinite(value) or value < 0:
        raise CoastlineContractError("shoreline distance must be finite and non-negative")
    return round(value)


def load_coastline_policy(
    path: Path,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Load the closed v1 shoreline policy without broadening its claims."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads((schema_path or _DEFAULT_SCHEMA).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoastlineContractError(f"cannot read shoreline policy: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda item: list(item.path),
    )
    if errors:
        raise CoastlineContractError(
            "invalid shoreline policy: " + "; ".join(_schema_error(error) for error in errors)
        )
    asset_ids = [item["assetId"] for item in document["source"]["assets"]]
    if asset_ids != document["recipe"]["sourceAssetOrder"]:
        raise CoastlineContractError("shoreline source assets are not in canonical order")
    if len(set(asset_ids)) != len(asset_ids):
        raise CoastlineContractError("shoreline source asset IDs must be unique")
    return document


def _raw_coastline_source(source_lock_path: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    if sha256_file(source_lock_path) != policy["sourceLock"]["sha256"]:
        raise CoastlineContractError("shoreline source-lock checksum mismatch")
    try:
        load_registry(source_lock_path)
        document = json.loads(source_lock_path.read_text(encoding="utf-8"))
    except (RegistryError, OSError, json.JSONDecodeError) as exc:
        raise CoastlineContractError(f"invalid shoreline source lock: {exc}") from exc
    sources = document["sources"]
    if len(sources) != 1:
        raise CoastlineContractError("shoreline source lock must contain exactly one source")
    source = sources[0]
    if (source["id"], source["version"]) != (
        policy["source"]["sourceId"],
        policy["source"]["registryVersion"],
    ):
        raise CoastlineContractError("shoreline source registry identity mismatch")
    rights = {
        key: source["licence"][key]
        for key in ("name", "url", "spdx", "attribution", "redistributionStatus")
    }
    if rights != policy["rights"]:
        raise CoastlineContractError("shoreline Natural Earth rights mismatch")
    return source


def validate_coastline_sources(
    source_lock_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Bind the scoped registry, archive identities, members, versions, and rights."""
    source = _raw_coastline_source(source_lock_path, policy)
    locked_assets = {item["id"]: item for item in source["assets"]}
    policy_assets = {item["assetId"]: item for item in policy["source"]["assets"]}
    expected_ids = policy["recipe"]["sourceAssetOrder"]
    if list(locked_assets) != expected_ids or list(policy_assets) != expected_ids:
        raise CoastlineContractError("shoreline source asset set or order changed")
    for asset_id in expected_ids:
        locked = locked_assets[asset_id]
        bound = policy_assets[asset_id]
        if locked["resolvedVersion"] != bound["registryVersion"]:
            raise CoastlineContractError(f"{asset_id} registry version mismatch")
        if locked.get("nativeVersion") != bound["nativeVersion"]:
            raise CoastlineContractError(f"{asset_id} native version mismatch")
        if (locked["byteSize"], locked["sha256"]) != (
            bound["archiveByteSize"],
            bound["archiveSha256"],
        ):
            raise CoastlineContractError(f"{asset_id} archive identity mismatch")
        members = locked.get("members", [])
        if [member["path"] for member in members] != bound["memberPaths"]:
            raise CoastlineContractError(f"{asset_id} archive member paths changed")
        if sha256_bytes(canonical_json_bytes(members)) != bound["memberInventorySha256"]:
            raise CoastlineContractError(f"{asset_id} archive member inventory mismatch")
        if any(member.get("nativeVersion") != bound["nativeVersion"] for member in members):
            raise CoastlineContractError(f"{asset_id} member native version mismatch")
    return locked_assets
