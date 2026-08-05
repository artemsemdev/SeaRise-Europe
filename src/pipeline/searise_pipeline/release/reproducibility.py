"""Evidence-bound comparison of complete AR6 release candidates."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio

from searise_pipeline.science.contracts import ScienceContractError

from .evidence import binding_sha256, candidate_binding, load_json


def _independence_profile(binding: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Return only contract-validated receipt dimensions, never mutable labels."""
    try:
        profile = binding["validatedEnvironmentProfile"]
        if type(profile) is not dict or set(profile) != {
            "pythonPlatform",
            "pythonLockSha256",
            "vectorPlatform",
            "tippecanoeBinarySha256",
        }:
            raise KeyError("validatedEnvironmentProfile")
        profile = (
            profile["pythonPlatform"],
            profile["pythonLockSha256"],
            profile["vectorPlatform"],
            profile["tippecanoeBinarySha256"],
        )
    except (KeyError, TypeError) as exc:
        raise ScienceContractError(
            "Release environment lacks immutable independence dimensions"
        ) from exc
    if not all(isinstance(value, str) and value for value in profile):
        raise ScienceContractError(
            "Release environment has invalid independence dimensions"
        )
    return profile


def _maximum_cog_difference(first: Path, second: Path) -> int:
    with rasterio.open(first) as left, rasterio.open(second) as right:
        left_values = left.read()
        right_values = right.read()
        if left_values.shape != right_values.shape or left.nodata != right.nodata:
            raise ScienceContractError("Cross-environment COG schemas differ")
        left_valid = left_values != left.nodata
        right_valid = right_values != right.nodata
        if not np.array_equal(left_valid, right_valid):
            raise ScienceContractError("Cross-environment COG nodata masks differ")
        if not np.any(left_valid):
            return 0
        return int(np.max(np.abs(left_values[left_valid] - right_values[right_valid])))


