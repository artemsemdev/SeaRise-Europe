"""Test the non-authoritative Phase 0 recovery automation."""

from __future__ import annotations

import pytest

from searise_pipeline.release import evaluate_recovery_gate

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
    "fullCleanBuildDurationSeconds": 20,
    "browserHeapBytes": 8 * 1024 * 1024,
    "rangeRequestCount": 4,
    "coldTransferBytes": 128 * 1024,
    "lookupP95Milliseconds": 2,
}


def _evaluate(**overrides):
    arguments = {
        "contract": contract(),
        "reproducibility_report": REPRODUCIBILITY,
        "delivery_report": DELIVERY,
        **overrides,
    }
    return evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        **arguments,
    )


def test_complete_automation_cannot_approve_or_unlock() -> None:
    gate = _evaluate()

    assert gate["automatedValidation"] == "passed"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False
    assert gate["blockingChecks"] == []
    assert gate["fallback"] == "do-not-publish-or-unlock-phase-1"


@pytest.mark.parametrize(
    "authority_argument",
    [
        {"owner_decision": "approved"},
        {"final_integration_merged_to_master": True},
        {"phase1_unlocked": True},
    ],
)
def test_direct_callers_have_no_unlock_capable_arguments(authority_argument) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _evaluate(**authority_argument)


def test_missing_external_evidence_stays_pending() -> None:
    gate = _evaluate(reproducibility_report=None, delivery_report=None)

    assert gate["automatedValidation"] == "pending"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False
    assert gate["blockingChecks"] == [
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
    ]


def test_present_failed_report_fails_even_when_other_report_is_missing() -> None:
    gate = _evaluate(
        reproducibility_report={**REPRODUCIBILITY, "status": "failed"},
        delivery_report=None,
    )

    assert gate["automatedValidation"] == "failed"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False


def test_unverified_source_and_all_nodata_layer_fail_automation() -> None:
    checks = {
        **BUILD_CHECKS,
        "sourceArchiveAndMembersVerified": False,
        "nonAllNodataLayers": False,
    }
    gate = evaluate_recovery_gate(
        {"releaseId": "fixture-v1", "checks": checks},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
    )

    assert gate["automatedValidation"] == "failed"
    assert gate["blockingChecks"][:2] == [
        "sourceArchiveAndMembersVerified",
        "nonAllNodataLayers",
    ]
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False


@pytest.mark.parametrize(
    ("report_name", "field", "invalid_value"),
    [
        ("delivery", "browserHeapBytes", True),
        ("delivery", "lookupP95Milliseconds", float("nan")),
        ("delivery", "fullCleanBuildDurationSeconds", -1),
        ("reproducibility", "independentEnvironmentCount", True),
        ("reproducibility", "validIdSetDifference", 0.0),
    ],
)
def test_automation_rejects_coerced_or_invalid_metrics(
    report_name: str,
    field: str,
    invalid_value: object,
) -> None:
    reports = {
        "delivery_report": DELIVERY,
        "reproducibility_report": REPRODUCIBILITY,
    }
    key = f"{report_name}_report"
    reports[key] = {**reports[key], field: invalid_value}

    gate = _evaluate(**reports)

    assert gate["automatedValidation"] == "failed"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False


def test_delivery_transfer_budget_is_required() -> None:
    release = contract()
    over_budget = {
        **DELIVERY,
        "coldTransferBytes": release["budgets"]["coldTransferBytes"] + 1,
    }

    gate = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=release,
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=over_budget,
    )

    assert gate["checks"]["deliveryMeasurements"] is False
    assert gate["blockingChecks"] == ["deliveryMeasurements"]
