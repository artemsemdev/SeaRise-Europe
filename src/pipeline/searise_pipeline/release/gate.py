"""Two-stage, evidence-bound recovery gate for the AR6 regional release."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError

from .evidence import binding_sha256, candidate_binding, load_json, sha256

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
    "licenceNoticeAndAttribution",
    "artifactBudgets",
)


def _bound_report(
    report: Mapping[str, Any] | None,
    binding: Mapping[str, Any] | None,
    *,
    plural: bool,
) -> bool:
    if report is None:
        return False
    if binding is None:
        return True
    if plural:
        return binding in report.get("candidates", [])
    return report.get("candidate") == binding


def evaluate_recovery_gate(
    build_evidence: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    reproducibility_report: Mapping[str, Any] | None,
    delivery_report: Mapping[str, Any] | None,
    owner_decision: str = "pending-owner",
    final_integration_merged_to_master: bool = False,
    binding: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Return one exact fail-closed disposition without inferring owner approval."""
    if owner_decision not in {"pending-owner", "approved", "rejected"}:
        raise ScienceContractError("Unknown project-owner release decision")
    build_checks = build_evidence.get("checks", {})
    checks = {check: build_checks.get(check) is True for check in _BUILD_CHECKS}
    tolerance = contract["reproducibility"]
    checks["crossEnvironmentReproducibility"] = (
        _bound_report(reproducibility_report, binding, plural=True)
        and reproducibility_report.get("status") == "passed"
        and reproducibility_report.get("independentEnvironmentCount", 0)
        >= tolerance["minimumIndependentEnvironments"]
        and reproducibility_report.get("maximumScientificValueDifferenceMillimetres")
        == tolerance["scientificValueToleranceMillimetres"]
        and reproducibility_report.get("validIdSetDifference")
        == tolerance["validIdSetDifference"]
        and reproducibility_report.get("byteIdentityWithinPinnedToolchain") is True
    )
    budgets = contract["budgets"]
    checks["deliveryMeasurements"] = (
        _bound_report(delivery_report, binding, plural=False)
        and delivery_report.get("status") == "passed"
        and delivery_report.get("fullCleanBuildDurationSeconds", float("inf"))
        <= budgets["buildDurationSeconds"]
        and delivery_report.get("browserHeapBytes", float("inf"))
        <= budgets["browserHeapBytes"]
        and delivery_report.get("rangeRequestCount", float("inf"))
        <= budgets["rangeRequestCount"]
        and delivery_report.get("coldTransferBytes", float("inf"))
        <= budgets["coldTransferBytes"]
        and delivery_report.get("lookupP95Milliseconds", float("inf"))
        <= budgets["lookupP95Milliseconds"]
    )
    missing_external = reproducibility_report is None or delivery_report is None
    invalid_supplied_external = (
        reproducibility_report is not None and not checks["crossEnvironmentReproducibility"]
    ) or (delivery_report is not None and not checks["deliveryMeasurements"])
    failed = [name for name, passed in checks.items() if not passed]
    if any(not checks[name] for name in _BUILD_CHECKS):
        automated_validation = "failed"
    elif invalid_supplied_external:
        automated_validation = "failed"
    elif missing_external:
        automated_validation = "pending"
    else:
        automated_validation = "passed" if not failed else "failed"

    if owner_decision == "rejected":
        release_disposition = "rejected"
    elif automated_validation == "failed":
        release_disposition = "blocked"
    elif automated_validation == "pending":
        release_disposition = (
            "pending-owner" if owner_decision == "pending-owner" else "blocked"
        )
    elif owner_decision == "pending-owner":
        release_disposition = "pending-owner"
    else:
        release_disposition = "approved"
    blockers = failed
    if owner_decision == "pending-owner":
        blockers.append("projectOwnerReleaseDecision")
    if not final_integration_merged_to_master:
        blockers.append("finalIntegrationMergedToMaster")
    phase_1_unlocked = (
        automated_validation == "passed"
        and release_disposition == "approved"
        and final_integration_merged_to_master
    )
    return {
        "schemaVersion": 1,
        "gateId": "phase-0r-ar6-regional-release-v1",
        "issue": 110,
        "releaseId": build_evidence.get("releaseId"),
        "scientificDisposition": contract["scientificDisposition"],
        "automatedValidation": automated_validation,
        "releaseDisposition": release_disposition,
        "ownerDecision": owner_decision,
        "finalIntegrationMergedToMaster": final_integration_merged_to_master,
        "phase1Unlocked": phase_1_unlocked,
        "checks": checks,
        "blockers": blockers,
        "evidencePaths": {
            "build": "build-evidence.json",
            "delivery": "external:delivery-measurements.json",
            "reproducibility": "external:reproducibility.json",
            "source": "source-receipt.json",
            "ownerDecision": "external:owner-decision.json",
            "integration": "external:integration-merge.json",
        },
        "fallback": (
            None if phase_1_unlocked else "do-not-publish-or-unlock-phase-1"
        ),
    }


