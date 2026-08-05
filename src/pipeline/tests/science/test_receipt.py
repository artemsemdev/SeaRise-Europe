"""Tests for deterministic vertical-transformation evidence receipts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.science import (
    ScienceContractError,
    assert_vertical_receipt_publishable,
    canonical_vertical_receipt_bytes,
    validate_vertical_receipt,
    vertical_receipt_sha256,
)


def _receipt() -> dict:  # type: ignore[type-arg]
    digest = "a" * 64
    return {
        "$schema": "../vertical-transformation-receipt.schema.json",
        "schemaVersion": 1,
        "receiptId": "test-vertical-transform",
        "issue": 83,
        "recordedAt": "2026-08-05",
        "status": "implementation-complete-publication-blocked",
        "methodologyId": "absolute-mean-water-surface-egm2008-interval-v1",
        "inputContracts": [
            {"path": f"contract-{index}.json", "sha256": digest}
            for index in range(3)
        ],
        "sourceInputs": [
            {
                "sourceId": f"source-{index}",
                "version": "v1",
                "assetId": "asset",
                "sha256": digest,
                "verification": "locked-and-verified",
            }
            for index in range(5)
        ],
        "transform": {
            "baselineEquation": "B0 = SLA + MDT",
            "geoidEquation": "B = B0 + N_source - N_target",
            "waterEquations": ["W_low = B + P_low", "W = B + P", "W_high = B + P_high"],
            "clearanceEquations": [
                "C_low = W_low - U_B - Z - U_Z",
                "C = W - Z",
                "C_high = W_high + U_B - Z + U_Z",
            ],
            "projectionQuantiles": [0.167, 0.5, 0.833],
            "nodataClass": 255,
            "reasonCodeContract": "searise_pipeline.science.vertical.ClassificationReason",
        },
        "uncertainty": {
            "aggregation": "sum-absolute-bounds",
            "baselineTerms": ["baseline-term"],
            "terrainTerms": ["terrain-term"],
            "numericBoundsStatus": "blocked",
            "maximumTotalUncertaintyMetres": None,
        },
        "outputs": {"status": "not-generated", "artifacts": []},
        "validation": {
            "automatedTests": "passed",
            "independentReview": "pending",
            "crossEnvironment": "pending",
            "basinControls": "pending",
        },
        "blockers": [
            {
                "id": "independent-review",
                "owner": "science",
                "requiredEvidence": "Signed review record",
            }
        ],
    }


def test_canonical_receipt_is_independent_of_mapping_order() -> None:
    receipt = _receipt()
    reordered = dict(reversed(list(receipt.items())))

    assert canonical_vertical_receipt_bytes(receipt) == canonical_vertical_receipt_bytes(
        reordered
    )
    assert vertical_receipt_sha256(receipt) == vertical_receipt_sha256(reordered)


def test_receipt_digest_changes_when_evidence_changes() -> None:
    receipt = _receipt()
    changed = deepcopy(receipt)
    changed["validation"]["crossEnvironment"] = "passed"

    assert vertical_receipt_sha256(receipt) != vertical_receipt_sha256(changed)


def test_publishable_receipt_requires_outputs_bounds_and_all_reviews() -> None:
    receipt = _receipt()
    receipt["status"] = "publishable"
    receipt["blockers"] = []

    with pytest.raises(ScienceContractError, match="Invalid vertical transformation receipt"):
        validate_vertical_receipt(receipt)


def test_blocked_receipt_cannot_authorize_publication() -> None:
    with pytest.raises(ScienceContractError, match="independent-review"):
        assert_vertical_receipt_publishable(_receipt())


def test_nonfinite_number_is_rejected_from_canonical_json() -> None:
    receipt = _receipt()
    receipt["uncertainty"]["maximumTotalUncertaintyMetres"] = float("nan")

    with pytest.raises(ScienceContractError, match="not canonical JSON"):
        canonical_vertical_receipt_bytes(receipt)


def test_missing_schema_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ScienceContractError, match="Cannot read vertical receipt schema"):
        validate_vertical_receipt(_receipt(), tmp_path / "missing.schema.json")
