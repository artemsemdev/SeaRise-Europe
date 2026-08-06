"""Strict, non-authoritative finalization of automated release evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from searise_pipeline.science.contracts import ScienceContractError

from .delivery import create_delivery_report
from .evidence import (
    binding_sha256,
    candidate_binding,
    ensure_outside_candidate,
    load_json_snapshot,
)
from .gate import evaluate_recovery_gate

_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_RELEASE_ID = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_PROFILE_KEYS = {
    "pythonPlatform",
    "pythonLockSha256",
    "vectorPlatform",
    "tippecanoeBinarySha256",
}
_BUILD_CHECKS = {
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
}


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ScienceContractError(f"{label} does not match its exact schema")
    return value


def _exact_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ScienceContractError(f"{label} must be an exact non-negative integer")
    return value


def _finite_number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ScienceContractError(f"{label} must be finite and non-negative")
    return float(value)


def _digest(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ScienceContractError(f"{label} is not canonical")
    return value


def _hash_inventory(value: object, label: str) -> dict[str, str]:
    if type(value) is not dict or not value:
        raise ScienceContractError(f"{label} must be a non-empty object")
    inventory: dict[str, str] = {}
    for relative, digest in value.items():
        candidate = Path(relative) if type(relative) is str else None
        if (
            candidate is None
            or candidate.is_absolute()
            or not relative
            or candidate.as_posix() != relative
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or type(digest) is not str
            or _SHA256.fullmatch(digest) is None
        ):
            raise ScienceContractError(f"{label} contains a non-canonical entry")
        inventory[relative] = digest
    return inventory


def _validate_profile(value: object, label: str) -> dict[str, str]:
    profile = _exact_object(value, _PROFILE_KEYS, label)
    if any(type(item) is not str or not item for item in profile.values()):
        raise ScienceContractError(f"{label} contains an empty identity")
    _digest(profile["pythonLockSha256"], _SHA256, f"{label} Python lock")
    _digest(
        profile["tippecanoeBinarySha256"],
        _SHA256,
        f"{label} Tippecanoe binary",
    )
    return profile


def _validate_environment(value: object) -> dict[str, Any]:
    environment = _exact_object(
        value,
        {"buildRunId", "python", "vector"},
        "Candidate environment identity",
    )
    if type(environment["buildRunId"]) is not str or not environment["buildRunId"]:
        raise ScienceContractError("Candidate build-run identity is empty")
    python = _exact_object(
        environment["python"],
        {
            "platform",
            "python_version",
            "lock_path",
            "lock_sha256",
            "packages",
            "gdal_version",
            "rasterio_proj_version",
            "pyproj_proj_version",
        },
        "Candidate Python environment",
    )
    vector = _exact_object(
        environment["vector"],
        {
            "tippecanoe_version",
            "tippecanoe_source_sha256",
            "tippecanoe_binary_sha256",
            "pmtiles_version",
            "pmtiles_commit",
            "pmtiles_distribution_platform",
            "pmtiles_distribution_sha256",
            "decode_binary_sha256",
        },
        "Candidate vector environment",
    )
    if any(
        type(item) is not str or not item
        for key, item in python.items()
        if key != "packages"
    ):
        raise ScienceContractError("Candidate Python environment contains an empty identity")
    packages = python["packages"]
    if (
        type(packages) is not dict
        or not packages
        or any(
            type(name) is not str
            or not name
            or type(version) is not str
            or not version
            for name, version in packages.items()
        )
    ):
        raise ScienceContractError("Candidate package identity is malformed")
    if any(type(item) is not str or not item for item in vector.values()):
        raise ScienceContractError("Candidate vector environment contains an empty identity")
    for key in (
        "tippecanoe_source_sha256",
        "tippecanoe_binary_sha256",
        "pmtiles_distribution_sha256",
        "decode_binary_sha256",
    ):
        _digest(vector[key], _SHA256, f"Candidate environment {key}")
    _digest(python["lock_sha256"], _SHA256, "Candidate environment lock_sha256")
    return environment


def _validate_binding(
    value: object,
    *,
    release_contract_id: str,
) -> dict[str, Any]:
    binding = _exact_object(
        value,
        {
            "releaseId",
            "releaseContractId",
            "manifestSha256",
            "buildReceiptSha256",
            "buildEvidenceSha256",
            "sourceReceiptSha256",
            "artifactHashes",
            "candidateFileHashes",
            "sourceRevision",
            "environmentIdentity",
            "validatedEnvironmentProfile",
        },
        "Candidate binding",
    )
    _digest(binding["releaseId"], _RELEASE_ID, "Candidate release ID")
    if binding["releaseContractId"] != release_contract_id:
        raise ScienceContractError("Candidate binding belongs to another release contract")
    for key in (
        "manifestSha256",
        "buildReceiptSha256",
        "buildEvidenceSha256",
        "sourceReceiptSha256",
    ):
        _digest(binding[key], _SHA256, f"Candidate {key}")
    artifact_hashes = _hash_inventory(binding["artifactHashes"], "Artifact hash inventory")
    candidate_hashes = _hash_inventory(
        binding["candidateFileHashes"],
        "Candidate file hash inventory",
    )
    if len(artifact_hashes) != 31 or not set(artifact_hashes).issubset(candidate_hashes):
        raise ScienceContractError("Candidate binding lacks the exact artifact inventory")
    _digest(binding["sourceRevision"], _GIT_SHA, "Candidate source revision")
    environment = _validate_environment(binding["environmentIdentity"])
    profile = _validate_profile(
        binding["validatedEnvironmentProfile"],
        "Validated environment profile",
    )
    expected_profile = {
        "pythonPlatform": environment["python"]["platform"],
        "pythonLockSha256": environment["python"]["lock_sha256"],
        "vectorPlatform": environment["vector"]["pmtiles_distribution_platform"],
        "tippecanoeBinarySha256": environment["vector"]["tippecanoe_binary_sha256"],
    }
    if profile != expected_profile:
        raise ScienceContractError("Validated environment profile differs from the candidate")
    return binding


def _validate_build_evidence(
    value: object,
    *,
    release_id: str,
) -> dict[str, Any]:
    evidence = _exact_object(
        value,
        {"schemaVersion", "releaseId", "checks", "lookupGoldenEvidence", "totals"},
        "Build evidence",
    )
    if type(evidence["schemaVersion"]) is not int or evidence["schemaVersion"] != 1:
        raise ScienceContractError("Build evidence schema version is invalid")
    if evidence["releaseId"] != release_id:
        raise ScienceContractError("Build evidence belongs to another candidate")
    checks = _exact_object(evidence["checks"], _BUILD_CHECKS, "Build checks")
    if any(type(item) is not bool for item in checks.values()):
        raise ScienceContractError("Build checks must be exact booleans")
    if type(evidence["lookupGoldenEvidence"]) is not dict:
        raise ScienceContractError("Build evidence lacks lookup-golden identity")
    totals = _exact_object(
        evidence["totals"],
        {"cogBytes", "pmtilesBytes", "geoparquetBytes", "coreArtifactBytes"},
        "Build artifact totals",
    )
    if any(type(item) is not int or item < 0 for item in totals.values()):
        raise ScienceContractError("Build artifact totals must be exact integers")
    return evidence


def _validate_reproducibility_report(
    value: object,
    *,
    binding: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    report = _exact_object(
        value,
        {
            "schemaVersion",
            "status",
            "localComparisonStatus",
            "externalProvenanceStatus",
            "candidates",
            "environments",
            "independentEnvironmentCount",
            "receiptProfileCount",
            "receiptProfiles",
            "requiredExternalBindings",
            "externalProvenanceRequirement",
            "maximumScientificValueDifferenceMillimetres",
            "validIdSetDifference",
            "byteIdentityWithinPinnedToolchain",
            "comparedArtifactCount",
            "comparisonDurationSeconds",
        },
        "Reproducibility report",
    )
    if type(report["schemaVersion"]) is not int or report["schemaVersion"] != 1:
        raise ScienceContractError("Reproducibility schema version is invalid")
    if (
        type(report["status"]) is not str
        or report["status"] not in {"pending-external-provenance", "failed"}
        or type(report["localComparisonStatus"]) is not str
        or report["localComparisonStatus"] not in {"passed", "failed"}
        or (report["status"] == "pending-external-provenance")
        != (report["localComparisonStatus"] == "passed")
        or type(report["externalProvenanceStatus"]) is not str
        or report["externalProvenanceStatus"] != "required"
    ):
        raise ScienceContractError("Reproducibility disposition is invalid")
    candidates = report["candidates"]
    if type(candidates) is not list or len(candidates) != 2:
        raise ScienceContractError("Reproducibility report requires exactly two candidates")
    validated = [
        _validate_binding(item, release_contract_id=contract["releaseContractId"])
        for item in candidates
    ]
    if binding not in validated or any(
        item["releaseId"] != binding["releaseId"]
        or item["sourceRevision"] != binding["sourceRevision"]
        for item in validated
    ):
        raise ScienceContractError("Reproducibility report is detached from the candidate")
    if report["environments"] != [item["environmentIdentity"] for item in validated]:
        raise ScienceContractError("Reproducibility environments differ from candidates")
    if _exact_integer(report["independentEnvironmentCount"], "Independent count") != 0:
        raise ScienceContractError("Local receipts cannot assert independent environments")
    expected_profiles = sorted(
        {tuple(item["validatedEnvironmentProfile"].items()) for item in validated}
    )
    profiles = report["receiptProfiles"]
    if type(profiles) is not list:
        raise ScienceContractError("Receipt profiles must be a list")
    validated_profiles = [
        _validate_profile(item, "Receipt profile")
        for item in profiles
    ]
    observed_profiles = sorted(tuple(item.items()) for item in validated_profiles)
    if (
        observed_profiles != expected_profiles
        or _exact_integer(report["receiptProfileCount"], "Receipt profile count")
        != len(expected_profiles)
    ):
        raise ScienceContractError("Receipt profiles differ from candidate receipts")
    expected_bindings = [
        {
            "candidateBindingSha256": binding_sha256(item),
            "releaseId": item["releaseId"],
            "sourceRevision": item["sourceRevision"],
            "receiptBuildRunId": item["environmentIdentity"]["buildRunId"],
            "validatedEnvironmentProfile": item["validatedEnvironmentProfile"],
        }
        for item in validated
    ]
    if report["requiredExternalBindings"] != expected_bindings:
        raise ScienceContractError("Required external bindings differ from candidates")
    minimum = contract["reproducibility"]["minimumIndependentEnvironments"]
    if report["externalProvenanceRequirement"] != {
        "provider": "github-actions",
        "candidateBindingRequired": True,
        "distinctTrustedRunCount": minimum,
        "distinctValidatedProfileCount": minimum,
        "receiptProfilesAreProof": False,
    }:
        raise ScienceContractError("External provenance requirement differs from the contract")
    maximum_difference = _exact_integer(
        report["maximumScientificValueDifferenceMillimetres"],
        "Maximum scientific value difference",
    )
    valid_id_difference = _exact_integer(
        report["validIdSetDifference"],
        "Valid ID-set difference",
    )
    if type(report["byteIdentityWithinPinnedToolchain"]) is not bool:
        raise ScienceContractError("Byte-identity status must be an exact boolean")
    if _exact_integer(report["comparedArtifactCount"], "Compared artifact count") != 31:
        raise ScienceContractError("Reproducibility report compared the wrong inventory")
    _finite_number(report["comparisonDurationSeconds"], "Comparison duration")
    tolerance = contract["reproducibility"]
    local_passed = (
        maximum_difference == tolerance["scientificValueToleranceMillimetres"]
        and valid_id_difference == tolerance["validIdSetDifference"]
        and report["byteIdentityWithinPinnedToolchain"]
        == tolerance["byteIdentityWithinPinnedToolchain"]
    )
    if local_passed != (report["localComparisonStatus"] == "passed"):
        raise ScienceContractError("Reproducibility status differs from measured parity")
    return report


def _validate_source_revision(repository_root: Path, source_revision: str) -> None:
    if repository_root.is_symlink() or not repository_root.is_dir():
        raise ScienceContractError("Repository root must be a real directory")
    try:
        top_level = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if Path(top_level).resolve() != repository_root.resolve():
            raise ScienceContractError("Repository root is not the exact Git worktree")
        subprocess.run(
            ["git", "-C", str(repository_root), "cat-file", "-e", f"{source_revision}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScienceContractError(
            "Cannot verify the candidate source revision in Git"
        ) from exc


def _bound_candidate_json(
    candidate: Path,
    relative: str,
    expected_sha256: str,
) -> Mapping[str, Any]:
    document, observed_sha256 = load_json_snapshot(candidate / relative)
    if observed_sha256 != expected_sha256:
        raise ScienceContractError(f"Candidate {relative} changed after candidate binding")
    return document


def finalize_recovery_gate(
    candidate: Path,
    *,
    contract: Mapping[str, Any],
    reproducibility_report_path: Path,
    delivery_trace_path: Path,
    build_timing_path: Path,
    harness_path: Path,
    repository_root: Path,
) -> Mapping[str, Any]:
    """Recompute and bind automated evidence while leaving authority pending."""
    if candidate.is_symlink():
        raise ScienceContractError("Release candidate path cannot be a symlink")
    try:
        candidate_root = candidate.resolve(strict=True)
    except OSError as exc:
        raise ScienceContractError("Release candidate does not exist") from exc
    binding = _validate_binding(
        candidate_binding(candidate_root, contract=contract),
        release_contract_id=contract["releaseContractId"],
    )
    external_paths = {
        "reproducibility": ensure_outside_candidate(
            candidate_root,
            reproducibility_report_path,
            label="Reproducibility report",
        ),
        "trace": ensure_outside_candidate(
            candidate_root,
            delivery_trace_path,
            label="Delivery trace",
        ),
        "timing": ensure_outside_candidate(
            candidate_root,
            build_timing_path,
            label="Build timing",
        ),
        "harness": ensure_outside_candidate(
            candidate_root,
            harness_path,
            label="Browser harness",
        ),
    }
    for label, path in external_paths.items():
        if not path.is_file():
            raise ScienceContractError(f"{label} is not a regular file")
    reproducibility_document, reproducibility_sha256 = load_json_snapshot(
        external_paths["reproducibility"]
    )
    reproducibility = _validate_reproducibility_report(
        reproducibility_document,
        binding=binding,
        contract=contract,
    )
    delivery = create_delivery_report(
        candidate_root,
        external_paths["trace"],
        external_paths["harness"],
        external_paths["timing"],
        contract=contract,
    )
    if delivery.get("candidate") != binding:
        raise ScienceContractError("Recomputed delivery evidence is detached from the candidate")
    source_receipt = _bound_candidate_json(
        candidate_root,
        "source-receipt.json",
        binding["sourceReceiptSha256"],
    )
    contract_sha256 = hashlib.sha256(
        (
            json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    if source_receipt.get("releaseContractSha256") != contract_sha256:
        raise ScienceContractError("Candidate release-contract hash is detached")
    build_evidence = _validate_build_evidence(
        _bound_candidate_json(
            candidate_root,
            "build-evidence.json",
            binding["buildEvidenceSha256"],
        ),
        release_id=binding["releaseId"],
    )
    if candidate_binding(candidate_root, contract=contract) != binding:
        raise ScienceContractError("Release candidate changed during finalization")
    if repository_root.is_symlink():
        raise ScienceContractError("Repository root cannot be a symlink")
    try:
        resolved_repository = repository_root.resolve(strict=True)
    except OSError as exc:
        raise ScienceContractError("Repository root does not exist") from exc
    _validate_source_revision(resolved_repository, binding["sourceRevision"])
    gate = dict(
        evaluate_recovery_gate(
            build_evidence,
            contract=contract,
            reproducibility_report=reproducibility,
            delivery_report=delivery,
        )
    )
    gate["evidenceBindings"] = {
        "candidateBindingSha256": binding_sha256(binding),
        "manifestSha256": binding["manifestSha256"],
        "reproducibilityReportSha256": reproducibility_sha256,
        "deliveryReportSha256": binding_sha256(delivery),
        "deliveryTraceSha256": delivery["trace"]["sha256"],
        "buildTimingSha256": delivery["buildTiming"]["sha256"],
        "browserHarnessSha256": delivery["harness"]["sha256"],
    }
    gate["externalVerificationRequired"] = {
        "reproducibilityProvenance": {
            "status": "pending-external-verification",
            "provider": reproducibility["externalProvenanceRequirement"]["provider"],
            "requiredExternalBindings": reproducibility["requiredExternalBindings"],
        }
    }
    return gate
