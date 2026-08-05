"""Test the explicit Phase 0 recovery disposition."""

from __future__ import annotations

from searise_pipeline.release import evaluate_recovery_gate

from .test_source_fixture import contract

BUILD_CHECKS = {
    "sourceArchiveAndMembersVerified": True,
    "completeScenarioHorizonMatrix": True,
    "sourceGridIdentity": True,
    "cogStructureAndValues": True,
    "geoparquetSchemaAndValues": True,
    "pmtilesStructureAndProperties": True,
    "crossArtifactSemanticParity": True,
    "lookupGoldenParity": True,
    "licenceAndAttribution": True,
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
    "buildDurationSeconds": 20,
    "browserHeapBytes": 8 * 1024 * 1024,
    "rangeRequestCount": 4,
    "lookupP95Milliseconds": 2,
}


def test_complete_automated_evidence_is_approved_but_owner_still_controls_unlock() -> None:
    pending = evaluate_recovery_gate(
        {"checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
    )
    approved = evaluate_recovery_gate(
        {"checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
    )

    assert pending["disposition"] == "approved"
    assert pending["releaseDecision"] == "pending-owner"
    assert pending["phase1Unlocked"] is False
    assert approved["disposition"] == "approved"
    assert approved["phase1Unlocked"] is True


def test_missing_external_evidence_blocks_without_rejecting() -> None:
    gate = evaluate_recovery_gate(
        {"checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=None,
        delivery_report=None,
    )

    assert gate["disposition"] == "blocked"
    assert gate["blockingChecks"] == [
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
    ]
    assert gate["fallback"] == "do-not-publish-or-unlock-phase-1"


def test_unverified_fixture_cannot_satisfy_the_source_gate() -> None:
    fixture_checks = {**BUILD_CHECKS, "sourceArchiveAndMembersVerified": False}

    gate = evaluate_recovery_gate(
        {"checks": fixture_checks},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
    )

    assert gate["disposition"] == "blocked"
    assert gate["phase1Unlocked"] is False
    assert gate["blockingChecks"] == ["sourceArchiveAndMembersVerified"]


def test_project_owner_can_explicitly_reject_a_complete_candidate() -> None:
    gate = evaluate_recovery_gate(
        {"checks": BUILD_CHECKS},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="rejected",
    )

    assert gate["disposition"] == "rejected"
    assert gate["phase1Unlocked"] is False
