from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = ROOT / "contracts/candidate-completeness/v1"
CANDIDATE_SCHEMA = CONTRACT_ROOT / "candidate.schema.json"
REQUIRED_ARTIFACTS = CONTRACT_ROOT / "required-artifacts.json"
GOLDEN = CONTRACT_ROOT / "fixtures/valid/engineering-candidate.json"
RELEASE_SCHEMA_ROOT = ROOT / "contracts/release/v1"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_registry(*schemas: dict[str, Any]) -> Registry:
    registry = Registry()
    for schema in schemas:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def test_candidate_golden_composes_the_full_release_artifact_contract() -> None:
    candidate_schema = _read(CANDIDATE_SCHEMA)
    artifact_schema = _read(RELEASE_SCHEMA_ROOT / "artifact.schema.json")
    attribution_schema = _read(RELEASE_SCHEMA_ROOT / "attribution.schema.json")
    definitions_schema = _read(RELEASE_SCHEMA_ROOT / "defs.schema.json")
    schemas = (
        definitions_schema,
        artifact_schema,
        attribution_schema,
        candidate_schema,
    )
    for schema in schemas:
        Draft202012Validator.check_schema(schema)

    registry = _schema_registry(*schemas)
    candidate = _read(GOLDEN)
    Draft202012Validator(
        candidate_schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(candidate)

    contract = _read(REQUIRED_ARTIFACTS)
    attribution_document = {
        "$schema": attribution_schema["$id"],
        "schemaVersion": "1.0.0",
        "dataReleaseId": candidate["dataReleaseId"],
        "dataProvenanceClass": candidate["dataProvenanceClass"],
        "records": contract["requiredAttributions"],
    }
    Draft202012Validator(
        attribution_schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(attribution_document)

    contract_record = next(
        record
        for record in contract["requiredAttributions"]
        if record["attributionId"]
        == "searise-europe-candidate-completeness-v1"
    )
    assert contract_record["sourceSha256"] == hashlib.sha256(
        CANDIDATE_SCHEMA.read_bytes()
    ).hexdigest()


def test_candidate_golden_seals_the_exact_inventory_before_manifest() -> None:
    contract = _read(REQUIRED_ARTIFACTS)
    candidate = _read(GOLDEN)
    envelopes = candidate["artifacts"]
    descriptors = [envelope["descriptor"] for envelope in envelopes]
    expected = {
        artifact["artifactId"]: artifact
        for artifact in contract["requiredArtifacts"]
    }

    assert contract["artifactCount"] == 47 == len(envelopes)
    assert len({item["artifactId"] for item in descriptors}) == 47
    assert len({item["path"] for item in descriptors}) == 47
    assert [envelope["writeSequence"] for envelope in envelopes] == list(range(1, 48))

    for envelope in envelopes:
        descriptor = envelope["descriptor"]
        required = expected[descriptor["artifactId"]]
        assert (
            descriptor["path"],
            descriptor["role"],
            descriptor["mediaType"],
            envelope["contentEncoding"],
            descriptor["rights"]["attributionIds"],
        ) == (
            required["path"],
            required["role"],
            required["mediaType"],
            required["contentEncoding"],
            required["attributionIds"],
        )
        assert descriptor["dataReleaseId"] == candidate["dataReleaseId"]
        assert descriptor["dataProvenanceClass"] == candidate["dataProvenanceClass"]
        assert envelope["observedByteSize"] == descriptor["byteSize"]
        assert envelope["observedSha256"] == descriptor["sha256"]

    checksum_subjects = candidate["checksumInventory"]["subjects"]
    expected_subjects = sorted(
        (
            {"path": descriptor["path"], "sha256": descriptor["sha256"]}
            for descriptor in descriptors
            if descriptor["role"] != "checksums"
        ),
        key=lambda subject: subject["path"],
    )
    assert len(checksum_subjects) == contract["checksumSubjectCount"] == 46
    assert checksum_subjects == expected_subjects

    assert candidate["gateReportSemantics"]["validatedArtifactCount"] == 44
    assert candidate["manifest"] == {
        "path": "manifest.json",
        "artifactCount": 47,
        "writeSequence": 48,
    }
    assert candidate["supplyChainBoundary"] == {
        "status": "deferred",
        "issue": 53,
        "roles": contract["forbiddenDeferredRoles"],
        "includedInArtifactInventory": False,
    }
    assert not set(contract["forbiddenDeferredRoles"]) & {
        descriptor["role"] for descriptor in descriptors
    }