def finalize_recovery_gate(
    candidate: Path,
    *,
    contract: Mapping[str, Any],
    reproducibility_report: Mapping[str, Any],
    delivery_report: Mapping[str, Any],
    owner_evidence: Mapping[str, Any],
    integration_evidence: Mapping[str, Any],
    promotion_record: Mapping[str, Any],
    owner_evidence_path: Path,
    integration_evidence_path: Path,
    repository_root: Path,
) -> Mapping[str, Any]:
    """Finalize only evidence cryptographically bound to an existing candidate."""
    binding = candidate_binding(candidate)
    if (
        owner_evidence != load_json(owner_evidence_path)
        or integration_evidence != load_json(integration_evidence_path)
    ):
        raise ScienceContractError("Promotion evidence mappings differ from hashed files")
    source_receipt = load_json(candidate / "source-receipt.json")
    contract_digest = hashlib.sha256(
        (
            json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    expected_promotion = {
        "schemaVersion": 1,
        "releaseId": binding["releaseId"],
        "releaseContractSha256": source_receipt["releaseContractSha256"],
        "candidateBindingSha256": binding_sha256(binding),
        "ownerEvidenceSha256": sha256(owner_evidence_path),
        "integrationMergeEvidenceSha256": sha256(integration_evidence_path),
        "repository": "artemsemdev/SeaRise-Europe",
        "baseBranch": "master",
    }
    if (
        contract_digest != source_receipt["releaseContractSha256"]
        or promotion_record != expected_promotion
    ):
        raise ScienceContractError("Owner-controlled promotion record is invalid or detached")
    build_evidence = load_json(candidate / "build-evidence.json")
    if build_evidence.get("releaseId") != binding["releaseId"]:
        raise ScienceContractError("Build evidence belongs to another release")
    if (
        owner_evidence.get("releaseId") != binding["releaseId"]
        or owner_evidence.get("approvedBy") != "artemsemdev"
    ):
        raise ScienceContractError("Owner decision belongs to another release")
    if integration_evidence.get("releaseId") != binding["releaseId"]:
        raise ScienceContractError("Integration evidence belongs to another release")
    decision = owner_evidence.get("decision")
    merged = integration_evidence.get("finalIntegrationMergedToMaster")
    if (
        decision not in {"approved", "rejected"}
        or not isinstance(merged, bool)
        or integration_evidence.get("repository") != "artemsemdev/SeaRise-Europe"
        or integration_evidence.get("baseBranch") != "master"
        or not integration_evidence.get("mergeCommitSha")
        or integration_evidence.get("implementationCommitSha")
        != binding["sourceRevision"]
        or not isinstance(integration_evidence.get("pullRequest"), int)
    ):
        raise ScienceContractError("Final gate evidence is malformed")
    merge_commit = integration_evidence["mergeCommitSha"]
    try:
        remote_url = subprocess.run(
            ["git", "-C", str(repository_root), "config", "--get", "remote.origin.url"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if remote_url not in {
            "https://github.com/artemsemdev/SeaRise-Europe.git",
            "git@github.com:artemsemdev/SeaRise-Europe.git",
        }:
            raise ScienceContractError("Git origin is not the canonical project repository")
        subprocess.run(
            ["git", "-C", str(repository_root), "cat-file", "-e", f"{merge_commit}^{{commit}}"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git", "-C", str(repository_root), "merge-base", "--is-ancestor",
                binding["sourceRevision"], merge_commit,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git", "-C", str(repository_root), "merge-base", "--is-ancestor",
                merge_commit, "refs/remotes/origin/master",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScienceContractError(
            "Integration merge commit is not present on the local master ancestry"
        ) from exc
    return evaluate_recovery_gate(
        build_evidence,
        contract=contract,
        reproducibility_report=reproducibility_report,
        delivery_report=delivery_report,
        owner_decision=decision,
        final_integration_merged_to_master=merged,
        binding=binding,
    )
