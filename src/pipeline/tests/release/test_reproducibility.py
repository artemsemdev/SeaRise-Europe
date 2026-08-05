"""Mutation tests for exact release artifact inventory."""

from __future__ import annotations

import pytest

from searise_pipeline.release.reproducibility import (
    _independence_profile,
    _validate_matrix,
)
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import contract


def _artifacts() -> list[dict[str, object]]:
    release = contract()
    records: list[dict[str, object]] = []
    for scenario in release["matrix"]["scenarios"]:
        for horizon in release["matrix"]["horizons"]:
            records.extend(
                [
                    {"role": "exact-browser-lookup", "scenario": scenario, "horizon": horizon},
                    {"role": "visual-only", "scenario": scenario, "horizon": horizon},
                    {"role": "stac-item", "scenario": scenario, "horizon": horizon},
                ]
            )
    records.extend(
        {"role": role}
        for role in (
            "analytical-parity",
            "source-grid-identity",
            "licence-notice",
            "stac-collection",
        )
    )
    return records


def test_matrix_inventory_rejects_a_duplicate_pair() -> None:
    artifacts = _artifacts()
    artifacts[1] = dict(artifacts[4])

    with pytest.raises(ScienceContractError, match="3 x 3 matrix"):
        _validate_matrix({"artifacts": artifacts}, contract())


def test_matrix_inventory_rejects_an_unknown_role() -> None:
    artifacts = _artifacts()
    artifacts[-1]["role"] = "unknown"

    with pytest.raises(ScienceContractError, match="role inventory"):
        _validate_matrix({"artifacts": artifacts}, contract())


def test_environment_independence_uses_immutable_profile_dimensions() -> None:
    environment = {
        "buildRunId": "arbitrary-label",
        "python": {"platform": "linux-x86_64-cp311", "lock_sha256": "a" * 64},
        "vector": {
            "pmtiles_distribution_platform": "linux-x86_64",
            "tippecanoe_binary_sha256": "b" * 64,
        },
    }

    assert _independence_profile(environment) == (
        "linux-x86_64-cp311",
        "a" * 64,
        "linux-x86_64",
        "b" * 64,
    )
