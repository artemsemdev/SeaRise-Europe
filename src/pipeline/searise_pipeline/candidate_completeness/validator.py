"""Fail-closed, offline validation of pre-sign candidate metadata only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "candidate-completeness" / "v1"

_SCHEMA_URL = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/"
    "candidate-completeness/v1/candidate.schema.json"
)
_CONTRACT_ID = "phase-1-pre-sign-candidate-completeness-v1"
_ARTIFACT_COUNT = 53
_CHECKSUM_SUBJECT_COUNT = 52
_MANIFEST_SEQUENCE = 54
_TERMINAL_ARTIFACT_IDS = (
    "release-gate-report-json",
    "release-gate-report-markdown",
    "checksums",
)
_PAIR_GATE = {
    "status": "required-pending-pair-validation",
    "evidenceEnvelopeContract": "contracts/supply-chain/v1/evidence-envelope.schema.json",
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
    "excludedSidecarRoles": ["provenance", "signature", "software-bill-of-materials"],
    "exclusionReason": "prevent-recursive-candidate-manifest-hashing",
}


class CandidateContractError(ValueError):
    """A candidate or its local contract violates a fail-closed boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CandidateSummary:
    """Stable metadata returned after candidate-only validation succeeds."""

    candidate_id: str
    data_release_id: str
    artifact_count: int


