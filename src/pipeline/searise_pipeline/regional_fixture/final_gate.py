"""Explicit Phase 0.9 decision guard for scientific release and Phase 1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from ..science.contracts import ScienceContractError

SCENARIOS = ("ssp1-26", "ssp2-45", "ssp5-85")
HORIZONS = (2030, 2050, 2100)
REQUIRED_REVIEW_KEYS = (
    "scientificData",
    "dataLicence",
    "productScope",
    "connectivity",
    "engineering",
    "crossEnvironment",
    "goldenVectors",
)


class FinalScientificGateBlocked(RuntimeError):
    """Phase 1 or scientific publication was attempted without final approval."""


def _schema_path() -> Path:
    return Path(__file__).parents[2] / "science" / "phase-0-9-gate.schema.json"


def _format_error(error: Any) -> str:
    location = ".".join(str(item) for item in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_final_gate(
    document: Mapping[str, Any], schema_path: Path | None = None
) -> None:
    """Validate the final decision and its non-negotiable unlock invariants."""
    path = schema_path or _schema_path()
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.9 gate schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda item: list(item.path),
    )
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ScienceContractError(f"Invalid Phase 0.9 gate: {details}")

    summary = document["attemptSummary"]
    if summary["completedCombinations"] + summary["blockedCombinations"] != 9:
        raise ScienceContractError("Invalid Phase 0.9 gate: attempt counts do not total nine")
    reviews_approved = all(
        document["reviews"][key]["status"] == "approved"
        for key in REQUIRED_REVIEW_KEYS
    )
    approval_complete = (
        document["decision"] == "approved"
        and not document["blockerIds"]
        and document["attemptEvidence"]["status"] == "completed"
        and summary["completedCombinations"] == 9
        and summary["blockedCombinations"] == 0
        and reviews_approved
    )
    if bool(document["phase1"]["unlocked"]) != approval_complete:
        raise ScienceContractError(
            "Invalid Phase 0.9 gate: Phase 1 unlock differs from explicit approval evidence"
        )


def canonical_final_gate_bytes(document: Mapping[str, Any]) -> bytes:
    """Return stable bytes for a validated final-gate decision."""
    validate_final_gate(document)
    try:
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ScienceContractError(f"Phase 0.9 gate is not canonical JSON: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def load_final_gate(path: Path) -> Mapping[str, Any]:
    """Read and validate one checked-in Phase 0.9 decision."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.9 gate: {exc}") from exc
    if not isinstance(document, dict):
        raise ScienceContractError("Phase 0.9 gate must be an object")
    validate_final_gate(document)
    return document


def verify_attempt_evidence(document: Mapping[str, Any], repo_root: Path) -> Mapping[str, Any]:
    """Verify the bound attempt bytes and all nine fail-closed combinations."""
    validate_final_gate(document)
    binding = document["attemptEvidence"]
    path = repo_root / binding["path"]
    try:
        payload = path.read_bytes()
        evidence = json.loads(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.9 attempt evidence: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != binding["sha256"]:
        raise ScienceContractError("Phase 0.9 attempt evidence checksum mismatch")
    if not isinstance(evidence, dict):
        raise ScienceContractError("Phase 0.9 attempt evidence must be an object")

    attempts = evidence.get("attempts", [])
    combinations = {(item.get("scenario"), item.get("horizon")) for item in attempts}
    expected = {(scenario, horizon) for scenario in SCENARIOS for horizon in HORIZONS}
    if len(attempts) != 9 or combinations != expected:
        raise ScienceContractError("Phase 0.9 evidence does not contain nine exact combinations")
    blocker_ids = list(document["blockerIds"])
    for attempt in attempts:
        if (
            attempt.get("status") != "blocked-before-array"
            or attempt.get("failureReasons") != blocker_ids
            or attempt.get("emittedScientificClassValues") != []
            or attempt.get("artifacts") != []
        ):
            raise ScienceContractError("Phase 0.9 attempt did not fail closed")
    return evidence


def assert_phase_1_unlocked(document: Mapping[str, Any]) -> None:
    """Require the explicit approved final decision; automation alone is insufficient."""
    validate_final_gate(document)
    if document["decision"] != "approved" or not document["phase1"]["unlocked"]:
        blockers = ", ".join(str(item) for item in document["blockerIds"])
        raise FinalScientificGateBlocked(
            f"Phase 0.9 decision is {document['decision']}; Phase 1 remains blocked: {blockers}"
        )
