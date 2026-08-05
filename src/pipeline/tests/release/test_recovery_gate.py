"""Test the exact two-stage Phase 0 recovery disposition."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import searise_pipeline.release.gate as gate_module
from searise_pipeline.release.evidence import binding_sha256
from searise_pipeline.release.gate import evaluate_recovery_gate, finalize_recovery_gate
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import contract

BUILD_CHECKS = {
    "sourceArchiveAndMembersVerified": True,
    "sourceContentSeal": True,
    "completeScenarioHorizonMatrix": True,
    "nonAllNodataLayers": True,
    "cogStructureAndValues": True,
    "sourceGridIdentity": True,
    "geoparquetSchemaAndValues": True,
    "pmtilesStructureAndProperties": True,
    "crossArtifactSemanticParity": True,
    "lookupGoldenParity": True,
    "licenceNoticeAndAttribution": True,
    "artifactBudgets": True,
}
REPRODUCIBILITY = {
    "status": "passed",
    "independentEnvironmentCount": 2,
    "maximumScientificValueDifferenceMillimetres": 0,
    "validIdSetDifference": 0,
    "byteIdentityWithinPinnedToolchain": True,
}
DELIVERY = {
    "status": "passed",
    "fullCleanBuildDurationSeconds": 20,
    "browserHeapBytes": 8 * 1024 * 1024,
    "rangeRequestCount": 4,
    "coldTransferBytes": 128 * 1024,
    "lookupP95Milliseconds": 2,
}
BINDING = {
    "releaseId": "candidate-v1",
    "releaseContractId": "ar6-europe-regional-release-v1",
    "manifestSha256": "a" * 64,
    "buildReceiptSha256": "b" * 64,
    "buildEvidenceSha256": "c" * 64,
    "sourceReceiptSha256": "d" * 64,
    "artifactHashes": {"analysis/value.tif": "e" * 64},
    "candidateFileHashes": {"manifest.json": "a" * 64},
    "sourceRevision": "f" * 40,
    "environmentIdentity": {"buildRunId": "test"},
}


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def _promotion_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    release = contract()
    contract_sha = hashlib.sha256(
        (
            json.dumps(
                release, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    candidate = tmp_path / "candidate"
    _write_json(
        candidate / "source-receipt.json",
        {"releaseContractSha256": contract_sha},
    )
    _write_json(
        candidate / "build-evidence.json",
        {"releaseId": BINDING["releaseId"], "checks": BUILD_CHECKS},
    )
    owner = {
        "releaseId": BINDING["releaseId"],
        "approvedBy": "artemsemdev",
        "decision": "approved",
    }
    integration = {
        "releaseId": BINDING["releaseId"],
        "finalIntegrationMergedToMaster": True,
        "repository": "artemsemdev/SeaRise-Europe",
        "baseBranch": "master",
        "mergeCommitSha": "1" * 40,
        "implementationCommitSha": BINDING["sourceRevision"],
        "pullRequest": 123,
    }
    owner_path = tmp_path / "owner.json"
    integration_path = tmp_path / "integration.json"
    _write_json(owner_path, owner)
    _write_json(integration_path, integration)
    promotion = {
        "schemaVersion": 1,
        "releaseId": BINDING["releaseId"],
        "releaseContractSha256": contract_sha,
        "candidateBindingSha256": binding_sha256(BINDING),
        "ownerEvidenceSha256": gate_module.sha256(owner_path),
        "integrationMergeEvidenceSha256": gate_module.sha256(integration_path),
        "repository": "artemsemdev/SeaRise-Europe",
        "baseBranch": "master",
    }
    monkeypatch.setattr(gate_module, "candidate_binding", lambda _: BINDING)
    return (
        release,
        candidate,
        owner,
        integration,
        promotion,
        owner_path,
        integration_path,
    )


def test_complete_automation_passes_but_owner_and_master_control_unlock() -> None:
    approved = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
    )
    merged = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
        final_integration_merged_to_master=True,
    )

    assert approved["automatedValidation"] == "passed"
    assert approved["releaseDisposition"] == "approved"
    assert approved["phase1Unlocked"] is False
    assert merged["phase1Unlocked"] is True


def test_missing_external_evidence_stays_pending_owner() -> None:
    gate = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=None,
        delivery_report=None,
    )

    assert gate["automatedValidation"] == "pending"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["blockers"] == [
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
        "projectOwnerReleaseDecision",
        "finalIntegrationMergedToMaster",
    ]


def test_owner_cannot_approve_while_external_evidence_is_missing() -> None:
    gate = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=None,
        delivery_report=None,
        owner_decision="approved",
    )

    assert gate["automatedValidation"] == "pending"
    assert gate["releaseDisposition"] == "blocked"
    assert gate["phase1Unlocked"] is False


def test_present_failed_report_is_failed_even_when_other_report_is_missing() -> None:
    gate = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report={**REPRODUCIBILITY, "status": "failed"},
        delivery_report=None,
    )

    assert gate["automatedValidation"] == "failed"
    assert gate["releaseDisposition"] == "blocked"


def test_unverified_fixture_and_all_nodata_layer_fail_automation() -> None:
    fixture_checks = {
        **BUILD_CHECKS,
        "sourceArchiveAndMembersVerified": False,
        "nonAllNodataLayers": False,
    }
    gate = evaluate_recovery_gate(
        {"releaseId": "fixture-v1", "checks": fixture_checks},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
    )

    assert gate["automatedValidation"] == "failed"
    assert gate["releaseDisposition"] == "blocked"
    assert gate["blockers"][:2] == [
        "sourceArchiveAndMembersVerified",
        "nonAllNodataLayers",
    ]


def test_project_owner_can_explicitly_reject_a_complete_candidate() -> None:
    gate = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="rejected",
    )

    assert gate["automatedValidation"] == "passed"
    assert gate["releaseDisposition"] == "rejected"
    assert gate["phase1Unlocked"] is False


def test_promotion_rejects_owner_mapping_that_differs_from_hashed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _promotion_inputs(tmp_path, monkeypatch)
    release, candidate, owner, integration, promotion, owner_path, integration_path = (
        inputs
    )

    with pytest.raises(ScienceContractError, match="mappings differ"):
        finalize_recovery_gate(
            candidate,
            contract=release,
            reproducibility_report={**REPRODUCIBILITY, "candidates": [BINDING]},
            delivery_report={**DELIVERY, "candidate": BINDING},
            owner_evidence={**owner, "decision": "rejected"},
            integration_evidence=integration,
            promotion_record=promotion,
            owner_evidence_path=owner_path,
            integration_evidence_path=integration_path,
            repository_root=tmp_path,
        )


def test_promotion_rejects_unrelated_historical_master_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _promotion_inputs(tmp_path, monkeypatch)
    release, candidate, owner, integration, promotion, owner_path, integration_path = (
        inputs
    )

    def fake_run(command, **_kwargs):
        if "config" in command:
            return subprocess.CompletedProcess(command, 0, stdout=(
                "https://github.com/artemsemdev/SeaRise-Europe.git\n"
            ))
        if "merge-base" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(gate_module.subprocess, "run", fake_run)
    with pytest.raises(ScienceContractError, match="not present on.*master ancestry"):
        finalize_recovery_gate(
            candidate,
            contract=release,
            reproducibility_report={**REPRODUCIBILITY, "candidates": [BINDING]},
            delivery_report={**DELIVERY, "candidate": BINDING},
            owner_evidence=owner,
            integration_evidence=integration,
            promotion_record=promotion,
            owner_evidence_path=owner_path,
            integration_evidence_path=integration_path,
            repository_root=tmp_path,
        )
