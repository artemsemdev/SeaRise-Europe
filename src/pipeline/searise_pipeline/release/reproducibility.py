"""Cross-environment comparison for complete AR6 release candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio

from searise_pipeline.science.contracts import ScienceContractError


def _load(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read release comparison input: {exc}") from exc
    if not isinstance(document, dict):
        raise ScienceContractError("Release comparison input must be an object")
    return document


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


def compare_release_candidates(
    first: Path,
    second: Path,
    *,
    first_environment: str,
    second_environment: str,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Compare independent outputs using the predeclared zero-value tolerance."""
    if not first_environment or not second_environment or first_environment == second_environment:
        raise ScienceContractError("Two distinct build environment identities are required")
    first_manifest = _load(first / "manifest.json")
    second_manifest = _load(second / "manifest.json")
    if (
        first_manifest["releaseContractId"] != contract["releaseContractId"]
        or second_manifest["releaseContractId"] != contract["releaseContractId"]
        or first_manifest["matrix"] != second_manifest["matrix"]
    ):
        raise ScienceContractError("Release candidates use different contracts or matrices")
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
    tolerance = contract["reproducibility"]
    status = (
        "passed"
        if maximum_difference == tolerance["scientificValueToleranceMillimetres"]
        and byte_identical == tolerance["byteIdentityWithinPinnedToolchain"]
        else "failed"
    )
    return {
        "schemaVersion": 1,
        "status": status,
        "environments": [first_environment, second_environment],
        "independentEnvironmentCount": 2,
        "maximumScientificValueDifferenceMillimetres": maximum_difference,
        "validIdSetDifference": 0,
        "byteIdentityWithinPinnedToolchain": byte_identical,
        "comparedArtifactCount": len(first_artifacts),
    }