class _DuplicateKeyError(ValueError):
    pass


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    """Read one strict JSON object without duplicate keys or JSON extensions."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonstandard_constant,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _fail("candidate-json", f"cannot read strict JSON object {path}: {exc}")
    if not isinstance(document, dict):
        _fail("candidate-json", f"JSON root must be an object: {path}")
    return document


def load_candidate(path: Path) -> dict[str, Any]:
    """Load a strict candidate JSON document; this does not read release artifacts."""
    return _load_json(path)


def _validator(contract_root: Path) -> Draft202012Validator:
    release_schema = _load_json(contract_root.parents[1] / "release" / "v1" / "defs.schema.json")
    candidate_schema = _load_json(contract_root / "candidate.schema.json")
    try:
        Draft202012Validator.check_schema(release_schema)
        Draft202012Validator.check_schema(candidate_schema)
    except Exception as exc:
        # jsonschema's schema-error type is not stable across supported versions.
        _fail("candidate-contract", f"invalid local schema: {exc}")
    registry = Registry().with_resources(
        (
            (release_schema["$id"], Resource.from_contents(release_schema)),
            (candidate_schema["$id"], Resource.from_contents(candidate_schema)),
        )
    )
    return Draft202012Validator(candidate_schema, registry=registry)


def _validate_inventory(contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    expected = {
        "schemaVersion": "1.0.0",
        "contractId": _CONTRACT_ID,
        "candidateSchema": _SCHEMA_URL,
        "artifactCount": _ARTIFACT_COUNT,
        "preGateArtifactCount": 50,
        "checksumSubjectCount": _CHECKSUM_SUBJECT_COUNT,
        "manifestWriteSequence": _MANIFEST_SEQUENCE,
        "terminalArtifactIds": list(_TERMINAL_ARTIFACT_IDS),
        "requiredEvidenceEnvelopeContract": _PAIR_GATE["evidenceEnvelopeContract"],
        "evidenceSidecarRolesExcludedFromManifest": _PAIR_GATE["excludedSidecarRoles"],
        "scenarios": ["ssp1-26", "ssp2-45", "ssp5-85"],
        "horizons": [2030, 2050, 2100],
    }
    for field, value in expected.items():
        if contract.get(field) != value:
            _fail("candidate-contract", f"inventory field differs: {field}")
    artifacts = contract.get("requiredArtifacts")
    if not isinstance(artifacts, list) or len(artifacts) != _ARTIFACT_COUNT:
        _fail("candidate-contract", "inventory must declare exactly 53 artifacts")
    if not all(isinstance(item, Mapping) for item in artifacts):
        _fail("candidate-contract", "inventory artifacts must be objects")
    identifiers = [item.get("artifactId") for item in artifacts]
    paths = [item.get("path") for item in artifacts]
    if len(set(identifiers)) != len(artifacts):
        _fail("candidate-contract", "inventory artifact IDs must be unique")
    if len(set(paths)) != len(artifacts):
        _fail("candidate-contract", "inventory artifact paths must be unique")
    expected_attribution_ids = sorted(
        {attribution for item in artifacts for attribution in item.get("attributionIds", [])}
    )
    if contract.get("requiredAttributionIds") != expected_attribution_ids:
        _fail("candidate-contract", "inventory required attribution identities differ")
    return artifacts


def _schema_error(candidate: Mapping[str, Any], contract_root: Path) -> str | None:
    errors = sorted(
        _validator(contract_root).iter_errors(candidate),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return None
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "$"
    return f"{location}: {error.message}"


def _is_count_only_schema_error(message: str) -> bool:
    return (message.startswith("artifacts:") and "is too short" in message) or (
        message.startswith("checksumInventory.subjects:") and "is too short" in message
    )


def _artifact_signature(artifact: Mapping[str, Any]) -> tuple[Any, ...]:
    rights = artifact.get("rights")
    attribution_ids = rights.get("attributionIds") if isinstance(rights, Mapping) else None
    return (
        artifact.get("artifactId"),
        artifact.get("path"),
        artifact.get("role"),
        artifact.get("mediaType"),
        artifact.get("contentEncoding"),
        attribution_ids,
    )


def _required_signature(artifact: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        artifact.get("artifactId"),
        artifact.get("path"),
        artifact.get("role"),
        artifact.get("mediaType"),
        artifact.get("contentEncoding"),
        artifact.get("attributionIds"),
    )


def _semantic_code(candidate: Mapping[str, Any], required: list[Mapping[str, Any]]) -> str | None:
    artifacts = candidate.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    if [_artifact_signature(item) if isinstance(item, Mapping) else () for item in artifacts] != [
        _required_signature(item) for item in required
    ]:
        return "artifact-inventory"
    ids = [item.get("artifactId") for item in artifacts if isinstance(item, Mapping)]
    paths = [item.get("path") for item in artifacts if isinstance(item, Mapping)]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        return "artifact-inventory"
    release_id = candidate.get("dataReleaseId")
    provenance = candidate.get("dataProvenanceClass")
    if any(
        item.get("dataReleaseId") != release_id or item.get("dataProvenanceClass") != provenance
        for item in artifacts
        if isinstance(item, Mapping)
    ):
        return "release-identity"
    if [item.get("writeSequence") for item in artifacts if isinstance(item, Mapping)] != list(
        range(1, _ARTIFACT_COUNT + 1)
    ) or [item.get("artifactId") for item in artifacts[-3:] if isinstance(item, Mapping)] != list(
        _TERMINAL_ARTIFACT_IDS
    ):
        return "manifest-order"
    expected_subjects = sorted(
        (
            {"path": item["path"], "sha256": item["sha256"]}
            for item in artifacts
            if isinstance(item, Mapping) and item.get("role") != "checksums"
        ),
        key=lambda item: item["path"],
    )
    checksum = candidate.get("checksumInventory")
    if not isinstance(checksum, Mapping) or checksum.get("subjects") != expected_subjects:
        return "checksum-coverage"
    expected_bindings = [
        {
            "itemArtifactId": f"stac-item-{scenario}-{horizon}",
            "scenario": scenario,
            "horizon": horizon,
            "analysisArtifactId": f"projection-{scenario}-{horizon}-cog",
            "visualArtifactId": f"projection-{scenario}-{horizon}-pmtiles",
            "tableArtifactId": "projection-matrix-geoparquet",
        }
        for scenario in ("ssp1-26", "ssp2-45", "ssp5-85")
        for horizon in (2030, 2050, 2100)
    ]
    bindings = candidate.get("stacBindings")
    if not isinstance(bindings, Mapping) or bindings.get("items") != expected_bindings:
        return "stac-binding"
    excluded = set(_PAIR_GATE["excludedSidecarRoles"])
    if excluded & {item.get("role") for item in artifacts if isinstance(item, Mapping)}:
        return "artifact-inventory"
    return None


def validate_candidate_document(
    candidate: Mapping[str, Any], *, contract_root: Path = CONTRACT_ROOT
) -> CandidateSummary:
    """Validate one candidate and its local inventory without opening artifact paths."""
    required = _validate_inventory(_load_json(contract_root / "required-artifacts.json"))
    schema_error = _schema_error(candidate, contract_root)
    semantic_code = _semantic_code(candidate, required)
    if schema_error is not None and not (
        semantic_code in {"artifact-inventory", "checksum-coverage"}
        and _is_count_only_schema_error(schema_error)
    ):
        _fail("candidate-schema", schema_error)
    if semantic_code is not None:
        _fail(semantic_code, "candidate contradicts the exact v1 inventory")
    if candidate.get("manifest") != {
        "path": "manifest.json",
        "artifactCount": _ARTIFACT_COUNT,
        "writeSequence": _MANIFEST_SEQUENCE,
        "selfHashExcluded": True,
    }:
        _fail("manifest-order", "manifest must be the 54th and self-hash-excluded write")
    if candidate.get("supplyChainGate") != _PAIR_GATE:
        _fail("supply-chain-gate", "pending candidate/evidence pair validation is required")
    geometry = candidate.get("geometryPolicy")
    if (
        candidate.get("publicationClaim") is not False
        or not isinstance(geometry, Mapping)
        or any(
            geometry.get(field) is not False
            for field in (
                "ownerApprovalRecorded",
                "canonical",
                "production",
                "publicationEligible",
                "hazardExtentClaim",
            )
        )
    ):
        _fail("nonclaim-boundary", "candidate must make no publication or geometry claim")
    return CandidateSummary(
        candidate_id=str(candidate["candidateId"]),
        data_release_id=str(candidate["dataReleaseId"]),
        artifact_count=len(required),
    )


def validate_candidate(path: Path, *, contract_root: Path = CONTRACT_ROOT) -> CandidateSummary:
    """Load and validate candidate metadata and the checked-in inventory contract."""
    return validate_candidate_document(load_candidate(path), contract_root=contract_root)
