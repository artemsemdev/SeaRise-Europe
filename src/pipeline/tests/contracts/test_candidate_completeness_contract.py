from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = ROOT / "contracts/candidate-completeness/v1"
RELEASE_ROOT = ROOT / "contracts/release/v1"
SCHEMA = CONTRACT_ROOT / "candidate.schema.json"
INVENTORY = CONTRACT_ROOT / "required-artifacts.json"
FIXTURE = CONTRACT_ROOT / "fixtures/valid/engineering-candidate.json"
VECTORS = CONTRACT_ROOT / "fixtures/vectors/negative-vectors.json"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    schemas = [_read(RELEASE_ROOT / "defs.schema.json"), _read(SCHEMA)]
    registry = Registry()
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(schemas[-1], registry=registry)


def _artifact_signature(artifact: dict[str, Any]) -> tuple[Any, ...]:
    return (
        artifact["artifactId"],
        artifact["path"],
        artifact["role"],
        artifact["mediaType"],
        artifact["contentEncoding"],
        artifact["rights"]["attributionIds"],
    )


def _required_signature(artifact: dict[str, Any]) -> tuple[Any, ...]:
    return (
        artifact["artifactId"],
        artifact["path"],
        artifact["role"],
        artifact["mediaType"],
        artifact["contentEncoding"],
        artifact["attributionIds"],
    )


def _semantic_errors(candidate: dict[str, Any]) -> set[str]:
    contract = _read(INVENTORY)
    artifacts = candidate.get("artifacts", [])
    errors: set[str] = set()
    if list(map(_artifact_signature, artifacts)) != list(
        map(_required_signature, contract["requiredArtifacts"])
    ):
        errors.add("artifact-inventory")
    if len({item.get("artifactId") for item in artifacts}) != len(artifacts) or len(
        {item.get("path") for item in artifacts}
    ) != len(artifacts):
        errors.add("artifact-inventory")
    if any(
        item.get("dataReleaseId") != candidate.get("dataReleaseId")
        or item.get("dataProvenanceClass") != candidate.get("dataProvenanceClass")
        for item in artifacts
    ):
        errors.add("release-identity")
    if [item.get("writeSequence") for item in artifacts] != list(range(1, 54)):
        errors.add("manifest-order")
    if [item.get("artifactId") for item in artifacts[-3:]] != contract["terminalArtifactIds"]:
        errors.add("manifest-order")
    if candidate.get("manifest") != {
        "path": "manifest.json",
        "artifactCount": contract["artifactCount"],
        "writeSequence": contract["manifestWriteSequence"],
        "selfHashExcluded": True,
    }:
        errors.add("manifest-order")
    expected_subjects = sorted(
        (
            {"path": item["path"], "sha256": item["sha256"]}
            for item in artifacts
            if item.get("role") != "checksums"
        ),
        key=lambda item: item["path"],
    )
    checksum_inventory = candidate.get("checksumInventory", {})
    if checksum_inventory.get("subjects") != expected_subjects:
        errors.add("checksum-coverage")
    expected_bindings = [
        {
            "itemArtifactId": f"stac-item-{scenario}-{horizon}",
            "scenario": scenario,
            "horizon": horizon,
            "analysisArtifactId": f"projection-{scenario}-{horizon}-cog",
            "visualArtifactId": f"projection-{scenario}-{horizon}-pmtiles",
            "tableArtifactId": "projection-matrix-geoparquet",
        }
        for scenario in contract["scenarios"]
        for horizon in contract["horizons"]
    ]
    if candidate.get("stacBindings", {}).get("items") != expected_bindings:
        errors.add("stac-binding")
    sidecar_roles = set(contract["evidenceSidecarRolesExcludedFromManifest"])
    if sidecar_roles & {item.get("role") for item in artifacts}:
        errors.add("artifact-inventory")
    return errors


def _errors(candidate: dict[str, Any]) -> set[str]:
    errors = _semantic_errors(candidate)
    if list(_validator().iter_errors(candidate)):
        errors.add("candidate-schema")
    return errors


