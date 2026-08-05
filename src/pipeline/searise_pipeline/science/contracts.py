"""Load scientific decisions without inferring missing semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]


class ScienceContractError(ValueError):
    """A scientific contract is absent, invalid, or not approved for use."""


@dataclass(frozen=True)
class ScienceContracts:
    """The source and geography decision documents used by a build."""

    source_semantics: Mapping[str, Any]
    geography_rules: Mapping[str, Any]
    vertical_methodology: Mapping[str, Any]


def _default_contract_dir() -> Path:
    return Path(__file__).parents[2] / "science"


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def _load_document(name: str, contract_dir: Path) -> Mapping[str, Any]:
    document_path = contract_dir / f"{name}.json"
    schema_path = contract_dir / f"{name}.schema.json"
    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read {name} contract: {exc}") from exc

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ScienceContractError(f"Invalid {name} contract: {details}")
    return document


def load_science_contracts(contract_dir: Path | None = None) -> ScienceContracts:
    """Load both versioned contracts after validating their complete schemas."""
    root = contract_dir or _default_contract_dir()
    return ScienceContracts(
        source_semantics=_load_document("source-semantics", root),
        geography_rules=_load_document("geography-rules", root),
        vertical_methodology=_load_document("vertical-methodology", root),
    )


def projection_mapping(
    contracts: ScienceContracts,
    source_id: str,
    version: str,
) -> Mapping[str, Any]:
    """Return the sole approved mapping, rejecting any unknown source version."""
    projection = contracts.source_semantics["projection"]
    if source_id != projection["sourceId"] or version != projection["version"]:
        raise ScienceContractError(
            f"No projection mapping for {source_id}/{version}; "
            f"expected {projection['sourceId']}/{projection['version']}"
        )
    return projection["mapping"]


def verify_geometry_assets(contracts: ScienceContracts, repo_root: Path) -> None:
    """Verify that geometry bytes match the versions named in the contract."""
    for key in ("support", "coastal"):
        entry = contracts.geography_rules[key]
        path = repo_root / entry["path"]
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ScienceContractError(f"Cannot read {key} geometry: {exc}") from exc
        if digest != entry["sha256"]:
            raise ScienceContractError(
                f"{key} geometry checksum mismatch: {digest} != {entry['sha256']}"
            )


def assert_publication_ready(contracts: ScienceContracts) -> None:
    """Fail while any scientific or geography decision remains blocking."""
    blockers: list[str] = []
    for document in (
        contracts.source_semantics,
        contracts.geography_rules,
        contracts.vertical_methodology,
    ):
        gate = document["publicationGate"]
        if gate["status"] != "approved":
            blockers.extend(str(item) for item in gate["blockingDecisions"])
    if blockers:
        raise ScienceContractError(
            "Scientific publication gate is blocked: " + ", ".join(blockers)
        )
