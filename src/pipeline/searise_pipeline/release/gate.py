"""Machine recovery gate for the AR6 regional release."""

from __future__ import annotations

from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError

_BUILD_CHECKS = (
    "sourceArchiveAndMembersVerified",
    "completeScenarioHorizonMatrix",
    "sourceGridIdentity",
    "cogStructureAndValues",
    "geoparquetSchemaAndValues",
    "pmtilesStructureAndProperties",
    "crossArtifactSemanticParity",
    "lookupGoldenParity",
    "licenceAndAttribution",
    "artifactBudgets",
)


def _report_check(
    report: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> bool:
    return report is not None and all(report.get(key) == value for key, value in expected.items())


def evaluate_recovery_gate(
    build_evidence: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    reproducibility_report: Mapping[str, Any] | None,
    delivery_report: Mapping[str, Any] | None,
    owner_decision: str = "pending-owner",
) -> Mapping[str, Any]:
    """Return exactly one fail-closed disposition without inferring approvals."""
    if owner_decision not in {"pending-owner", "approved", "rejected"}:
        raise ScienceContractError("Unknown project-owner release decision")
    build_checks = build_evidence.get("checks", {})
    checks = {check: build_checks.get(check) is True for check in _BUILD_CHECKS}
    tolerance = contract["reproducibility"]
    checks["crossEnvironmentReproducibility"] = (
        reproducibility_report is not None
        and reproducibility_report.get("status") == "passed"
        and reproducibility_report.get("independentEnvironmentCount", 0)
        >= tolerance["minimumIndependentEnvironments"]
        and reproducibility_report.get("maximumScientificValueDifferenceMillimetres")
        == tolerance["scientificValueToleranceMillimetres"]
        and reproducibility_report.get("validIdSetDifference") == tolerance["validIdSetDifference"]
        and reproducibility_report.get("byteIdentityWithinPinnedToolchain") is True
    )
    budgets = contract["budgets"]
    checks["deliveryMeasurements"] = (
        _report_check(delivery_report, {"status": "passed"})
        and delivery_report.get("buildDurationSeconds", float("inf"))
        <= budgets["buildDurationSeconds"]
        and delivery_report.get("browserHeapBytes", float("inf")) <= budgets["browserHeapBytes"]
        and delivery_report.get("rangeRequestCount", float("inf")) <= budgets["rangeRequestCount"]
        and delivery_report.get("lookupP95Milliseconds", float("inf"))
        <= budgets["lookupP95Milliseconds"]
    )
    blockers = [name for name, passed in checks.items() if not passed]
    if build_evidence.get("rejected") is True or owner_decision == "rejected":
        disposition = "rejected"
    elif not blockers:
        disposition = "approved"
    else:
        disposition = "blocked"
    phase_1_unlocked = disposition == "approved" and owner_decision == "approved"
    return {
        "schemaVersion": 1,
        "gateId": "phase-0r-ar6-regional-release-v1",
        "issue": 110,
        "scientificDisposition": contract["scientificDisposition"],
        "disposition": disposition,
        "automatedEvidence": "passed" if not blockers else "incomplete-or-failed",
        "releaseDecision": owner_decision,
        "phase1Unlocked": phase_1_unlocked,
        "checks": checks,
        "blockingChecks": blockers,
        "fallback": None if disposition == "approved" else "do-not-publish-or-unlock-phase-1",
    }
