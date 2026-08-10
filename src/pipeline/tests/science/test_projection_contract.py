"""Protect the accepted AR6 regional projection product decision."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from searise_pipeline.science import ScienceContractError, load_science_contracts

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src" / "pipeline" / "science"
PUBLIC_CONTRACT_DIR = REPO_ROOT / "contracts" / "release" / "v1"


def _public_contract_validator(schema_name: str) -> Draft202012Validator:
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in PUBLIC_CONTRACT_DIR.glob("*.schema.json")
    }
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return Draft202012Validator(schemas[schema_name], registry=registry)


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


def test_public_contract_schemas_pass_the_draft_2020_12_metaschema() -> None:
    schemas = list(PUBLIC_CONTRACT_DIR.glob("*.schema.json"))

    assert {path.name for path in schemas} == {
        "defs.schema.json",
        "scenario-config.schema.json",
    }
    for path in schemas:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_public_scenario_config_locks_the_complete_projection_matrix() -> None:
    fixture = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "scenario-config.json").read_text(
            encoding="utf-8"
        )
    )
    validator = _public_contract_validator("scenario-config.schema.json")

    validator.validate(fixture)

    assert len(fixture["layerMatrix"]) == 9
    assert fixture["defaults"] == {"scenario": "ssp2-45", "horizon": 2050}


def test_public_release_authority_keeps_machine_owner_and_provenance_separate() -> None:
    definitions = json.loads(
        (PUBLIC_CONTRACT_DIR / "defs.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(definitions["$defs"]["releaseAuthority"])

    validator.validate(
        {
            "automatedValidation": "passed",
            "releaseDisposition": "approved",
            "dataProvenanceClass": "real-source",
            "statusDisclosureRequired": False,
        }
    )
    unsafe_documents = [
        {
            "automatedValidation": "passed",
            "releaseDisposition": "approved",
            "dataProvenanceClass": "synthetic-fixture",
            "statusDisclosureRequired": False,
        },
        {
            "automatedValidation": "passed",
            "releaseDisposition": "pending-owner",
            "dataProvenanceClass": "real-source",
            "statusDisclosureRequired": False,
        },
        {
            "automatedValidation": "passed",
            "releaseDisposition": "approved",
            "statusDisclosureRequired": False,
        },
    ]

    assert all(list(validator.iter_errors(document)) for document in unsafe_documents)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/absolute/artifact.tif",
        "../outside/artifact.tif",
        "layers/../artifact.tif",
        "https://provider.example/artifact.tif",
        "layers/artifact.tif?token=secret",
        "layers\\artifact.tif",
    ],
)
def test_public_release_relative_paths_reject_origins_and_traversal(
    unsafe_path: str,
) -> None:
    definitions = json.loads(
        (PUBLIC_CONTRACT_DIR / "defs.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(definitions["$defs"]["releaseRelativePath"])

    validator.validate("layers/ssp2-45/2050.tif")
    assert list(validator.iter_errors(unsafe_path))


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda value: value["layerMatrix"].pop(), "layerMatrix"),
        (
            lambda value: value["layerMatrix"].__setitem__(
                1, {"scenario": "ssp1-26", "horizon": 2030}
            ),
            "layerMatrix.1.horizon",
        ),
        (lambda value: value["defaults"].__setitem__("scenario", "ssp5-85"), "defaults.scenario"),
        (
            lambda value: value["lookup"].__setitem__("maximumDistanceKilometres", 101),
            "lookup.maximumDistanceKilometres",
        ),
        (
            lambda value: value["lookup"].__setitem__("interpolation", "bilinear"),
            "lookup.interpolation",
        ),
        (
            lambda value: value["lookup"].__setitem__(
                "visualArtifactScientificInput", True
            ),
            "lookup.visualArtifactScientificInput",
        ),
        (lambda value: value["prohibitedClaims"].pop(), "prohibitedClaims"),
    ],
)
def test_public_scenario_config_fails_closed(
    mutation: Callable[[dict[str, Any]], object],
    expected_path: str,
) -> None:
    fixture = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "scenario-config.json").read_text(
            encoding="utf-8"
        )
    )
    mutation(fixture)
    validator = _public_contract_validator("scenario-config.schema.json")

    errors = sorted(validator.iter_errors(fixture), key=lambda error: list(error.absolute_path))

    assert errors
    observed_paths = [".".join(str(part) for part in error.absolute_path) for error in errors]
    assert expected_path in observed_paths
