"""Validate the versioned public settlement artifact contracts."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from searise_pipeline.settlements.contract_semantics import (
    SettlementContractSemanticError,
    validate_settlement_search_shard_semantics,
)
from searise_pipeline.settlements.reconciliation import (
    CATALOGUE_REJECTION_REASONS,
    SPATIAL_REJECTION_REASONS,
    SettlementReconciliationError,
    validate_reconciliation_report_semantics,
)

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "contracts" / "settlements" / "v2"
V3_CONTRACT_DIR = REPO_ROOT / "contracts" / "settlements" / "v3"
V4_CONTRACT_DIR = REPO_ROOT / "contracts" / "settlements" / "v4"
RELEASE_V1_DIR = REPO_ROOT / "contracts" / "release" / "v1"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str, contract_dir: Path = CONTRACT_DIR) -> Draft202012Validator:
    schemas = [_read(path) for path in contract_dir.glob("*.schema.json")]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = next(schema for schema in schemas if schema["$id"].endswith(schema_name))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def _fixture_validator(path: Path) -> Draft202012Validator:
    document = _read(path)
    contract_dir = path.parents[2]
    return _validator(document["$schema"].rsplit("/", maxsplit=1)[-1], contract_dir)


def _v1_validator(schema_name: str) -> Draft202012Validator:
    schemas = [_read(path) for path in RELEASE_V1_DIR.glob("*.schema.json")]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = next(schema for schema in schemas if schema["$id"].endswith(schema_name))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def _lexicographic_key_json(document: Any) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _set_nested(document: dict[str, Any], path: tuple[Any, ...], value: Any) -> None:
    target: Any = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def test_settlement_v2_schemas_pass_the_draft_2020_12_metaschema() -> None:
    schemas = sorted(CONTRACT_DIR.glob("*.schema.json"))

    assert [path.name for path in schemas] == [
        "artifact-envelope.schema.json",
        "place.schema.json",
    ]
    for path in schemas:
        Draft202012Validator.check_schema(_read(path))


def test_negative_fixture_matrix_covers_public_compatibility_boundaries() -> None:
    names = {path.name for path in (CONTRACT_DIR / "fixtures" / "invalid").glob("*.json")}

    assert names == {
        "coastal-shard-inland-document.json",
        "invalid-approximation-publication.json",
        "invalid-arrow-fields-json-sha.json",
        "unsupported-geoparquet-version.json",
        "unsupported-schema-version.json",
        "unsupported-search-serialization.json",
    }


@pytest.mark.parametrize(
    "fixture_path",
    sorted((CONTRACT_DIR / "fixtures" / "valid").glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_accepts_every_settlement_v2_golden(fixture_path: Path) -> None:
    document = _read(fixture_path)

    _fixture_validator(fixture_path).validate(document)


@pytest.mark.parametrize(
    "fixture_path",
    sorted((CONTRACT_DIR / "fixtures" / "invalid").glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_rejects_every_negative_settlement_v2_fixture(fixture_path: Path) -> None:
    document = _read(fixture_path)

    assert list(_fixture_validator(fixture_path).iter_errors(document))


@pytest.mark.parametrize(
    ("fixture_name", "path", "supported"),
    [
        ("coastal-shard-inland-document.json", ("documents", 0, "isCoastal"), True),
        ("invalid-approximation-publication.json", ("publicationEligible",), False),
        (
            "invalid-arrow-fields-json-sha.json",
            ("arrowFieldsJsonSha256",),
            "48aeb7651b8bfd7ba365d92187bd3980b9357dc5396f9309275b6a5774eb42f2",
        ),
        ("unsupported-geoparquet-version.json", ("formatVersion",), "1.1.0"),
        ("unsupported-schema-version.json", ("schemaVersion",), "2.0.0"),
        (
            "unsupported-search-serialization.json",
            ("engine", "serializationVersion"),
            "1",
        ),
    ],
)
def test_each_negative_fixture_is_otherwise_contract_valid(
    fixture_name: str, path: tuple[Any, ...], supported: Any
) -> None:
    fixture_path = CONTRACT_DIR / "fixtures" / "invalid" / fixture_name
    document = _read(fixture_path)

    _set_nested(document, path, supported)

    _fixture_validator(fixture_path).validate(document)


@pytest.mark.parametrize(
    ("fixture_name", "field", "unsupported"),
    [
        ("settlement-geoparquet.json", "formatVersion", "2.0.0"),
        ("settlement-search-shard.json", "formatVersion", "2.0.0"),
        ("settlement-search-shard.json", "schemaVersion", "2.1.0"),
    ],
)
def test_artifact_compatibility_fails_closed(
    fixture_name: str, field: str, unsupported: str
) -> None:
    path = CONTRACT_DIR / "fixtures" / "valid" / fixture_name
    document = copy.deepcopy(_read(path))
    document[field] = unsupported

    assert list(_fixture_validator(path).iter_errors(document))


def test_search_engine_serialization_identity_fails_closed() -> None:
    path = CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    document = copy.deepcopy(_read(path))
    document["engine"]["serializationVersion"] = "2"

    assert list(_fixture_validator(path).iter_errors(document))


def test_coastal_shard_rejects_inland_documents() -> None:
    path = CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    document = copy.deepcopy(_read(path))
    document["catalogMembership"] = "europe-coastal"
    _fixture_validator(path).validate(document)

    document["documents"][0]["isCoastal"] = False

    assert list(_fixture_validator(path).iter_errors(document))


def test_v1_place_contract_stays_closed_instead_of_accepting_v2_fields() -> None:
    document = _read(RELEASE_V1_DIR / "fixtures" / "valid" / "search-record.json")
    document["sourceSpelling"] = "Harbor Fixture"

    assert list(_v1_validator("search-record.schema.json").iter_errors(document))


def test_approximate_geometry_golden_is_not_publication_eligible() -> None:
    search = _read(CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json")

    assert search["geometryStatus"] == "selected-scope-approximation"
    assert search["publicationEligible"] is False

    search["dataProvenanceClass"] = "real-source"
    _validator("artifact-envelope.schema.json").validate(search)


def test_artifact_goldens_have_self_consistent_counts_and_schema_identity() -> None:
    geoparquet = _read(CONTRACT_DIR / "fixtures" / "valid" / "settlement-geoparquet.json")
    canonical_fields = _lexicographic_key_json(geoparquet["arrowFields"])
    search = _read(CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json")

    assert geoparquet["arrowFieldsCanonicalization"] == "lexicographic-key-json-v1"
    assert geoparquet["arrowFieldsJsonSha256"] == hashlib.sha256(canonical_fields).hexdigest()
    validate_settlement_search_shard_semantics(search)


def test_settlement_v3_schemas_pass_the_draft_2020_12_metaschema() -> None:
    schemas = sorted(V3_CONTRACT_DIR.glob("*.schema.json"))

    assert [path.name for path in schemas] == [
        "artifact-envelope.schema.json",
        "place.schema.json",
        "reconciliation-report.schema.json",
    ]
    for path in schemas:
        Draft202012Validator.check_schema(_read(path))


def test_v3_negative_fixture_matrix_covers_successor_boundaries() -> None:
    names = {path.name for path in (V3_CONTRACT_DIR / "fixtures" / "invalid").glob("*.json")}

    assert names == {
        "empty-membership-shard-place.json",
        "fractional-coast-distance.json",
        "invalid-canonical-name-role.json",
        "invalid-owner-approval-claim.json",
        "invalid-shoreline-identity.json",
        "missing-search-feature-code.json",
        "unsupported-search-engine.json",
    }


@pytest.mark.parametrize(
    "fixture_path",
    sorted((V3_CONTRACT_DIR / "fixtures" / "valid").glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_accepts_every_settlement_v3_golden(fixture_path: Path) -> None:
    _fixture_validator(fixture_path).validate(_read(fixture_path))


def test_v3_search_semantic_vectors_are_schema_valid_and_shared() -> None:
    valid_path = V3_CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    mismatch_path = V3_CONTRACT_DIR / "fixtures" / "semantic-invalid" / "record-count-mismatch.json"
    assert {path.name for path in mismatch_path.parent.glob("*.json")} == {
        "reconciliation-source-flow-mismatch.json",
        "record-count-mismatch.json",
    }
    valid = _read(valid_path)
    mismatch = _read(mismatch_path)

    _fixture_validator(valid_path).validate(valid)
    _fixture_validator(mismatch_path).validate(mismatch)
    validate_settlement_search_shard_semantics(valid)
    with pytest.raises(SettlementContractSemanticError, match="recordCount"):
        validate_settlement_search_shard_semantics(mismatch)


def test_v3_reconciliation_semantic_vector_is_schema_valid_but_arithmetically_invalid() -> None:
    path = (
        V3_CONTRACT_DIR
        / "fixtures"
        / "semantic-invalid"
        / "reconciliation-source-flow-mismatch.json"
    )
    document = _read(path)

    _fixture_validator(path).validate(document)
    with pytest.raises(SettlementReconciliationError, match="catalogue accepted plus"):
        validate_reconciliation_report_semantics(document)


@pytest.mark.parametrize("ledger", ["catalogue", "spatial"])
def test_v3_reconciliation_schema_rejects_invented_rejection_reasons(ledger: str) -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / "settlement-reconciliation.json"
    document = _read(path)
    document["rejections"][ledger][0]["reason"] = f"invented-{ledger}-reason"

    assert list(_fixture_validator(path).iter_errors(document))


def test_v3_reconciliation_schema_and_semantic_reason_vocabularies_match() -> None:
    schema = _read(V3_CONTRACT_DIR / "reconciliation-report.schema.json")
    definitions = schema["$defs"]

    assert (
        frozenset(definitions["catalogueReasonBucket"]["properties"]["reason"]["enum"])
        == CATALOGUE_REJECTION_REASONS
    )
    assert (
        frozenset(
            {definitions["spatialReasonBucket"]["properties"]["reason"]["const"]}
        )
        == SPATIAL_REJECTION_REASONS
    )


@pytest.mark.parametrize(
    "fixture_path",
    sorted((V3_CONTRACT_DIR / "fixtures" / "invalid").glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_rejects_every_negative_settlement_v3_fixture(
    fixture_path: Path,
) -> None:
    assert list(_fixture_validator(fixture_path).iter_errors(_read(fixture_path)))


@pytest.mark.parametrize(
    ("fixture_name", "path", "supported"),
    [
        (
            "empty-membership-shard-place.json",
            ("spatialClassification", "catalogMembership"),
            ["europe-core"],
        ),
        (
            "fractional-coast-distance.json",
            ("spatialClassification", "distanceToCoastMeters"),
            26000,
        ),
        (
            "invalid-canonical-name-role.json",
            ("canonicalName", "role"),
            "canonical",
        ),
        (
            "invalid-owner-approval-claim.json",
            ("ownerApprovalClaim",),
            False,
        ),
        (
            "invalid-shoreline-identity.json",
            ("spatialIdentity", "shorelineGeometry", "sha256"),
            "53972730f9af3f541b67ee67a4653fb5a21ac52011d33c4372eb9fa84bc331ac",
        ),
        (
            "missing-search-feature-code.json",
            ("documents", 0, "featureCode"),
            "PPL",
        ),
        (
            "unsupported-search-engine.json",
            ("engine", "serializationVersion"),
            "2",
        ),
    ],
)
def test_each_v3_negative_fixture_is_otherwise_contract_valid(
    fixture_name: str, path: tuple[Any, ...], supported: Any
) -> None:
    fixture_path = V3_CONTRACT_DIR / "fixtures" / "invalid" / fixture_name
    document = _read(fixture_path)
    _set_nested(document, path, supported)

    _fixture_validator(fixture_path).validate(document)


@pytest.mark.parametrize(
    ("role", "field"),
    [
        ("supportGeometry", "artifactId"),
        ("supportGeometry", "version"),
        ("supportGeometry", "sha256"),
        ("coastalGeometry", "artifactId"),
        ("coastalGeometry", "version"),
        ("coastalGeometry", "sha256"),
        ("shorelineGeometry", "artifactId"),
        ("shorelineGeometry", "version"),
        ("shorelineGeometry", "sha256"),
    ],
)
def test_v3_spatial_artifact_identity_fails_closed(role: str, field: str) -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / "place.json"
    document = _read(path)
    document["spatialClassification"][role][field] = "unsupported"

    assert list(_fixture_validator(path).iter_errors(document))


@pytest.mark.parametrize(
    "field",
    [
        "canonicalGeometryClaim",
        "hazardExtentClaim",
        "scientificApprovalClaim",
        "ownerApprovalClaim",
        "publicationEligible",
    ],
)
def test_v3_approximation_cannot_claim_approval(field: str) -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    document = _read(path)
    document[field] = True

    assert list(_fixture_validator(path).iter_errors(document))


@pytest.mark.parametrize(
    ("field", "unsupported"),
    [("id", "unknown"), ("packageVersion", "2.0.0"), ("serializationVersion", "3")],
)
def test_v3_search_engine_descriptor_fails_closed(field: str, unsupported: str) -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    document = _read(path)
    document["engine"][field] = unsupported

    assert list(_fixture_validator(path).iter_errors(document))


def test_v3_audit_membership_and_search_projection_boundaries() -> None:
    place_path = V3_CONTRACT_DIR / "fixtures" / "valid" / "place.json"
    place = _read(place_path)
    _fixture_validator(place_path).validate(place)
    assert place["recordRole"] == "source-audit"
    assert place["spatialClassification"]["catalogMembership"] == []

    shard_path = V3_CONTRACT_DIR / "fixtures" / "valid" / "shard-place.json"
    shard = _read(shard_path)
    _fixture_validator(shard_path).validate(shard)
    assert shard["recordRole"] == "search-shard"
    assert shard["spatialClassification"]["catalogMembership"] == ["europe-core"]

    empty_path = V3_CONTRACT_DIR / "fixtures" / "invalid" / "empty-membership-shard-place.json"
    errors = list(_fixture_validator(empty_path).iter_errors(_read(empty_path)))
    membership_error = next(error for error in errors if "should be non-empty" in error.message)
    assert list(membership_error.absolute_path) == [
        "spatialClassification",
        "catalogMembership",
    ]

    search_path = V3_CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    search = _read(search_path)
    document = search["documents"][0]
    assert document["featureCode"] == "PPL"
    assert type(document["distanceToCoastMeters"]) is int
    for field in ("featureCode", "distanceToCoastMeters"):
        mutated = copy.deepcopy(search)
        del mutated["documents"][0][field]
        assert list(_fixture_validator(search_path).iter_errors(mutated))


def test_v3_geoparquet_carries_source_and_spatial_identity() -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / "settlement-geoparquet.json"
    document = _read(path)
    field_types = {field["name"]: field["type"] for field in document["arrowFields"]}

    source_updated = next(
        field for field in document["arrowFields"] if field["name"] == "source_updated_at"
    )
    assert source_updated == {
        "name": "source_updated_at",
        "type": "utf8",
        "nullable": False,
    }
    assert field_types["distance_to_coast_m"] == "int64"
    for role in ("support", "coastal", "shoreline"):
        assert field_types[f"{role}_geometry_id"] == "utf8"
        assert field_types[f"{role}_geometry_version"] == "utf8"
        assert field_types[f"{role}_geometry_sha256"] == "utf8"
    assert field_types["spatial_predicate"] == "utf8"
    assert field_types["distance_method_version"] == "utf8"
    assert (
        document["arrowFieldsJsonSha256"]
        == hashlib.sha256(_lexicographic_key_json(document["arrowFields"])).hexdigest()
    )


def test_v3_source_update_date_is_required_and_non_null() -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / "place.json"
    document = _read(path)
    document["sourceUpdatedAt"] = None

    assert list(_fixture_validator(path).iter_errors(document))


@pytest.mark.parametrize("fixture_name", ["place.json", "settlement-search-shard.json"])
def test_v3_contracts_reject_unknown_fields(fixture_name: str) -> None:
    path = V3_CONTRACT_DIR / "fixtures" / "valid" / fixture_name
    document = _read(path)
    document["unknownField"] = True

    assert list(_fixture_validator(path).iter_errors(document))


def test_v3_representative_engine_is_an_exact_fixture_descriptor() -> None:
    schema = _read(V3_CONTRACT_DIR / "artifact-envelope.schema.json")
    engine = schema["$defs"]["searchShard"]["allOf"][1]["properties"]["engine"]
    descriptor = {field: definition["const"] for field, definition in engine["properties"].items()}

    assert descriptor == {
        "id": "representative-json",
        "packageVersion": "1.0.0",
        "serializationVersion": "2",
    }
    assert "does not select a production browser search engine" in engine["$comment"]


def test_settlement_v4_public_search_schema_and_goldens_are_valid() -> None:
    schemas = sorted(V4_CONTRACT_DIR.glob("*.schema.json"))
    assert [path.name for path in schemas] == ["search-artifact.schema.json"]
    Draft202012Validator.check_schema(_read(schemas[0]))

    paths = sorted((V4_CONTRACT_DIR / "fixtures" / "valid").glob("*.json"))
    assert [path.name for path in paths] == [
        "settlement-browser-search-shard-set-receipt.json",
        "settlement-browser-search-shard.json",
        "settlement-search-projection-authority.json",
    ]
    for path in paths:
        _fixture_validator(path).validate(_read(path))


def test_settlement_v4_search_semantics_and_versions_fail_closed() -> None:
    path = (
        V4_CONTRACT_DIR
        / "fixtures"
        / "valid"
        / "settlement-browser-search-shard.json"
    )
    document = _read(path)
    validate_settlement_search_shard_semantics(document)

    mismatch = copy.deepcopy(document)
    mismatch["recordCount"] = 2
    _fixture_validator(path).validate(mismatch)
    with pytest.raises(SettlementContractSemanticError, match="recordCount"):
        validate_settlement_search_shard_semantics(mismatch)

    for field, value in (
        ("schemaVersion", "5.0.0"),
        ("formatVersion", "settlement-browser-search-shard-v3"),
    ):
        unsupported = copy.deepcopy(document)
        unsupported[field] = value
        assert list(_fixture_validator(path).iter_errors(unsupported))

    unsupported = copy.deepcopy(document)
    unsupported["engine"]["engineId"] = "representative-json"
    assert list(_fixture_validator(path).iter_errors(unsupported))
