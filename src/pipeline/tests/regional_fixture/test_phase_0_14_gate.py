"""Characterization tests for the Phase 0.14 complete-with-no-go decision."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.regional_fixture.final_gate import FinalScientificGateBlocked
from searise_pipeline.regional_fixture.phase_0_14_gate import (
    DEPENDENCY_ISSUES,
    DEPENDENCY_SPECS,
    FINAL_STOP_REASONS,
    HORIZONS,
    SCENARIOS,
    assert_phase_1_unlocked,
    build_phase_0_14_no_go,
    canonical_phase_0_14_no_go_bytes,
    load_phase_0_14_no_go,
    validate_phase_0_14_no_go,
    verify_phase_0_14_bindings,
)
from searise_pipeline.science.contracts import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
EVIDENCE_PATH = REPO_ROOT / "src/pipeline/science/evidence/phase-0-14-final-no-go.json"


def _gate() -> dict:  # type: ignore[type-arg]
    return dict(build_phase_0_14_no_go(REPO_ROOT))


def _write_json(root: Path, relative_path: str, document: dict) -> None:  # type: ignore[type-arg]
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _draft_root(tmp_path: Path) -> Path:
    _write_json(tmp_path, "src/pipeline/science/phase-0-9-gate.json", {})
    _write_json(
        tmp_path,
        "src/pipeline/science/evidence/phase-0-9-regional-attempt.json",
        {},
    )
    return tmp_path


def _final_root(tmp_path: Path) -> Path:
    _draft_root(tmp_path)
    evidence = {
        94: {
            "status": "blocked",
            "review": {"independent": False, "disposition": "pending"},
        },
        95: {
            "decision": {
                "authority": "automated-methodology-analysis",
                "recommendedDisposition": "rejected",
            },
            "publicationGate": {"status": "blocked"},
            "review": {"authoritativeDisposition": "pending"},
        },
        96: {
            "publicationGate": {"status": "blocked"},
            "review": {"status": "pending-external"},
        },
        97: {
            "review": {
                "status": "pending-independent-review",
                "approvalReady": False,
            }
        },
    }
    for issue, document in evidence.items():
        _write_json(tmp_path, DEPENDENCY_SPECS[issue]["path"], document)
    return tmp_path


def test_builder_separates_automated_rejection_from_blocked_disposition() -> None:
    gate = _gate()

    assert gate["recordStatus"] == "final"
    assert gate["phase0Disposition"] == "complete-with-no-go"
    assert gate["authoritativeScientificDisposition"] == "blocked"
    assert gate["automatedMethodologyRecommendation"] == {
        "status": "complete",
        "authority": "automated-methodology-analysis",
        "disposition": "rejected",
    }
    assert [item["issue"] for item in gate["dependencyBindings"]] == list(DEPENDENCY_ISSUES)
    assert all(item["disposition"] == "blocked" for item in gate["dependencyBindings"])
    assert all(
        item["binding"]
        == {
            "status": "bound",
            "expectedPath": DEPENDENCY_SPECS[item["issue"]]["path"],
            "path": DEPENDENCY_SPECS[item["issue"]]["path"],
            "sha256": item["binding"]["sha256"],
        }
        for item in gate["dependencyBindings"]
    )
    assert all(len(item["binding"]["sha256"]) == 64 for item in gate["dependencyBindings"])


def test_all_nine_combinations_stop_before_arrays_or_artifacts() -> None:
    gate = _gate()
    expected = {(scenario, horizon) for scenario in SCENARIOS for horizon in HORIZONS}

    assert {(item["scenario"], item["horizon"]) for item in gate["attempts"]} == expected
    assert gate["shortCircuit"]["sourcePayloadsOpened"] is False
    expected_reasons = list(FINAL_STOP_REASONS)
    assert all(value == [] for value in gate["deliverables"].values())
    for attempt in gate["attempts"]:
        assert attempt["status"] == "stopped-before-array"
        assert attempt["reasonCodes"] == expected_reasons
        assert attempt["scientificClassValues"] == []
        assert attempt["artifacts"] == []
        assert attempt["statistics"] is None


def test_no_go_cannot_unlock_phase_1_or_use_automation_as_review() -> None:
    gate = _gate()

    assert gate["phase1"] == {
        "status": "locked",
        "unlocked": False,
        "reason": (
            "Phase 0 completed with no-go; a newly scoped methodology and gate are "
            "required before Phase 1 can begin."
        ),
    }
    assert gate["automation"]["canApproveScience"] is False
    assert gate["automation"]["canActAsIndependentReviewer"] is False
    with pytest.raises(FinalScientificGateBlocked, match="Phase 1 remains locked"):
        assert_phase_1_unlocked(gate)


def test_validator_rejects_an_authoritative_dependency_rejection() -> None:
    gate = deepcopy(_gate())
    gate["dependencyBindings"][1]["disposition"] = "rejected"

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.14 gate"):
        validate_phase_0_14_no_go(gate)


@pytest.mark.parametrize("disposition", ["approved", "rejected"])
def test_validator_rejects_an_authoritative_gate_decision(disposition: str) -> None:
    gate = deepcopy(_gate())
    gate["authoritativeScientificDisposition"] = disposition

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.14 gate"):
        validate_phase_0_14_no_go(gate)


@pytest.mark.parametrize("recommendation", ["approved", "pending"])
def test_validator_rejects_an_inconsistent_automated_recommendation(
    recommendation: str,
) -> None:
    gate = deepcopy(_gate())
    gate["automatedMethodologyRecommendation"]["disposition"] = recommendation

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.14 gate"):
        validate_phase_0_14_no_go(gate)


def test_validator_rejects_a_missing_matrix_member() -> None:
    gate = deepcopy(_gate())
    gate["attempts"] = gate["attempts"][:-1]

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.14 gate"):
        validate_phase_0_14_no_go(gate)

    gate = deepcopy(_gate())
    gate["requiredReviews"]["scientificData"]["evidence"] = "invented-review.json"
    with pytest.raises(ScienceContractError, match="Invalid Phase 0.14 gate"):
        validate_phase_0_14_no_go(gate)


def test_validator_rejects_changed_historical_binding_or_fabricated_review() -> None:
    gate = deepcopy(_gate())
    gate["historicalGateBindings"][0]["path"] = "replacement.json"
    with pytest.raises(ScienceContractError, match="historical Phase 0.9 bindings changed"):
        validate_phase_0_14_no_go(gate)

    gate = deepcopy(_gate())
    gate["requiredReviews"]["scientificData"] = {
        "status": "approved",
        "evidence": "invented-review.json",
    }
    with pytest.raises(ScienceContractError, match="Invalid Phase 0.14 gate"):
        validate_phase_0_14_no_go(gate)


def test_pending_dependencies_cannot_validate_as_terminal_evidence(tmp_path: Path) -> None:
    gate = build_phase_0_14_no_go(_draft_root(tmp_path))

    with pytest.raises(ScienceContractError, match="terminal checked-in evidence must be final"):
        canonical_phase_0_14_no_go_bytes(gate)
    with pytest.raises(ScienceContractError, match="terminal checked-in evidence must be final"):
        verify_phase_0_14_bindings(gate, tmp_path)


def test_final_record_binds_and_verifies_all_dependency_evidence(tmp_path: Path) -> None:
    root = _final_root(tmp_path)
    gate = build_phase_0_14_no_go(root)

    assert gate["recordStatus"] == "final"
    assert all(item["binding"]["status"] == "bound" for item in gate["dependencyBindings"])
    assert gate["shortCircuit"]["reasonCodes"] == list(FINAL_STOP_REASONS)
    verify_phase_0_14_bindings(gate, root)
    assert canonical_phase_0_14_no_go_bytes(gate).endswith(b"\n")


def test_final_record_rejects_pending_or_unbound_dependency(tmp_path: Path) -> None:
    gate = deepcopy(build_phase_0_14_no_go(_final_root(tmp_path)))
    gate["dependencyBindings"][0]["binding"] = {
        "status": "pending",
        "expectedPath": DEPENDENCY_SPECS[94]["path"],
        "path": None,
        "sha256": None,
    }

    with pytest.raises(ScienceContractError, match="final record requires all dependency"):
        validate_phase_0_14_no_go(gate)


def test_validator_rejects_a_bound_unexpected_dependency_path(tmp_path: Path) -> None:
    gate = deepcopy(build_phase_0_14_no_go(_final_root(tmp_path)))
    gate["dependencyBindings"][0]["binding"]["path"] = DEPENDENCY_SPECS[95]["path"]

    with pytest.raises(ScienceContractError, match="bound path is not the expected path"):
        validate_phase_0_14_no_go(gate)


def test_bound_dependency_semantics_must_match_blocked_disposition(tmp_path: Path) -> None:
    root = _final_root(tmp_path)
    _write_json(
        root,
        DEPENDENCY_SPECS[95]["path"],
        {
            "decision": {
                "authority": "independent-reviewer",
                "recommendedDisposition": "approved",
            },
            "publicationGate": {"status": "approved"},
            "review": {"authoritativeDisposition": "approved"},
        },
    )
    gate = build_phase_0_14_no_go(root)

    with pytest.raises(ScienceContractError, match="evidence contradicts"):
        verify_phase_0_14_bindings(gate, root)


def test_canonical_bytes_are_mapping_order_independent(tmp_path: Path) -> None:
    gate = build_phase_0_14_no_go(_final_root(tmp_path))
    reordered = dict(reversed(list(gate.items())))

    assert canonical_phase_0_14_no_go_bytes(gate) == canonical_phase_0_14_no_go_bytes(reordered)


def test_checked_final_evidence_rebuilds_byte_for_byte() -> None:
    rebuilt = build_phase_0_14_no_go(REPO_ROOT)

    assert rebuilt["recordStatus"] == "final"
    assert canonical_phase_0_14_no_go_bytes(rebuilt) == EVIDENCE_PATH.read_bytes()


def test_checked_final_evidence_loads_and_verifies_all_bindings() -> None:
    evidence = load_phase_0_14_no_go(EVIDENCE_PATH)

    verify_phase_0_14_bindings(evidence, REPO_ROOT)
    assert evidence["authoritativeScientificDisposition"] == "blocked"
    assert evidence["phase0Disposition"] == "complete-with-no-go"
    assert evidence["phase1"]["unlocked"] is False
