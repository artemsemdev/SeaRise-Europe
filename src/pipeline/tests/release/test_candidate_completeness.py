"""Shared golden vectors for the Phase 1 candidate completeness boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from searise_pipeline.release import (
    CandidateCompletenessError,
    validate_candidate_completeness,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPO_ROOT / "contracts/candidate-completeness/v1"
SCHEMA = CONTRACT_ROOT / "candidate.schema.json"
CONTRACT = json.loads((CONTRACT_ROOT / "required-artifacts.json").read_text())
VALID = json.loads(
    (CONTRACT_ROOT / "fixtures/valid/engineering-candidate.json").read_text()
)
VECTORS = json.loads(
    (CONTRACT_ROOT / "fixtures/vectors/negative-vectors.json").read_text()
)["vectors"]


def _value(document: Any, pointer: str) -> Any:
    value = document
    for part in pointer.removeprefix("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _apply(document: Mapping[str, Any], operations: list[Mapping[str, Any]]) -> Any:
    result = copy.deepcopy(document)
    for operation in operations:
        parts = operation["path"].removeprefix("/").split("/")
        parent = _value(result, "/" + "/".join(parts[:-1])) if len(parts) > 1 else result
        key = parts[-1]
        value = (
            copy.deepcopy(_value(result, operation["from"]))
            if operation["op"] == "copy"
            else copy.deepcopy(operation.get("value"))
        )
        if isinstance(parent, list):
            if operation["op"] == "remove":
                parent.pop(int(key))
            elif key == "-":
                parent.append(value)
            else:
                parent[int(key)] = value
        elif operation["op"] == "remove":
            del parent[key]
        else:
            parent[key] = value
    return result


def test_complete_engineering_candidate_is_accepted() -> None:
    summary = validate_candidate_completeness(VALID, CONTRACT, schema_path=SCHEMA)

    assert summary.artifact_count == 44
    assert summary.dataset_count == 9
    assert summary.manifest_written_last is True


@pytest.mark.parametrize("vector", VECTORS, ids=lambda vector: vector["id"])
def test_shared_negative_vectors_fail_closed(vector: Mapping[str, Any]) -> None:
    candidate = _apply(VALID, vector["operations"])

    with pytest.raises(CandidateCompletenessError) as error:
        validate_candidate_completeness(candidate, CONTRACT, schema_path=SCHEMA)

    assert error.value.code == vector["expectedCode"]


def test_noncanonical_geometry_policy_cannot_be_promoted() -> None:
    candidate = copy.deepcopy(VALID)
    candidate["geometryPolicy"]["canonical"] = True
    candidate["geometryPolicy"]["publicationEligible"] = True

    with pytest.raises(CandidateCompletenessError) as error:
        validate_candidate_completeness(candidate, CONTRACT, schema_path=SCHEMA)

    assert error.value.code == "geometry-policy"


def test_python_schema_rejects_malformed_nested_rights() -> None:
    candidate = copy.deepcopy(VALID)
    candidate["artifacts"][0]["rights"] = None
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    errors = list(Draft202012Validator(schema).iter_errors(candidate))

    assert errors
    assert list(errors[0].absolute_path) == ["artifacts", 0, "rights"]
