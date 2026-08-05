"""Build and validate the immutable Phase 0.14 scientific no-go record."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from ..science.contracts import ScienceContractError
from .final_gate import FinalScientificGateBlocked

SCENARIOS = ("ssp1-26", "ssp2-45", "ssp5-85")
HORIZONS = (2030, 2050, 2100)
FINAL_STOP_REASONS = (
    "automated-methodology-recommendation-rejected",
    "cell-level-vertical-uncertainty-unbounded",
    "independent-reviews-pending",
)
DEPENDENCY_ISSUES = (94, 95, 96, 97)
DEPENDENCY_SPECS: Mapping[int, Mapping[str, str]] = {
    94: {
        "path": "src/pipeline/science/evidence/geoid-evaluator-validation.json",
        "reasonCode": "independent-geoid-validation-pending",
    },
    95: {
        "path": "src/pipeline/science/coastal-uncertainty-budget.json",
        "reasonCode": "cell-level-vertical-uncertainty-unbounded",
    },
    96: {
        "path": "src/pipeline/science/evidence/phase-0-12-basin-controls.json",
        "reasonCode": "vertical-goldens-and-review-pending",
    },
    97: {
        "path": "src/pipeline/science/scope-connectivity-review.json",
        "reasonCode": "independent-scope-connectivity-review-pending",
    },
}
HISTORICAL_PATHS = (
    "src/pipeline/science/phase-0-9-gate.json",
    "src/pipeline/science/evidence/phase-0-9-regional-attempt.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dependency_bindings(repo_root: Path) -> list[Mapping[str, Any]]:
    """Bind integrated evidence or retain its exact expected path as a draft slot."""
    records: list[Mapping[str, Any]] = []
    for issue in DEPENDENCY_ISSUES:
        spec = DEPENDENCY_SPECS[issue]
        relative_path = spec["path"]
        path = repo_root / relative_path
        if path.is_file():
            binding: Mapping[str, Any] = {
                "status": "bound",
                "expectedPath": relative_path,
                "path": relative_path,
                "sha256": _sha256(path),
            }
        else:
            binding = {
                "status": "pending",
                "expectedPath": relative_path,
                "path": None,
                "sha256": None,
            }
        records.append(
            {
                "issue": issue,
                "disposition": "blocked",
                "reasonCode": spec["reasonCode"],
                "binding": binding,
            }
        )
    return records


def _stopped_attempt(
    scenario: str, horizon: int, reason_codes: tuple[str, ...]
) -> Mapping[str, Any]:
    return {
        "scenario": scenario,
        "horizon": horizon,
        "status": "stopped-before-array",
        "failureStage": "scientific-preflight",
        "reasonCodes": list(reason_codes),
        "scientificClassValues": [],
        "artifacts": [],
        "statistics": None,
    }


def build_phase_0_14_no_go(
    repo_root: Path,
    *,
    recorded_at: str = "2026-08-05",
) -> Mapping[str, Any]:
    """Build a draft or fully bound no-go record without opening source payloads."""
    dependency_records = dependency_bindings(repo_root)
    record_status = (
        "final"
        if all(item["binding"]["status"] == "bound" for item in dependency_records)
        else "draft"
    )
    stop_reasons = FINAL_STOP_REASONS
    if record_status == "draft":
        stop_reasons = FINAL_STOP_REASONS + ("dependency-evidence-bindings-incomplete",)
    return {
        "$schema": "./phase-0-14-gate.schema.json",
        "schemaVersion": 1,
        "gateId": "phase-0.14-final-scientific-no-go",
        "issue": 98,
        "recordStatus": record_status,
        "recordedAt": recorded_at,
        "historicalGateBindings": [
            {"path": path, "sha256": _sha256(repo_root / path), "immutable": True}
            for path in HISTORICAL_PATHS
        ],
        "dependencyBindings": dependency_records,
        "automatedMethodologyRecommendation": {
            "status": "complete",
            "authority": "automated-methodology-analysis",
            "disposition": "rejected",
        },
        "authoritativeScientificDisposition": "blocked",
        "phase0Disposition": "complete-with-no-go",
        "decisionReason": (
            "Automated analysis recommends rejecting the selected binary coastal-"
            "screening methodology because its required cell-level vertical uncertainty "
            "cannot be bounded from the pinned evidence. The authoritative scientific "
            "disposition remains blocked pending independent review."
        ),
        "shortCircuit": {
            "stage": "scientific-preflight",
            "triggerIssue": 95,
            "reasonCodes": list(stop_reasons),
            "sourcePayloadsOpened": False,
        },
        "attempts": [
            _stopped_attempt(scenario, horizon, stop_reasons)
            for scenario in SCENARIOS
            for horizon in HORIZONS
        ],
        "requiredReviews": {
            key: {"status": "pending", "evidence": None}
            for key in (
                "scientificData",
                "dataLicence",
                "productScope",
                "engineering",
                "crossEnvironment",
            )
        },
        "automation": {
            "status": "passed",
            "canApproveScience": False,
            "canActAsIndependentReviewer": False,
        },
        "deliverables": {
            "scientificArrays": [],
            "analysisCogs": [],
            "visualPmtiles": [],
            "geoParquet": [],
            "statistics": [],
            "releaseReceipts": [],
        },
        "phase1": {
            "status": "locked",
            "unlocked": False,
            "reason": (
                "Phase 0 completed with no-go; a newly scoped methodology and gate are "
                "required before Phase 1 can begin."
            ),
        },
    }


def _schema_path() -> Path:
    return Path(__file__).parents[2] / "science" / "phase-0-14-gate.schema.json"


def _error_message(error: Any) -> str:
    location = ".".join(str(item) for item in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_phase_0_14_no_go(
    document: Mapping[str, Any],
    schema_path: Path | None = None,
    *,
    require_final: bool = False,
) -> None:
    """Enforce the no-output and Phase 1 lock invariants beyond JSON Schema."""
    path = schema_path or _schema_path()
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.14 gate schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda item: list(item.path),
    )
    if errors:
        details = "; ".join(_error_message(error) for error in errors)
        raise ScienceContractError(f"Invalid Phase 0.14 gate: {details}")

    historical_paths = tuple(item["path"] for item in document["historicalGateBindings"])
    if historical_paths != HISTORICAL_PATHS:
        raise ScienceContractError("Invalid Phase 0.14 gate: historical Phase 0.9 bindings changed")
    dependencies = document["dependencyBindings"]
    if tuple(item["issue"] for item in dependencies) != DEPENDENCY_ISSUES:
        raise ScienceContractError("Invalid Phase 0.14 gate: dependency issues must be 94-97")
    for dependency in dependencies:
        issue = dependency["issue"]
        spec = DEPENDENCY_SPECS[issue]
        binding = dependency["binding"]
        if dependency["disposition"] != "blocked" or dependency["reasonCode"] != spec["reasonCode"]:
            raise ScienceContractError(
                f"Invalid Phase 0.14 gate: issue {issue} disposition/reason mismatch"
            )
        if binding["expectedPath"] != spec["path"]:
            raise ScienceContractError(
                f"Invalid Phase 0.14 gate: issue {issue} expected evidence path changed"
            )
        if binding["status"] == "bound" and binding["path"] != binding["expectedPath"]:
            raise ScienceContractError(
                f"Invalid Phase 0.14 gate: issue {issue} bound path is not the expected path"
            )

    bindings_complete = all(
        dependency["binding"]["status"] == "bound" for dependency in dependencies
    )
    if document["recordStatus"] == "final" and not bindings_complete:
        raise ScienceContractError(
            "Invalid Phase 0.14 gate: a final record requires all dependency evidence bound"
        )
    if document["recordStatus"] == "draft" and bindings_complete:
        raise ScienceContractError(
            "Invalid Phase 0.14 gate: a fully bound record cannot remain draft"
        )
    if require_final and document["recordStatus"] != "final":
        raise ScienceContractError(
            "Invalid Phase 0.14 gate: terminal checked-in evidence must be final"
        )

    expected_reasons = FINAL_STOP_REASONS
    if document["recordStatus"] == "draft":
        expected_reasons += ("dependency-evidence-bindings-incomplete",)
    if tuple(document["shortCircuit"]["reasonCodes"]) != expected_reasons:
        raise ScienceContractError("Invalid Phase 0.14 gate: short-circuit reasons changed")

    expected = {(scenario, horizon) for scenario in SCENARIOS for horizon in HORIZONS}
    attempts = document["attempts"]
    observed = {(item["scenario"], item["horizon"]) for item in attempts}
    if observed != expected or len(attempts) != len(expected):
        raise ScienceContractError("Invalid Phase 0.14 gate: expected exact 3x3 matrix")
    for attempt in attempts:
        if tuple(attempt["reasonCodes"]) != expected_reasons:
            raise ScienceContractError("Invalid Phase 0.14 gate: stop reasons changed")


def canonical_phase_0_14_no_go_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize a validated decision deterministically."""
    validate_phase_0_14_no_go(document, require_final=True)
    try:
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ScienceContractError(f"Phase 0.14 gate is not canonical JSON: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def load_phase_0_14_no_go(path: Path) -> Mapping[str, Any]:
    """Load and validate a checked-in Phase 0.14 decision."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.14 gate: {exc}") from exc
    if not isinstance(document, dict):
        raise ScienceContractError("Phase 0.14 gate must be an object")
    validate_phase_0_14_no_go(document, require_final=True)
    return document


def verify_phase_0_14_bindings(document: Mapping[str, Any], repo_root: Path) -> None:
    """Verify final evidence hashes and their blocked scientific semantics."""
    validate_phase_0_14_no_go(document, require_final=True)
    records = list(document["historicalGateBindings"])
    records.extend(item["binding"] for item in document["dependencyBindings"])
    for binding in records:
        path = repo_root / binding["path"]
        if not path.is_file() or _sha256(path) != binding["sha256"]:
            raise ScienceContractError(f"Phase 0.14 binding mismatch: {binding['path']}")

    for dependency in document["dependencyBindings"]:
        path = repo_root / dependency["binding"]["path"]
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScienceContractError(
                f"Cannot inspect Phase 0.14 dependency {dependency['issue']}: {exc}"
            ) from exc
        if not isinstance(evidence, dict):
            raise ScienceContractError(
                f"Phase 0.14 dependency {dependency['issue']} evidence must be an object"
            )
        if not _dependency_evidence_is_blocked(dependency["issue"], evidence):
            raise ScienceContractError(
                f"Phase 0.14 dependency {dependency['issue']} evidence contradicts "
                "the recorded blocked disposition"
            )


def _dependency_evidence_is_blocked(issue: int, evidence: Mapping[str, Any]) -> bool:
    if issue == 94:
        review = evidence.get("review", {})
        return (
            evidence.get("status") == "blocked"
            and review.get("independent") is False
            and review.get("disposition") == "pending"
        )
    if issue == 95:
        decision = evidence.get("decision", {})
        review = evidence.get("review", {})
        return (
            decision.get("authority") == "automated-methodology-analysis"
            and decision.get("recommendedDisposition") == "rejected"
            and evidence.get("publicationGate", {}).get("status") == "blocked"
            and review.get("authoritativeDisposition") == "pending"
        )
    if issue == 96:
        return (
            evidence.get("publicationGate", {}).get("status") == "blocked"
            and evidence.get("review", {}).get("status") == "pending-external"
        )
    if issue == 97:
        review = evidence.get("review", {})
        return (
            review.get("status") == "pending-independent-review"
            and review.get("approvalReady") is False
        )
    return False


def assert_phase_1_unlocked(document: Mapping[str, Any]) -> None:
    """Always reject Phase 1 for this versioned complete-with-no-go record."""
    validate_phase_0_14_no_go(document)
    raise FinalScientificGateBlocked(
        "Phase 0.14 completed with no-go; the scientific disposition is blocked and "
        "Phase 1 remains locked after an automated rejection recommendation"
    )
