"""Protect the accepted AR6 regional projection product decision."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from searise_pipeline.science import ScienceContractError, load_science_contracts

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src" / "pipeline" / "science"


def test_projection_contract_binds_source_quantity_and_states() -> None:
    contract = load_science_contracts(CONTRACT_DIR).projection_contract

    assert contract is not None
    assert contract["sourceBinding"] == {
        "semanticsPath": "src/pipeline/science/source-semantics.json",
        "sourceKey": "ipcc-ar6-sea-level/20210809",
        "archiveSha256": (
            "d3b1c2ed093cca491db2461e67b782bcca98763d326378ffee39908c2b094e91"
        ),
        "memberBasenameTemplate": "total_{scenario}_medium_confidence_values.nc",
        "variable": "sea_level_change",
        "sourceUnits": "mm",
        "publishedUnits": "m",
        "unitToMetres": 0.001,
        "fillValue": -32768,
        "confidence": "medium",
        "baseline": "1995-2014 mean",
        "scenarios": ["ssp1-26", "ssp2-45", "ssp5-85"],
        "horizons": [2030, 2050, 2100],
        "quantiles": {"lower": 0.167, "central": 0.5, "upper": 0.833},
    }
    assert contract["resultContract"]["states"] == [
        "ProjectionAvailable",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
    ]
    assert contract["modeledQuantity"]["id"] == (
        "regional-relative-sea-level-change"
    )


def test_projection_lookup_is_grid_only_and_does_not_skip_nodata() -> None:
    contract = load_science_contracts(CONTRACT_DIR).projection_contract
    assert contract is not None
    point = contract["spatialLookup"]["point"]

    assert contract["spatialLookup"]["map"]["sourceLocationFamily"] == "grid"
    assert point == {
        "sourceLocationFamily": "grid",
        "operator": "nearest-source-grid-location",
        "distanceMetric": "haversine",
        "earthRadiusKilometres": 6371.0088,
        "maximumDistanceKilometres": 100,
        "tieBreak": "lowest-source-location-id",
        "selectionDistanceRounding": "none",
        "reportedDistanceDecimalPlaces": 6,
        "interpolation": "none",
        "extrapolation": "none",
        "tideGaugeFallback": "prohibited",
        "nodataSubstitution": "prohibited",
    }
    assert contract["resultContract"]["dataUnavailableReasons"] == [
        "source-location-too-distant",
        "source-value-nodata",
    ]


def test_automation_cannot_approve_projection_release() -> None:
    contract = load_science_contracts(CONTRACT_DIR).projection_contract

    assert contract is not None
    assert contract["validation"]["onlineReference"]["requiredForCi"] is False
    assert contract["validation"]["automatedValidationMeaning"] == (
        "source-and-implementation-parity-only"
    )
    assert contract["validation"]["releaseDecisionAuthority"] == "project-owner"
    assert contract["publicationGate"] == {
        "status": "blocked",
        "automatedValidation": "pending",
        "releaseDecision": "pending-owner",
        "blockingIssues": [135, 110],
        "phase1Unlocked": False,
    }


@pytest.mark.parametrize(
    ("section", "field", "unsafe_value"),
    [
        ("spatialLookup.point", "sourceLocationFamily", "tide-gauge"),
        ("spatialLookup.point", "interpolation", "bilinear"),
        ("spatialLookup.point", "nodataSubstitution", "nearest-valid"),
        ("validation.onlineReference", "requiredForCi", True),
        ("validation", "releaseDecisionAuthority", "ci"),
        ("userFacingDisclosure", "distanceAndResolutionRequired", False),
    ],
)
def test_projection_contract_rejects_semantic_weakening(
    tmp_path: Path,
    section: str,
    field: str,
    unsafe_value: object,
) -> None:
    for path in CONTRACT_DIR.glob("*.json"):
        shutil.copy2(path, tmp_path / path.name)

    contract_path = tmp_path / "ar6-projection-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    target = contract
    for key in section.split("."):
        target = target[key]
    target[field] = unsafe_value
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ScienceContractError, match="ar6-projection-contract"):
        load_science_contracts(tmp_path)