def _valid_ids(path: Path) -> set[tuple[str, int, int]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ScienceContractError("Reproducibility comparison requires pinned pyarrow") from exc
    table = pq.read_table(
        path,
        columns=["scenario", "horizon", "source_location_id"],
    ).to_pydict()
    return set(zip(table["scenario"], table["horizon"], table["source_location_id"]))


def _validate_matrix(manifest: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    artifacts = manifest.get("artifacts", [])
    by_role: dict[str, list[Mapping[str, Any]]] = {}
    for item in artifacts:
        by_role.setdefault(item["role"], []).append(item)
    allowed_roles = {
        "exact-browser-lookup",
        "visual-only",
        "stac-item",
        "analytical-parity",
        "source-grid-identity",
        "licence-notice",
        "stac-collection",
    }
    if set(by_role) != allowed_roles or len(artifacts) != 31:
        raise ScienceContractError("Candidate artifact role inventory differs from the contract")
    expected = {
        (scenario, horizon)
        for scenario in contract["matrix"]["scenarios"]
        for horizon in contract["matrix"]["horizons"]
    }
    for role in ("exact-browser-lookup", "visual-only", "stac-item"):
        records = by_role[role]
        observed = {(item.get("scenario"), item.get("horizon")) for item in records}
        if len(records) != 9 or observed != expected:
            raise ScienceContractError(f"Candidate {role} artifacts differ from the 3 x 3 matrix")
    singleton_roles = {
        "analytical-parity",
        "source-grid-identity",
        "licence-notice",
        "stac-collection",
    }
    if any(len(by_role.get(role, [])) != 1 for role in singleton_roles):
        raise ScienceContractError("Candidate singleton artifacts are incomplete")


def compare_release_candidates(
    first: Path,
    second: Path,
    *,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Hash real bytes and compare scientific values and valid-ID sets exactly."""
    started = time.perf_counter()
    first_binding = candidate_binding(first, contract=contract)
    second_binding = candidate_binding(second, contract=contract)
    first_manifest = load_json(first / "manifest.json")
    second_manifest = load_json(second / "manifest.json")
    if (
        first_binding["releaseContractId"] != contract["releaseContractId"]
        or second_binding["releaseContractId"] != contract["releaseContractId"]
        or first_manifest["matrix"] != second_manifest["matrix"]
    ):
        raise ScienceContractError("Release candidates use different contracts or matrices")
    _validate_matrix(first_manifest, contract)
    _validate_matrix(second_manifest, contract)
    first_environment = first_binding["environmentIdentity"]
    second_environment = second_binding["environmentIdentity"]
    if first_binding["sourceRevision"] != second_binding["sourceRevision"]:
        raise ScienceContractError("Independent candidates must build the same source revision")
    receipt_profiles = {
        _independence_profile(first_binding),
        _independence_profile(second_binding),
    }
    first_artifacts = {item["path"]: item for item in first_manifest["artifacts"]}
    second_artifacts = {item["path"]: item for item in second_manifest["artifacts"]}
    if first_artifacts.keys() != second_artifacts.keys():
        raise ScienceContractError("Release candidates contain different artifact paths")
    maximum_difference = 0
    byte_identical = True
    for relative_path, left in first_artifacts.items():
        right = second_artifacts[relative_path]
        if left["sha256"] == right["sha256"]:
            continue
        byte_identical = False
        if left["role"] != "exact-browser-lookup":
            raise ScienceContractError(
                f"Cross-environment {left['role']} artifact is not byte-identical"
            )
        maximum_difference = max(
            maximum_difference,
            _maximum_cog_difference(first / relative_path, second / relative_path),
        )
    first_ids = _valid_ids(first / "analysis/projections.parquet")
    second_ids = _valid_ids(second / "analysis/projections.parquet")
    valid_id_difference = len(first_ids.symmetric_difference(second_ids))
    tolerance = contract["reproducibility"]
    local_status = (
        "passed"
        if maximum_difference == tolerance["scientificValueToleranceMillimetres"]
        and valid_id_difference == tolerance["validIdSetDifference"]
        and byte_identical == tolerance["byteIdentityWithinPinnedToolchain"]
        else "failed"
    )
    candidate_bindings = [first_binding, second_binding]
    required_external_bindings = [
        {
            "candidateBindingSha256": binding_sha256(binding),
            "releaseId": binding["releaseId"],
            "sourceRevision": binding["sourceRevision"],
            "receiptBuildRunId": binding["environmentIdentity"]["buildRunId"],
            "validatedEnvironmentProfile": binding["validatedEnvironmentProfile"],
        }
        for binding in candidate_bindings
    ]
    status = "failed" if local_status == "failed" else "pending-external-provenance"
    return {
        "schemaVersion": 1,
        "status": status,
        "localComparisonStatus": local_status,
        "externalProvenanceStatus": "required",
        "candidates": candidate_bindings,
        "environments": [first_environment, second_environment],
        "independentEnvironmentCount": 0,
        "receiptProfileCount": len(receipt_profiles),
        "receiptProfiles": [
            {
                "pythonPlatform": profile[0],
                "pythonLockSha256": profile[1],
                "vectorPlatform": profile[2],
                "tippecanoeBinarySha256": profile[3],
            }
            for profile in sorted(receipt_profiles)
        ],
        "requiredExternalBindings": required_external_bindings,
        "externalProvenanceRequirement": {
            "provider": "github-actions",
            "candidateBindingRequired": True,
            "distinctTrustedRunCount": contract["reproducibility"][
                "minimumIndependentEnvironments"
            ],
            "distinctValidatedProfileCount": contract["reproducibility"][
                "minimumIndependentEnvironments"
            ],
            "receiptProfilesAreProof": False,
        },
        "maximumScientificValueDifferenceMillimetres": maximum_difference,
        "validIdSetDifference": valid_id_difference,
        "byteIdentityWithinPinnedToolchain": byte_identical,
        "comparedArtifactCount": len(first_artifacts),
        "comparisonDurationSeconds": round(time.perf_counter() - started, 6),
    }
