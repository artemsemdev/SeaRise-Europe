"""Fail-closed loading of pinned geoid evaluator evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from .contracts import ScienceContractError
from .uncertainty import UncertaintyTerm


def _science_dir() -> Path:
    return Path(__file__).parents[2] / "science"


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(document, dict):
        raise ScienceContractError(f"Invalid {label}: document must be an object")
    return document


def _validate(
    document: Mapping[str, Any], schema_path: Path, label: str
) -> None:
    schema = _read_object(schema_path, f"{label} schema")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ScienceContractError(f"Invalid {label}: {details}")


def load_geoid_evaluator_policy(path: Path | None = None) -> Mapping[str, Any]:
    """Load the exact evaluator policy without filling missing conventions."""
    policy_path = path or _science_dir() / "geoid-evaluator.json"
    document = _read_object(policy_path, "geoid evaluator policy")
    _validate(
        document,
        policy_path.with_name("geoid-evaluator.schema.json"),
        "geoid evaluator policy",
    )
    return document


def load_geoid_evaluator_evidence(
    path: Path | None = None,
    policy_path: Path | None = None,
) -> Mapping[str, Any]:
    """Load evidence and verify that it names the exact policy bytes."""
    evidence_path = path or _science_dir() / "evidence" / "geoid-evaluator-validation.json"
    resolved_policy_path = policy_path or _science_dir() / "geoid-evaluator.json"
    load_geoid_evaluator_policy(resolved_policy_path)
    document = _read_object(evidence_path, "geoid evaluator evidence")
    _validate(
        document,
        _science_dir() / "geoid-evaluator-evidence.schema.json",
        "geoid evaluator evidence",
    )
    try:
        policy_digest = hashlib.sha256(resolved_policy_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ScienceContractError(f"Cannot hash geoid evaluator policy: {exc}") from exc
    if document["policy"]["sha256"] != policy_digest:
        raise ScienceContractError("Geoid evaluator evidence policy checksum mismatch")
    return document


def canonical_geoid_evidence_bytes(evidence: Mapping[str, Any]) -> bytes:
    """Return stable JSON bytes after complete evidence validation."""
    _validate(
        evidence,
        _science_dir() / "geoid-evaluator-evidence.schema.json",
        "geoid evaluator evidence",
    )
    try:
        text = json.dumps(
            evidence,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ScienceContractError(
            f"Geoid evaluator evidence is not canonical JSON: {exc}"
        ) from exc
    return (text + "\n").encode("utf-8")


def geoid_evidence_sha256(evidence: Mapping[str, Any]) -> str:
    """Hash canonical evidence independently of source formatting."""
    return hashlib.sha256(canonical_geoid_evidence_bytes(evidence)).hexdigest()


def evaluator_disagreement_term(
    evidence: Mapping[str, Any], shape: tuple[int, ...]
) -> UncertaintyTerm:
    """Expose only a reviewed complete disagreement bound as uncertainty."""
    canonical_geoid_evidence_bytes(evidence)
    disagreement = evidence["evaluatorDisagreement"]
    bound = disagreement["boundMetres"]
    if evidence["status"] != "accepted" or disagreement["status"] != "bounded":
        bound_values = None
    elif not isinstance(bound, (int, float)):
        raise ScienceContractError("Accepted geoid evaluator evidence has no numeric bound")
    else:
        bound_values = np.full(shape, float(bound), dtype=np.float64)
    return UncertaintyTerm(
        id="geoid-evaluator-disagreement",
        component="baseline",
        bound_m=bound_values,
        units="m",
        provenance=(
            f"{evidence['evidenceId']}:status={evidence['status']};"
            f"comparison={disagreement['status']}"
        ),
        spatial_handling="uniform-reviewed-bound-over-geoid-correction-support",
        aggregation_rule="sum-absolute-bounds",
    )