def _apply(document: dict[str, Any], operation: dict[str, Any]) -> None:
    tokens = [
        part.replace("~1", "/").replace("~0", "~") for part in operation["path"].split("/")[1:]
    ]
    target: Any = document
    for token in tokens[:-1]:
        target = target[int(token)] if isinstance(target, list) else target[token]
    final = tokens[-1]
    if operation["op"] == "remove":
        if isinstance(target, list):
            del target[int(final)]
        else:
            del target[final]
    elif operation["op"] == "replace":
        if isinstance(target, list):
            target[int(final)] = operation["value"]
        else:
            target[final] = operation["value"]
    else:
        raise AssertionError(f"unsupported fixture operation: {operation['op']}")


def test_candidate_fixture_matches_schema_and_exact_inventory() -> None:
    candidate = _read(FIXTURE)
    _validator().validate(candidate)
    assert _semantic_errors(candidate) == set()

    contract = _read(INVENTORY)
    artifacts = candidate["artifacts"]
    assert len(artifacts) == contract["artifactCount"] == 53
    assert len(candidate["checksumInventory"]["subjects"]) == 52
    assert sum(item["role"] == "projection-analysis-cog" for item in artifacts) == 9
    assert sum(item["role"] == "projection-visual-pmtiles" for item in artifacts) == 9
    assert sum(item["role"] == "projection-geoparquet" for item in artifacts) == 1
    search_shards = {
        item["artifactId"] for item in artifacts if item["role"] == "settlement-search-index"
    }
    assert search_shards == {
        "settlements-europe-core",
        "settlements-europe-coastal",
    }


def test_inventory_uses_current_release_roles_and_media_types() -> None:
    definitions = _read(RELEASE_ROOT / "defs.schema.json")["$defs"]
    allowed_roles = set(definitions["artifactRole"]["enum"])
    allowed_media_types = set(definitions["mediaType"]["enum"])
    required = _read(INVENTORY)["requiredArtifacts"]

    assert {item["role"] for item in required} <= allowed_roles
    assert {item["mediaType"] for item in required} <= allowed_media_types
    assert len({item["artifactId"] for item in required}) == len(required)
    assert len({item["path"] for item in required}) == len(required)
    assert (
        sorted({attribution for item in required for attribution in item["attributionIds"]})
        == _read(INVENTORY)["requiredAttributionIds"]
    )
    assert sum(item["role"] == "source-receipt" for item in required) == 7


def test_supply_chain_gate_is_required_without_recursive_sidecars() -> None:
    candidate = _read(FIXTURE)
    contract = _read(INVENTORY)

    assert candidate["supplyChainGate"] == {
        "status": "required-pending-pair-validation",
        "evidenceEnvelopeContract": contract["requiredEvidenceEnvelopeContract"],
        "requiredForPublication": True,
        "candidateManifestSubject": "manifest.json",
        "pairValidation": {
            "status": "pending-dependent-validator",
            "requiredBindings": [
                "candidateId",
                "dataReleaseId",
                "dataProvenanceClass",
                "actualManifestSha256",
            ],
        },
        "excludedSidecarRoles": contract["evidenceSidecarRolesExcludedFromManifest"],
        "exclusionReason": "prevent-recursive-candidate-manifest-hashing",
    }
    assert candidate["publicationClaim"] is False
    assert candidate["geometryPolicy"]["publicationEligible"] is False
    assert candidate["geometryPolicy"]["hazardExtentClaim"] is False


def test_every_negative_vector_fails_with_its_expected_code() -> None:
    fixture = _read(FIXTURE)
    vectors = _read(VECTORS)["vectors"]
    assert len({vector["id"] for vector in vectors}) == len(vectors)
    for vector in vectors:
        candidate = copy.deepcopy(fixture)
        for operation in vector["operations"]:
            _apply(candidate, operation)
        assert vector["expectedCode"] in _errors(candidate), vector["id"]
