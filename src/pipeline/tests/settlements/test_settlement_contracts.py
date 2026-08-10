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

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "contracts" / "settlements" / "v2"
RELEASE_V1_DIR = REPO_ROOT / "contracts" / "release" / "v1"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str) -> Draft202012Validator:
    schemas = [_read(path) for path in CONTRACT_DIR.glob("*.schema.json")]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = next(schema for schema in schemas if schema["$id"].endswith(schema_name))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def _fixture_validator(path: Path) -> Draft202012Validator:
    document = _read(path)
    return _validator(document["$schema"].rsplit("/", maxsplit=1)[-1])


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


def _assert_search_semantics(document: dict[str, Any]) -> None:
    assert document["recordCount"] == len(document["documents"])


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
    names = {
        path.name for path in (CONTRACT_DIR / "fixtures" / "invalid").glob("*.json")
    }

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
    search = _read(
        CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    )

    assert search["geometryStatus"] == "selected-scope-approximation"
    assert search["publicationEligible"] is False

    search["dataProvenanceClass"] = "real-source"
    _validator("artifact-envelope.schema.json").validate(search)


def test_artifact_goldens_have_self_consistent_counts_and_schema_identity() -> None:
    geoparquet = _read(
        CONTRACT_DIR / "fixtures" / "valid" / "settlement-geoparquet.json"
    )
    canonical_fields = _lexicographic_key_json(geoparquet["arrowFields"])
    search = _read(
        CONTRACT_DIR / "fixtures" / "valid" / "settlement-search-shard.json"
    )

    assert geoparquet["arrowFieldsCanonicalization"] == "lexicographic-key-json-v1"
    assert geoparquet["arrowFieldsJsonSha256"] == hashlib.sha256(
        canonical_fields
    ).hexdigest()
    _assert_search_semantics(search)

    inconsistent = copy.deepcopy(search)
    inconsistent["recordCount"] += 1
    with pytest.raises(AssertionError):
        _assert_search_semantics(inconsistent)
