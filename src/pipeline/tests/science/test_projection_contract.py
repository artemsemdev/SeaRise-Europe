"""Protect the accepted AR6 regional projection product decision."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from searise_pipeline.release import (
    PublicReleaseContractError,
    validate_public_manifest,
    validate_release_artifacts,
    validate_release_rights,
    validate_release_stac,
)
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
    return Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=FormatChecker(),
    )


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
        "architecture-evidence.schema.json",
        "artifact.schema.json",
        "attribution.schema.json",
        "build-receipt.schema.json",
        "defs.schema.json",
        "methodology.schema.json",
        "manifest.schema.json",
        "projection-result.schema.json",
        "quality-summary.schema.json",
        "release-pointer.schema.json",
        "scenario-config.schema.json",
        "search-record.schema.json",
        "source-receipt.schema.json",
        "stac.schema.json",
    }
    for path in schemas:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "fixture_path",
    sorted((PUBLIC_CONTRACT_DIR / "fixtures" / "valid").glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_accepts_every_shared_public_contract_fixture(
    fixture_path: Path,
) -> None:
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    schema_name = document["$schema"].rsplit("/", maxsplit=1)[-1]

    _public_contract_validator(schema_name).validate(document)


@pytest.mark.parametrize(
    "fixture_path",
    sorted((PUBLIC_CONTRACT_DIR / "fixtures" / "invalid").glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_rejects_every_shared_negative_public_contract_fixture(
    fixture_path: Path,
) -> None:
    document = json.loads(fixture_path.read_text(encoding="utf-8"))
    schema_name = document["$schema"].rsplit("/", maxsplit=1)[-1]

    assert list(_public_contract_validator(schema_name).iter_errors(document))


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
    assert fixture["dataProvenanceClass"] == "synthetic-fixture"


def test_public_release_authority_keeps_machine_owner_and_provenance_separate() -> None:
    definitions = json.loads(
        (PUBLIC_CONTRACT_DIR / "defs.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(
        definitions["$id"], Resource.from_contents(definitions)
    )
    validator = Draft202012Validator(
        {"$ref": f'{definitions["$id"]}#/$defs/releaseAuthority'},
        registry=registry,
    )

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


def test_public_projection_result_schema_accepts_exactly_four_fixture_states() -> None:
    validator = _public_contract_validator("projection-result.schema.json")
    paths = sorted((PUBLIC_CONTRACT_DIR / "fixtures" / "valid").glob("*.json"))
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    results = [
        document
        for document in documents
        if document["$schema"].endswith("/projection-result.schema.json")
    ]

    for result in results:
        validator.validate(result)

    assert {result["state"] for result in results} == {
        "ProjectionAvailable",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
    }
    assert all(
        result["releaseAuthority"]["dataProvenanceClass"] == "synthetic-fixture"
        for result in results
    )

    available = next(result for result in results if result["state"] == "ProjectionAvailable")
    available["source"]["distanceKilometres"] = 100
    validator.validate(available)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result["source"].__setitem__("distanceKilometres", 100.000001),
        lambda result: result["releaseAuthority"].__setitem__(
            "releaseDisposition", "approved"
        ),
        lambda result: result.__setitem__("reasonCode", "source-value-nodata"),
        lambda result: result.__setitem__("renderedColourMetres", 0.201),
        lambda result: result["projection"].__setitem__("baseline", "absolute sea level"),
    ],
)
def test_projection_available_result_rejects_contradictory_semantics(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    result = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "projection-available.json"
        ).read_text(encoding="utf-8")
    )
    mutate(result)

    errors = list(_public_contract_validator("projection-result.schema.json").iter_errors(result))

    assert errors


def test_non_projection_states_cannot_carry_scientific_values() -> None:
    result = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "out-of-scope.json").read_text(
            encoding="utf-8"
        )
    )
    result["projection"] = {
        "lowerMillimetres": 100,
        "medianMillimetres": 200,
        "upperMillimetres": 300,
    }

    errors = list(_public_contract_validator("projection-result.schema.json").iter_errors(result))

    assert errors


def test_too_distant_reason_requires_distance_above_the_inclusive_limit() -> None:
    result = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "data-unavailable.json"
        ).read_text(encoding="utf-8")
    )
    result["reasonCode"] = "source-location-too-distant"
    validator = _public_contract_validator("projection-result.schema.json")

    assert list(validator.iter_errors(result))

    result["source"]["distanceKilometres"] = 100.000001
    validator.validate(result)


@pytest.mark.parametrize(
    "schema_name",
    ["methodology.schema.json", "attribution.schema.json"],
)
def test_public_source_metadata_fixtures_are_schema_valid(schema_name: str) -> None:
    fixture_name = schema_name.removesuffix(".schema.json") + ".json"
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / fixture_name).read_text(
            encoding="utf-8"
        )
    )

    _public_contract_validator(schema_name).validate(document)
    assert document["dataProvenanceClass"] == "synthetic-fixture"


def test_methodology_rejects_scientific_semantic_weakening() -> None:
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "methodology.json").read_text(
            encoding="utf-8"
        )
    )
    document["lookup"]["scientificArtifactRole"] = "projection-visual-pmtiles"

    assert list(
        _public_contract_validator("methodology.schema.json").iter_errors(document)
    )


def test_attribution_rejects_incomplete_rights_and_non_https_sources() -> None:
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "attribution.json").read_text(
            encoding="utf-8"
        )
    )
    document["records"][0]["redistribution"] = "conditional"
    document["records"][0]["sourceUrl"] = "http://provider.example/source.zip"

    errors = list(_public_contract_validator("attribution.schema.json").iter_errors(document))

    assert len(errors) >= 2


@pytest.mark.parametrize(
    "schema_name",
    ["source-receipt.schema.json", "build-receipt.schema.json"],
)
def test_public_receipt_fixtures_are_schema_valid(schema_name: str) -> None:
    fixture_name = schema_name.removesuffix(".schema.json") + ".json"
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / fixture_name).read_text(
            encoding="utf-8"
        )
    )

    _public_contract_validator(schema_name).validate(document)
    assert document["dataProvenanceClass"] == "synthetic-fixture"


def test_source_receipt_rejects_secret_urls_and_publishable_cache() -> None:
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "source-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    document["sourceUrl"] += "?token=secret"
    document["cache"]["publicationAllowed"] = True

    errors = list(_public_contract_validator("source-receipt.schema.json").iter_errors(document))

    assert len(errors) >= 2


def test_build_receipt_rejects_network_and_unsafe_output_identity() -> None:
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "build-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    document["networkAccess"] = "enabled"
    document["outputs"][0]["path"] = "../outside.json"
    document["outputs"][0]["mediaType"] = "application/octet-stream"

    errors = list(_public_contract_validator("build-receipt.schema.json").iter_errors(document))

    assert len(errors) >= 3


@pytest.mark.parametrize(
    "schema_name",
    [
        "search-record.schema.json",
        "quality-summary.schema.json",
        "architecture-evidence.schema.json",
        "release-pointer.schema.json",
    ],
)
def test_public_consumer_metadata_fixtures_are_schema_valid(schema_name: str) -> None:
    fixture_name = schema_name.removesuffix(".schema.json") + ".json"
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / fixture_name).read_text(
            encoding="utf-8"
        )
    )

    _public_contract_validator(schema_name).validate(document)
    assert document["dataProvenanceClass"] == "synthetic-fixture"


def test_search_record_rejects_historical_and_contradictory_records() -> None:
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "search-record.json").read_text(
            encoding="utf-8"
        )
    )
    document["featureCode"] = "PPLH"
    document["isCoastal"] = False

    errors = list(_public_contract_validator("search-record.schema.json").iter_errors(document))

    assert len(errors) >= 2


def test_quality_and_architecture_evidence_fail_closed() -> None:
    quality = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "quality-summary.json").read_text(
            encoding="utf-8"
        )
    )
    quality["blockingChecks"].append(
        {"code": "fixture-blocker", "evidencePath": "evidence/blocker.json"}
    )
    quality["validations"][0]["status"] = "failed"
    quality["releaseDisposition"] = "approved"
    architecture = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "architecture-evidence.json"
        ).read_text(encoding="utf-8")
    )
    architecture["runtime"]["applicationApiCalls"] = 1
    architecture["privacy"]["searchSentToProjectServer"] = True

    assert len(
        list(_public_contract_validator("quality-summary.schema.json").iter_errors(quality))
    ) >= 3
    assert len(
        list(
            _public_contract_validator("architecture-evidence.schema.json").iter_errors(
                architecture
            )
        )
    ) >= 2


def test_release_pointer_rejects_origins_and_unsafe_cache_policy() -> None:
    document = json.loads(
        (PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "release-pointer.json").read_text(
            encoding="utf-8"
        )
    )
    document["manifest"]["path"] = "https://provider.example/manifest.json"
    document["cacheControl"] = "public, max-age=31536000, immutable"

    errors = list(_public_contract_validator("release-pointer.schema.json").iter_errors(document))

    assert len(errors) >= 2


def test_public_artifact_fixtures_lock_exact_and_visual_roles() -> None:
    validator = _public_contract_validator("artifact.schema.json")
    paths = sorted((PUBLIC_CONTRACT_DIR / "fixtures" / "valid").glob("artifact-*.json"))
    artifacts = [json.loads(path.read_text(encoding="utf-8")) for path in paths]

    for artifact in artifacts:
        validator.validate(artifact)

    assert {artifact["scientificUse"] for artifact in artifacts} == {
        "exact-lookup",
        "exact-analytics",
        "visual-only",
        "not-applicable",
    }
    assert all(artifact["dataProvenanceClass"] == "synthetic-fixture" for artifact in artifacts)


def test_static_stac_fixtures_use_the_pinned_1_1_0_profile() -> None:
    validator = _public_contract_validator("stac.schema.json")
    fixture_dir = PUBLIC_CONTRACT_DIR / "fixtures" / "valid"
    documents = [
        json.loads((fixture_dir / name).read_text(encoding="utf-8"))
        for name in ("stac-catalog.json", "stac-collection.json", "stac-item.json")
    ]

    for document in documents:
        validator.validate(document)

    item = documents[-1]
    assert all(document["stac_version"] == "1.1.0" for document in documents)
    assert item["assets"]["analysis"]["roles"] == [
        "data",
        "searise:exact-lookup",
    ]
    assert item["assets"]["visual"]["roles"] == [
        "visual",
        "searise:visual-only",
    ]


def test_static_stac_negative_fixture_rejects_mutable_origin() -> None:
    document = json.loads(
        (
            PUBLIC_CONTRACT_DIR
            / "fixtures"
            / "invalid"
            / "stac-catalog-unsafe-origin.json"
        ).read_text(encoding="utf-8")
    )

    assert list(_public_contract_validator("stac.schema.json").iter_errors(document))


def test_stac_item_artifacts_use_geojson_media_type() -> None:
    artifact = json.loads(
        (
            PUBLIC_CONTRACT_DIR
            / "fixtures"
            / "valid"
            / "artifact-search-index.json"
        ).read_text(encoding="utf-8")
    )
    artifact.update(
        {
            "artifactId": "stac-ssp2-45-2050",
            "path": "stac/items/ssp2-45-2050.json",
            "role": "stac-item",
            "mediaType": "application/geo+json",
        }
    )
    validator = _public_contract_validator("artifact.schema.json")

    validator.validate(artifact)
    artifact["mediaType"] = "application/json"
    assert list(validator.iter_errors(artifact))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.__setitem__("stac_version", "1.0.0"),
        lambda item: item["assets"]["analysis"].__setitem__(
            "href", "https://provider.example/analysis.tif"
        ),
        lambda item: item["assets"]["visual"].__setitem__(
            "roles", ["data", "searise:exact-lookup"]
        ),
        lambda item: item["properties"].__setitem__(
            "searise:scientific_use", "pmtiles-exact"
        ),
    ],
)
def test_static_stac_item_rejects_unsafe_or_contradictory_metadata(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    item = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "stac-item.json"
        ).read_text(encoding="utf-8")
    )
    mutate(item)

    assert list(_public_contract_validator("stac.schema.json").iter_errors(item))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda artifact: artifact.__setitem__("path", "../analysis.tif"),
        lambda artifact: artifact.__setitem__("mediaType", "application/vnd.pmtiles"),
        lambda artifact: artifact.__setitem__("scientificUse", "visual-only"),
        lambda artifact: artifact.__setitem__("sha256", "not-a-hash"),
        lambda artifact: artifact.__setitem__("rights", {"attributionIds": []}),
        lambda artifact: artifact["projectionContext"]["grid"].__setitem__(
            "nativeResolutionDegrees", 0.5
        ),
    ],
)
def test_analysis_artifact_rejects_contract_weakening(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    artifact = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "artifact-analysis-cog.json"
        ).read_text(encoding="utf-8")
    )
    mutate(artifact)

    assert list(_public_contract_validator("artifact.schema.json").iter_errors(artifact))


def test_non_projection_artifact_cannot_claim_projection_context() -> None:
    artifact = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "artifact-search-index.json"
        ).read_text(encoding="utf-8")
    )
    artifact["mediaType"] = "application/json"
    validator = _public_contract_validator("artifact.schema.json")

    assert list(validator.iter_errors(artifact))

    artifact["mediaType"] = "application/vnd.searise.search-index+json"
    artifact["projectionContext"] = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "artifact-analysis-cog.json"
        ).read_text(encoding="utf-8")
    )["projectionContext"]

    assert list(validator.iter_errors(artifact))


def _manifest_artifact(
    template: dict[str, Any],
    *,
    artifact_id: str,
    path: str,
    role: str,
    media_type: str,
) -> dict[str, Any]:
    artifact = copy.deepcopy(template)
    artifact.update(
        {
            "artifactId": artifact_id,
            "path": path,
            "role": role,
            "mediaType": media_type,
            "sha256": hashlib.sha256(artifact_id.encode()).hexdigest(),
        }
    )
    return artifact


def _valid_manifest() -> dict[str, Any]:
    fixture_dir = PUBLIC_CONTRACT_DIR / "fixtures" / "valid"
    cog_template = json.loads(
        (fixture_dir / "artifact-analysis-cog.json").read_text(encoding="utf-8")
    )
    pmtiles_template = json.loads(
        (fixture_dir / "artifact-visual-pmtiles.json").read_text(encoding="utf-8")
    )
    geoparquet = json.loads(
        (fixture_dir / "artifact-projection-geoparquet.json").read_text(encoding="utf-8")
    )
    metadata_template = json.loads(
        (fixture_dir / "artifact-search-index.json").read_text(encoding="utf-8")
    )
    datasets: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = [geoparquet]
    for scenario in ("ssp1-26", "ssp2-45", "ssp5-85"):
        member_hash = hashlib.sha256(scenario.encode()).hexdigest()
        for horizon in (2030, 2050, 2100):
            analysis_id = f"projection-{scenario}-{horizon}-cog"
            visual_id = f"projection-{scenario}-{horizon}-pmtiles"
            stac_id = f"stac-{scenario}-{horizon}"
            cog = copy.deepcopy(cog_template)
            cog.update(
                {
                    "artifactId": analysis_id,
                    "path": f"analysis/{scenario}/{horizon}.tif",
                    "sha256": hashlib.sha256(analysis_id.encode()).hexdigest(),
                }
            )
            cog["projectionContext"].update({"scenario": scenario, "horizon": horizon})
            cog["projectionContext"]["source"]["memberSha256"] = member_hash
            visual = copy.deepcopy(pmtiles_template)
            visual.update(
                {
                    "artifactId": visual_id,
                    "path": f"layers/{scenario}/{horizon}.pmtiles",
                    "sha256": hashlib.sha256(visual_id.encode()).hexdigest(),
                }
            )
            visual["projectionContext"].update({"scenario": scenario, "horizon": horizon})
            visual["projectionContext"]["source"]["memberSha256"] = member_hash
            stac_item = _manifest_artifact(
                metadata_template,
                artifact_id=stac_id,
                path=f"stac/items/{scenario}-{horizon}.json",
                role="stac-item",
                media_type="application/geo+json",
            )
            artifacts.extend([cog, visual, stac_item])
            datasets.append(
                {
                    "scenario": scenario,
                    "horizon": horizon,
                    "analysisArtifactId": analysis_id,
                    "visualArtifactId": visual_id,
                    "analyticalArtifactId": "projection-matrix-geoparquet",
                    "stacItemArtifactId": stac_id,
                }
            )
    metadata = [
        ("scenario-config", "config/scenarios.json", "scenario-config", "application/json"),
        ("methodology", "config/methodology.json", "methodology", "application/json"),
        ("attribution", "config/source-attribution.json", "source-attribution", "application/json"),
        ("source-receipt", "receipts/sources/ipcc-ar6.json", "source-receipt", "application/json"),
        ("build-receipt", "receipts/build.json", "build-receipt", "application/json"),
        (
            "search-records",
            "search/settlements.parquet",
            "settlement-geoparquet",
            "application/vnd.apache.parquet",
        ),
        ("quality-summary", "evidence/quality-summary.json", "quality-summary", "application/json"),
        (
            "architecture-evidence",
            "evidence/architecture.json",
            "architecture-evidence",
            "application/json",
        ),
        ("stac-catalog", "stac/catalog.json", "stac-catalog", "application/json"),
        ("stac-collection", "stac/collection.json", "stac-collection", "application/json"),
        ("checksums", "checksums.txt", "checksums", "text/plain"),
        ("provenance", "provenance.intoto.jsonl", "provenance", "application/x-ndjson"),
        (
            "signature",
            "manifest.sigstore.json",
            "signature",
            "application/vnd.dev.sigstore.bundle+json;version=0.3",
        ),
    ]
    artifacts.extend(
        _manifest_artifact(
            metadata_template,
            artifact_id=artifact_id,
            path=path,
            role=role,
            media_type=media_type,
        )
        for artifact_id, path, role, media_type in metadata
    )
    release_id = cog_template["dataReleaseId"]
    return {
        "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/manifest.schema.json",
        "schemaVersion": "1.0.0",
        "dataReleaseId": release_id,
        "dataProvenanceClass": "synthetic-fixture",
        "releaseAuthority": {
            "automatedValidation": "pending",
            "releaseDisposition": "pending-owner",
            "dataProvenanceClass": "synthetic-fixture",
            "statusDisclosureRequired": True,
        },
        "createdAt": "2026-08-10T12:05:00Z",
        "codeRevision": "c096aeab4e0994faa7a9d2253b47215ef897dfcb",
        "previousReleaseId": None,
        "methodologyVersion": "ar6-regional-projection-v1",
        "defaults": {"scenario": "ssp2-45", "horizon": 2050},
        "publication": {
            "releasePath": f"releases/{release_id}",
            "cacheControl": "public, max-age=31536000, immutable",
            "appendOnly": True,
        },
        "sources": [
            {
                "sourceId": "fixture/ipcc-ar6-regional",
                "sourceRelease": "20210809-fixture",
                "archiveSha256": "1" * 64,
                "attributionId": "ipcc-ar6-sl-projections-20210809",
                "receiptArtifactId": "source-receipt",
            }
        ],
        "contractArtifacts": {
            "scenarioConfig": "scenario-config",
            "methodology": "methodology",
            "attribution": "attribution",
            "sourceReceipts": ["source-receipt"],
            "buildReceipt": "build-receipt",
            "searchRecords": "search-records",
            "qualitySummary": "quality-summary",
            "architectureEvidence": "architecture-evidence",
            "stacCatalog": "stac-catalog",
            "stacCollection": "stac-collection",
            "stacItems": [
                f"stac-{scenario}-{horizon}"
                for scenario in ("ssp1-26", "ssp2-45", "ssp5-85")
                for horizon in (2030, 2050, 2100)
            ],
            "checksums": "checksums",
            "provenance": "provenance",
            "signature": "signature",
        },
        "artifacts": artifacts,
        "datasets": datasets,
    }


def _valid_attribution_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    attribution = json.loads(
        (
            PUBLIC_CONTRACT_DIR / "fixtures" / "valid" / "attribution.json"
        ).read_text(encoding="utf-8")
    )
    non_projection_roles = sorted(
        {
            artifact["role"]
            for artifact in manifest["artifacts"]
            if artifact["rights"]["attributionIds"] == ["geonames-fixture"]
        }
    )
    attribution["records"].append(
        {
            "attributionId": "geonames-fixture",
            "sourceId": "fixture/geonames",
            "title": "Synthetic settlement and release metadata",
            "sourceUrl": "https://fixtures.searise.invalid/geonames",
            "licence": {
                "spdxId": "CC-BY-4.0",
                "name": "Creative Commons Attribution 4.0 International",
                "url": "https://creativecommons.org/licenses/by/4.0/",
            },
            "attributionText": "Synthetic fixture metadata; not real-source output.",
            "redistribution": "allowed",
            "sourceSha256": "8" * 64,
            "appliesToRoles": non_projection_roles,
        }
    )
    return attribution


def _valid_stac_bundle(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    fixture_dir = PUBLIC_CONTRACT_DIR / "fixtures" / "valid"
    catalog = json.loads((fixture_dir / "stac-catalog.json").read_text(encoding="utf-8"))
    collection = json.loads(
        (fixture_dir / "stac-collection.json").read_text(encoding="utf-8")
    )
    item_template = json.loads(
        (fixture_dir / "stac-item.json").read_text(encoding="utf-8")
    )
    artifacts = {artifact["artifactId"]: artifact for artifact in manifest["artifacts"]}
    items = []
    for dataset in manifest["datasets"]:
        scenario = dataset["scenario"]
        horizon = dataset["horizon"]
        item = copy.deepcopy(item_template)
        item["id"] = f"{scenario}-{horizon}"
        item["properties"].update(
            {
                "datetime": f"{horizon}-01-01T00:00:00Z",
                "searise:scenario": scenario,
                "searise:horizon": horizon,
                "searise:source_member_sha256": artifacts[
                    dataset["analysisArtifactId"]
                ]["projectionContext"]["source"]["memberSha256"],
            }
        )
        for key, artifact_id in (
            ("analysis", dataset["analysisArtifactId"]),
            ("visual", dataset["visualArtifactId"]),
            ("table", dataset["analyticalArtifactId"]),
        ):
            artifact = artifacts[artifact_id]
            item["assets"][key].update(
                {
                    "href": f"../../{artifact['path']}",
                    "file:size": artifact["byteSize"],
                    "checksum:multihash": f"1220{artifact['sha256']}",
                    "searise:artifact_id": artifact_id,
                }
            )
        items.append(item)
    return catalog, collection, items


def test_manifest_schema_accepts_one_complete_synthetic_release_inventory() -> None:
    manifest = _valid_manifest()

    _public_contract_validator("manifest.schema.json").validate(manifest)

    assert len(manifest["datasets"]) == 9
    assert len(manifest["artifacts"]) == 41


def test_manifest_stac_and_rights_semantics_accept_one_complete_inventory() -> None:
    manifest = _valid_manifest()
    attribution = _valid_attribution_for_manifest(manifest)
    catalog, collection, items = _valid_stac_bundle(manifest)

    summary = validate_public_manifest(manifest, schema_directory=PUBLIC_CONTRACT_DIR)
    validate_release_rights(
        manifest,
        attribution,
        schema_directory=PUBLIC_CONTRACT_DIR,
    )
    validate_release_stac(
        manifest,
        catalog,
        collection,
        items,
        schema_directory=PUBLIC_CONTRACT_DIR,
    )

    assert summary.data_release_id == manifest["dataReleaseId"]
    assert summary.artifact_count == 41
    assert summary.dataset_count == 9


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest["artifacts"][1].__setitem__(
                "artifactId", manifest["artifacts"][0]["artifactId"]
            ),
            "artifact IDs must be unique",
        ),
        (
            lambda manifest: manifest["artifacts"][-1].__setitem__(
                "path", manifest["artifacts"][-2]["path"]
            ),
            "artifact paths must be unique",
        ),
        (
            lambda manifest: manifest["artifacts"][0].__setitem__(
                "dataReleaseId", "searise-europe-v1.0.1-20260810-c096aeab4e09"
            ),
            "mismatched release ID",
        ),
        (
            lambda manifest: manifest["artifacts"][1]["projectionContext"].__setitem__(
                "scenario", "ssp5-85"
            ),
            "contradicts its dataset context",
        ),
        (
            lambda manifest: manifest["artifacts"][3].__setitem__(
                "path", "stac/items/ssp1-26-2030-wrong.json"
            ),
            "contradicts its dataset path",
        ),
    ],
)
def test_manifest_semantics_reject_cross_document_contradictions(
    mutate: Callable[[dict[str, Any]], object],
    message: str,
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)

    with pytest.raises(PublicReleaseContractError, match=message):
        validate_public_manifest(manifest, schema_directory=PUBLIC_CONTRACT_DIR)


def test_release_rights_reject_role_not_covered_by_attribution() -> None:
    manifest = _valid_manifest()
    attribution = _valid_attribution_for_manifest(manifest)
    attribution["records"][1]["appliesToRoles"].remove("stac-item")

    with pytest.raises(PublicReleaseContractError, match="does not cover role stac-item"):
        validate_release_rights(
            manifest,
            attribution,
            schema_directory=PUBLIC_CONTRACT_DIR,
        )


def test_release_artifact_integrity_rejects_tampered_bytes(tmp_path: Path) -> None:
    manifest = _valid_manifest()
    for artifact in manifest["artifacts"]:
        path = tmp_path / artifact["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (artifact["artifactId"] + "\n").encode()
        path.write_bytes(payload)
        artifact["byteSize"] = len(payload)
        artifact["sha256"] = hashlib.sha256(payload).hexdigest()

    validate_public_manifest(manifest, schema_directory=PUBLIC_CONTRACT_DIR)
    validate_release_artifacts(manifest, release_root=tmp_path)

    first = manifest["artifacts"][0]
    (tmp_path / first["path"]).write_bytes(b"tampered but same declared identity\n")
    with pytest.raises(PublicReleaseContractError, match="byte size differs|SHA-256 differs"):
        validate_release_artifacts(manifest, release_root=tmp_path)


def test_release_stac_rejects_asset_identity_drift() -> None:
    manifest = _valid_manifest()
    catalog, collection, items = _valid_stac_bundle(manifest)
    items[0]["assets"]["analysis"]["checksum:multihash"] = "1220" + "0" * 64

    with pytest.raises(PublicReleaseContractError, match="mismatched analysis hash"):
        validate_release_stac(
            manifest,
            catalog,
            collection,
            items,
            schema_directory=PUBLIC_CONTRACT_DIR,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["datasets"].pop(),
        lambda manifest: manifest["datasets"][0].__setitem__("horizon", 2050),
        lambda manifest: manifest["releaseAuthority"].__setitem__(
            "releaseDisposition", "approved"
        ),
        lambda manifest: manifest["publication"].__setitem__(
            "releasePath", "https://provider.example/release"
        ),
        lambda manifest: manifest["contractArtifacts"].pop("qualitySummary"),
        lambda manifest: manifest["contractArtifacts"]["stacItems"].pop(),
        lambda manifest: manifest["artifacts"][0].__setitem__("path", "../escape.parquet"),
    ],
)
def test_manifest_schema_rejects_incomplete_or_unsafe_inventory(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)

    assert list(_public_contract_validator("manifest.schema.json").iter_errors(manifest))
