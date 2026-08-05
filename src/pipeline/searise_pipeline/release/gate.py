"""Non-authoritative machine gate for the AR6 regional release."""

from __future__ import annotations

import math
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError

_BUILD_CHECKS = (
    "sourceArchiveAndMembersVerified",
    "sourceContentSeal",
    "completeScenarioHorizonMatrix",
    "nonAllNodataLayers",
    "cogStructureAndValues",
    "sourceGridIdentity",
    "geoparquetSchemaAndValues",
    "pmtilesStructureAndProperties",
    "crossArtifactSemanticParity",
    "lookupGoldenParity",
    "licenceAndAttribution",
    "artifactBudgets",
)


def _exact_non_negative_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _reproducibility_passed(
    report: Mapping[str, Any] | None,
    tolerance: Mapping[str, Any],
) -> bool:
    return (
        report is not None
        and report.get("status") == "passed"
        and type(report.get("independentEnvironmentCount")) is int
        and report["independentEnvironmentCount"]
        >= tolerance["minimumIndependentEnvironments"]
        and type(report.get("maximumScientificValueDifferenceMillimetres")) is int
        and report["maximumScientificValueDifferenceMillimetres"]
        == tolerance["scientificValueToleranceMillimetres"]
        and type(report.get("validIdSetDifference")) is int
        and report["validIdSetDifference"] == tolerance["validIdSetDifference"]
        and report.get("byteIdentityWithinPinnedToolchain") is True
    )


def _delivery_passed(
    report: Mapping[str, Any] | None,
    budgets: Mapping[str, Any],
) -> bool:
    if report is None or report.get("status") != "passed":
        return False
    measurements = (
        ("fullCleanBuildDurationSeconds", "buildDurationSeconds"),
        ("browserHeapBytes", "browserHeapBytes"),
        ("rangeRequestCount", "rangeRequestCount"),
        ("coldTransferBytes", "coldTransferBytes"),
        ("lookupP95Milliseconds", "lookupP95Milliseconds"),
    )
    return all(
        _exact_non_negative_number(report.get(report_key))
        and report[report_key] <= budgets[budget_key]
        for report_key, budget_key in measurements
    )


def evaluate_recovery_gate(
    build_evidence: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    reproducibility_report: Mapping[str, Any] | None,
    delivery_report: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Evaluate automation without accepting or inferring release authority."""
    build_checks = build_evidence.get("checks")
    if not isinstance(build_checks, Mapping):
        raise ScienceContractError("Build evidence checks must be an object")
    checks = {check: build_checks.get(check) is True for check in _BUILD_CHECKS}
    checks["crossEnvironmentReproducibility"] = _reproducibility_passed(
        reproducibility_report,
        contract["reproducibility"],
    )
    checks["deliveryMeasurements"] = _delivery_passed(
        delivery_report,
        contract["budgets"],
    )
    failed_checks = [name for name, passed in checks.items() if not passed]
    missing_external = reproducibility_report is None or delivery_report is None
    supplied_external_failed = (
        reproducibility_report is not None
        and not checks["crossEnvironmentReproducibility"]
    ) or (delivery_report is not None and not checks["deliveryMeasurements"])
    if any(not checks[name] for name in _BUILD_CHECKS) or supplied_external_failed:
        automated_validation = "failed"
    elif missing_external:
        automated_validation = "pending"
    else:
        automated_validation = "passed"

    return {
        "schemaVersion": 1,
        "gateId": "phase-0r-ar6-regional-release-v1",
        "issue": 110,
        "releaseId": build_evidence.get("releaseId"),
        "scientificDisposition": contract["scientificDisposition"],
        "automatedValidation": automated_validation,
        "releaseDisposition": "pending-owner",
        "phase1Unlocked": False,
        "checks": checks,
        "blockingChecks": failed_checks,
        "fallback": "do-not-publish-or-unlock-phase-1",
    }
