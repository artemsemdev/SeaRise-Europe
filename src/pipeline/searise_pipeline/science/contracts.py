"""Load scientific decisions without inferring missing semantics."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]


class ScienceContractError(ValueError):
    """A scientific contract is absent, invalid, or not approved for use."""


_CANONICAL_UNCERTAINTY_TERMS = {
    "sla-l4-mapping": ("constant", "bounded-conditionally"),
    "mdt-formal-mapping": ("per-cell", "bounded-conditionally"),
    "temporal-weighting": ("exact-zero", "inapplicable"),
    "reference-period-completeness": ("exact-zero", "inapplicable"),
    "horizontal-interpolation": ("exact-zero", "inapplicable"),
    "coastal-sla-representativeness": ("unbounded", "unbounded"),
    "geoid-evaluator-disagreement": ("unbounded", "unbounded"),
    "dem-random-error": ("per-cell", "bounded-conditionally"),
    "dem-absolute-systematic-envelope": ("constant", "bounded-conditionally"),
    "dem-edit-fill": ("unbounded", "unbounded"),
    "dsm-to-bare-earth-representation": ("unbounded", "unbounded"),
    "water-mask": ("exact-zero", "inapplicable"),
    "terrain-void": ("unbounded", "unbounded"),
    "coastline-representation": ("unbounded", "unbounded"),
    "effective-resolution": ("unbounded", "unbounded"),
}


@dataclass(frozen=True)
class ScienceContracts:
    """The complete scientific decision documents used by a build."""

    source_semantics: Mapping[str, Any]
    projection_contract: Mapping[str, Any]
    geography_rules: Mapping[str, Any]
    vertical_methodology: Mapping[str, Any]
    terrain_decision: Mapping[str, Any]
    final_gate: Mapping[str, Any]
    uncertainty_budget: Mapping[str, Any] | None = None


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
    if not isinstance(document, dict):
        raise ScienceContractError(f"Invalid {name} contract: document must be an object")
    return document


def load_science_contracts(contract_dir: Path | None = None) -> ScienceContracts:
    """Load every versioned contract after validating its complete schema."""
    root = contract_dir or _default_contract_dir()
    uncertainty_budget = _load_document("coastal-uncertainty-budget", root)
    _validate_uncertainty_budget(uncertainty_budget)
    return ScienceContracts(
        source_semantics=_load_document("source-semantics", root),
        projection_contract=_load_document("ar6-projection-contract", root),
        geography_rules=_load_document("geography-rules", root),
        vertical_methodology=_load_document("vertical-methodology", root),
        uncertainty_budget=uncertainty_budget,
        terrain_decision=_load_document("terrain-decision", root),
        final_gate=_load_document("phase-0-9-gate", root),
    )


def _validate_uncertainty_budget(budget: Mapping[str, Any]) -> None:
    """Reject semantic weakening that JSON Schema cannot express concisely."""
    terms = budget["terms"]
    by_id = {term["id"]: term for term in terms}
    if len(by_id) != len(terms):
        raise ScienceContractError("Invalid uncertainty budget: duplicate term id")

    canonical_ids = set(_CANONICAL_UNCERTAINTY_TERMS)
    actual_ids = set(by_id)
    if actual_ids != canonical_ids:
        raise ScienceContractError(
            "Invalid uncertainty budget: canonical terms differ; "
            f"missing={sorted(canonical_ids - actual_ids)}, "
            f"unexpected={sorted(actual_ids - canonical_ids)}"
        )

    required = set(budget["eligibility"]["requiredBoundTermIds"])
    expected_required = {
        term_id
        for term_id, (_, status) in _CANONICAL_UNCERTAINTY_TERMS.items()
        if status != "inapplicable"
    }
    if required != expected_required:
        raise ScienceContractError(
            "Invalid uncertainty budget: required bound terms differ from canonical set"
        )

    declared_unbounded = set(budget["eligibility"]["unboundedTermIds"])
    expected_unbounded = {
        term_id
        for term_id, (_, status) in _CANONICAL_UNCERTAINTY_TERMS.items()
        if status == "unbounded"
    }
    if declared_unbounded != expected_unbounded:
        raise ScienceContractError(
            "Invalid uncertainty budget: declared unbounded terms differ from canonical set"
        )

    for term_id, term in by_id.items():
        numeric = term["numeric"]
        expected_kind, expected_status = _CANONICAL_UNCERTAINTY_TERMS[term_id]
        if (numeric["kind"], term["status"]) != (expected_kind, expected_status):
            raise ScienceContractError(
                f"Invalid uncertainty budget: {term_id} kind/status differs "
                "from canonical semantics"
            )
        if term["unsupportedOutcome"] != "DataUnavailable":
            raise ScienceContractError(
                f"Invalid uncertainty budget: {term_id} must fail closed when unsupported"
            )
        value = numeric["value"]
        if expected_kind == "constant":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ScienceContractError(
                    f"Invalid uncertainty budget: bounded constant {term_id} "
                    "must be positive and finite"
                )
        elif expected_kind == "exact-zero":
            if value != 0:
                raise ScienceContractError(
                    f"Invalid uncertainty budget: inapplicable term {term_id} must be exact zero"
                )
        elif value is not None:
            raise ScienceContractError(
                f"Invalid uncertainty budget: {expected_kind} term {term_id} "
                "must not declare a constant"
            )

    if expected_unbounded and budget["decision"]["recommendedDisposition"] != "rejected":
        raise ScienceContractError(
            "Invalid uncertainty budget: required unbounded terms must recommend rejection"
        )
    if budget["review"]["status"] == "pending-independent" and (
        budget["review"]["authoritativeDisposition"] != "pending"
        or budget["publicationGate"]["status"] != "blocked"
    ):
        raise ScienceContractError(
            "Invalid uncertainty budget: pending review must keep authoritative publication blocked"
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
    mapping = projection["mapping"]
    if not isinstance(mapping, dict):
        raise ScienceContractError("Projection mapping must be an object")
    return mapping


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


def verify_terrain_source_bindings(
    contracts: ScienceContracts,
    source_lock_path: Path,
) -> None:
    """Verify that terrain decision evidence names exact locked object sets."""
    try:
        source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read terrain source lock: {exc}") from exc

    sources = {source["id"]: source for source in source_lock["sources"]}
    for role, binding in contracts.terrain_decision["controlEvidence"].items():
        source = sources.get(binding["sourceId"])
        if source is None or source["version"] != binding["release"]:
            raise ScienceContractError(f"{role} terrain source identity mismatch")
        assets = {asset["id"]: asset for asset in source["assets"]}
        asset = assets.get(binding["assetId"])
        if asset is None or asset.get("availability") != "locked":
            raise ScienceContractError(f"{role} terrain control set is not locked")
        object_set = asset.get("objectSet", {})
        expected = {
            key: binding[key]
            for key in (
                "manifestPath",
                "manifestSha256",
                "payloadSha256",
                "objectCount",
                "totalByteSize",
            )
        }
        actual = {key: object_set.get(key) for key in expected}
        if actual != expected:
            raise ScienceContractError(f"{role} terrain manifest identity mismatch")


def assert_publication_ready(contracts: ScienceContracts) -> None:
    """Fail while any scientific or geography decision remains blocking."""
    blockers: list[str] = []
    documents = [
        contracts.source_semantics,
        contracts.geography_rules,
        contracts.vertical_methodology,
        contracts.terrain_decision,
    ]
    if contracts.uncertainty_budget is not None:
        documents.append(contracts.uncertainty_budget)
    for document in documents:
        gate = document["publicationGate"]
        if gate["status"] != "approved":
            blockers.extend(str(item) for item in gate["blockingDecisions"])
    final_gate = contracts.final_gate
    if final_gate["decision"] != "approved" or not final_gate["phase1"]["unlocked"]:
        blockers.extend(str(item) for item in final_gate["blockerIds"])
    if blockers:
        raise ScienceContractError("Scientific publication gate is blocked: " + ", ".join(blockers))
