"""Tests for deterministic vertical-transformation evidence receipts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.science import (
    ScienceContractError,
    assert_vertical_receipt_publishable,
    canonical_vertical_receipt_bytes,
    load_vertical_receipt,
    validate_vertical_receipt,
    vertical_receipt_sha256,
)

REPO_ROOT = Path(__file__).parents[4]
EVIDENCE_PATH = (
    REPO_ROOT
    / "src"
    / "pipeline"
    / "science"
    / "evidence"
    / "vertical-transformation-implementation.json"
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
                "members": [],
                "verification": "locked-and-verified",
            }
            for index in range(5)
        ],
        "software": {
            "runtime": "CPython 3.9.6",
            "packages": [{"name": "searise-pipeline", "version": "0.1.0"}],
            "externalGeoidEngine": {"status": "pending", "name": None, "version": None},
        },
        "baseline": {
            "referencePeriod": {
                "startInclusive": "1995-01-01",
                "endExclusive": "2015-01-01",
            },
            "monthlyObjectCount": 240,
            "calendarDayWeight": 7305,
            "aggregation": "calendar-day-weighted-complete-months-plus-static-mdt",
            "missingPeriodRule": "nodata",
        },
        "grid": {
            "status": "pending-phase-0.8",
            "horizontalCrs": None,
            "verticalCrs": "EPSG:3855",
            "shape": None,
            "affine": None,
            "pixelInterpretation": None,
            "continuousInterpolation": "bilinear-inside-source-support",
            "categoricalInterpolation": "nearest-neighbour",
            "extrapolation": "none",
            "nodataRule": "propagate-any-missing-source-or-neighbour",
        },
        "geoid": {
            "status": "blocked",
            "commonEllipsoid": None,
            "permanentTideRule": None,
            "source": _geoid_model("GOCO06S", digest),
            "target": _geoid_model("EGM2008", digest),
        },
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
            "baselineTerms": [_term("baseline-term", "baseline")],
            "terrainTerms": [_term("terrain-term", "terrain")],
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


def _geoid_model(model: str, digest: str) -> dict:  # type: ignore[type-arg]
    return {
        "model": model,
        "version": "v1",
        "memberSha256": digest,
        "nativeTideSystem": "tide_free",
        "outputTideSystem": "tide_free",
        "evaluationEpoch": None,
        "maximumDegree": 10,
        "maximumOrder": 10,
        "normalization": "fully_normalized",
        "earthGravityConstant": None,
        "referenceRadiusMetres": None,
    }


def _term(term_id: str, component: str) -> dict:  # type: ignore[type-arg]
    return {
        "id": term_id,
        "component": component,
        "units": "m",
        "provenance": "test evidence",
        "spatialHandling": "per-cell",
        "aggregation": "sum-absolute-bounds",
        "status": "pending-bound",
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


def test_checked_in_receipt_binds_exact_contract_and_source_bytes() -> None:
    receipt = load_vertical_receipt(EVIDENCE_PATH)
    for contract in receipt["inputContracts"]:
        assert hashlib.sha256((REPO_ROOT / contract["path"]).read_bytes()).hexdigest() == contract[
            "sha256"
        ]

    source_lock = json.loads(
        (REPO_ROOT / "src/pipeline/sources/source-lock.json").read_text(encoding="utf-8")
    )
    sources = {source["id"]: source for source in source_lock["sources"]}
    for source_input in receipt["sourceInputs"][:5]:
        source = sources[source_input["sourceId"]]
        asset = next(
            item for item in source["assets"] if item["id"] == source_input["assetId"]
        )
        expected_sha = asset.get("sha256", asset.get("objectSet", {}).get("payloadSha256"))
        assert source_input["version"] == source["version"]
        assert source_input["sha256"] == expected_sha
        members = {member["id"]: member for member in asset.get("members", [])}
        for member in source_input["members"]:
            if member["id"] != "object-manifest":
                assert member["sha256"] == members[member["id"]]["sha256"]


def test_checked_in_receipt_records_complete_blocked_execution_context() -> None:
    receipt = load_vertical_receipt(EVIDENCE_PATH)

    assert receipt["baseline"]["monthlyObjectCount"] == 240
    assert receipt["baseline"]["calendarDayWeight"] == 7305
    assert receipt["grid"]["shape"] is None
    assert receipt["grid"]["affine"] is None
    assert receipt["software"]["externalGeoidEngine"]["status"] == "pending"
    assert receipt["geoid"]["target"]["earthGravityConstant"] is None
    assert receipt["outputs"] == {"status": "not-generated", "artifacts": []}
    terms = receipt["uncertainty"]["baselineTerms"] + receipt["uncertainty"][
        "terrainTerms"
    ]
    assert {term["status"] for term in terms} == {"pending-bound"}
    assert all(
        term["units"] == "m"
        and term["provenance"]
        and term["spatialHandling"]
        and term["aggregation"] == "sum-absolute-bounds"
        for term in terms
    )
    assert {blocker["id"] for blocker in receipt["blockers"]} == {
        "egm2008-evaluation-conventions",
        "quid-mapping-bounds",
        "phase-0.8-terrain-connectivity-controls",
        "baltic-black-sea-controls",
        "cross-environment-reproducibility",
        "independent-scientific-review",
    }
