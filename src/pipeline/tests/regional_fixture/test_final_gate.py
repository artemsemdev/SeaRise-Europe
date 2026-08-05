"""Unit tests for the explicit Phase 0.9 final-decision invariant."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.regional_fixture.final_gate import (
    FinalScientificGateBlocked,
    assert_phase_1_unlocked,
    canonical_final_gate_bytes,
    load_final_gate,
    validate_final_gate,
    verify_attempt_evidence,
)
from searise_pipeline.science.contracts import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
GATE_PATH = REPO_ROOT / "src/pipeline/science/phase-0-9-gate.json"


def _gate() -> dict:  # type: ignore[type-arg]
    return {
        "$schema": "./phase-0-9-gate.schema.json",
        "schemaVersion": 1,
        "gateId": "phase-0.9-final-scientific-gate",
        "issue": 85,
        "recordedAt": "2026-08-05",
        "methodologyId": "absolute-mean-water-surface-egm2008-interval-v1",
        "historicalEvidence": "docs/evidence/phase-0-regional-fixture.md",
        "decision": "blocked",
        "decisionReason": "Required scientific evidence is incomplete.",
        "attemptEvidence": {
            "path": "src/pipeline/science/evidence/phase-0-9-regional-attempt.json",
            "sha256": "a" * 64,
            "status": "preflight-blocked",
        },
        "attemptSummary": {
            "totalCombinations": 9,
            "completedCombinations": 0,
            "blockedCombinations": 9,
            "emittedScientificClassValues": [],
            "emittedArtifactCount": 0,
        },
        "reviews": {
            key: {"status": "pending", "evidence": None}
            for key in (
                "scientificData",
                "dataLicence",
                "productScope",
                "connectivity",
                "engineering",
                "crossEnvironment",
                "goldenVectors",
            )
        },
        "automation": {"status": "passed", "canAuthorizeDecision": False},
        "blockerIds": ["missing-review"],
        "deliverables": {
            "scientificArrays": [],
            "analysisCogs": [],
            "visualPmtiles": [],
            "geoParquet": [],
            "statistics": [],
            "receipts": [],
        },
        "phase1": {
            "status": "blocked",
            "unlocked": False,
            "nextDecision": "Supply the named evidence; #98 may re-evaluate the gate.",
        },
    }


def test_ci_success_cannot_authorize_a_blocked_gate() -> None:
    gate = _gate()

    validate_final_gate(gate)
    with pytest.raises(FinalScientificGateBlocked, match="Phase 1 remains blocked"):
        assert_phase_1_unlocked(gate)


def test_approval_requires_zero_blockers_completed_reviews_and_artifacts() -> None:
    gate = _gate()
    gate["decision"] = "approved"
    gate["phase1"] = {
        "status": "unlocked",
        "unlocked": True,
        "nextDecision": "Begin Phase 1.",
    }

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.9 gate"):
        validate_final_gate(gate)


def test_phase_1_unlock_must_equal_explicit_approval_evidence() -> None:
    gate = _gate()
    gate["phase1"]["unlocked"] = True
    gate["phase1"]["status"] = "unlocked"

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.9 gate"):
        validate_final_gate(gate)


def test_attempt_counts_must_total_all_nine_combinations() -> None:
    gate = _gate()
    gate["attemptSummary"]["blockedCombinations"] = 8

    with pytest.raises(ScienceContractError, match="attempt counts do not total nine"):
        validate_final_gate(gate)


def test_canonical_gate_is_mapping_order_independent() -> None:
    gate = _gate()
    reordered = dict(reversed(list(deepcopy(gate).items())))

    assert canonical_final_gate_bytes(gate) == canonical_final_gate_bytes(reordered)


def test_only_complete_explicit_approval_can_unlock_phase_1() -> None:
    gate = _gate()
    artifact = {"path": "artifact.bin", "sha256": "b" * 64}
    gate["decision"] = "approved"
    gate["attemptEvidence"]["status"] = "completed"
    gate["attemptSummary"] = {
        "totalCombinations": 9,
        "completedCombinations": 9,
        "blockedCombinations": 0,
        "emittedScientificClassValues": [0, 1],
        "emittedArtifactCount": 21,
    }
    gate["reviews"] = {
        key: {"status": "approved", "evidence": f"reviews/{key}.json"}
        for key in gate["reviews"]
    }
    gate["blockerIds"] = []
    gate["deliverables"] = {
        "scientificArrays": [
            {"path": f"array-{index}.npy", "sha256": "b" * 64}
            for index in range(9)
        ],
        "analysisCogs": [
            {"path": f"cog-{index}.tif", "sha256": "b" * 64}
            for index in range(9)
        ],
        "visualPmtiles": [artifact],
        "geoParquet": [artifact],
        "statistics": [artifact],
        "receipts": [artifact],
    }
    gate["phase1"] = {
        "status": "unlocked",
        "unlocked": True,
        "nextDecision": "Begin Phase 1.",
    }

    validate_final_gate(gate)
    assert_phase_1_unlocked(gate)


def test_checked_in_gate_verifies_bound_attempt_and_stays_blocked() -> None:
    gate = load_final_gate(GATE_PATH)
    evidence = verify_attempt_evidence(gate, REPO_ROOT)

    assert gate["decision"] == "blocked"
    assert gate["automation"] == {"status": "passed", "canAuthorizeDecision": False}
    assert gate["attemptSummary"]["blockedCombinations"] == 9
    assert "#98 alone may re-evaluate" in gate["phase1"]["nextDecision"]
    assert gate["deliverables"] == {
        "scientificArrays": [],
        "analysisCogs": [],
        "visualPmtiles": [],
        "geoParquet": [],
        "statistics": [],
        "receipts": [],
    }
    assert len(evidence["attempts"]) == 9
    with pytest.raises(FinalScientificGateBlocked):
        assert_phase_1_unlocked(gate)
