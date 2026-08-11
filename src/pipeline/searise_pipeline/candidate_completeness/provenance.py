"""Canonical unsigned provenance for a validated Phase 1 candidate/build pair."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, NoReturn
from urllib.parse import quote

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .validator import CandidateContractError, validate_candidate_document

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
BUILD_TYPE = "https://artemsemdev.github.io/SeaRise-Europe/build-types/offline-release/v1"
BUILDER_ID = (
    "https://github.com/artemsemdev/SeaRise-Europe/.github/workflows/"
    "offline-release-controlled.yml@refs/heads/master"
)
POLICY_IDENTITY = "phase-1-pre-sign-synthetic-provenance-v1"

_ROOT = Path(__file__).resolve().parents[4]
_RELEASE_CONTRACT_ROOT = _ROOT / "contracts/release/v1"
_INVOCATION = re.compile(
    r"https://github\.com/artemsemdev/SeaRise-Europe/actions/runs/"
    r"[1-9][0-9]*/attempts/1\Z"
)


class ProvenanceContractError(ValueError):
    """The metadata or statement violates the closed provenance boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> NoReturn:
    raise ProvenanceContractError(code, message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant: {value}")


def _load_strict(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"{label}-json", f"cannot read strict JSON object {path}: {exc}")
    if not isinstance(document, dict):
        _fail(f"{label}-json", f"JSON root must be an object: {path}")
    return document, raw


def canonical_provenance_bytes(document: Mapping[str, Any]) -> bytes:
    """Render sorted single-line UTF-8 JSON with one terminal newline."""
    try:
        rendered = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        _fail("provenance-json", f"statement is not standard JSON: {exc}")
    return (rendered + "\n").encode("utf-8")


def _validate_build_receipt(document: Mapping[str, Any]) -> None:
    try:
        schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in _RELEASE_CONTRACT_ROOT.glob("*.schema.json")
        }
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
        )
        validator = Draft202012Validator(
            schemas["build-receipt.schema.json"],
            registry=registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(document),
            key=lambda error: tuple(
                (type(part).__name__, str(part)) for part in error.absolute_path
            ),
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        _fail("build-receipt-contract", f"cannot load the local build receipt contract: {exc}")
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        _fail("build-receipt-contract", f"{location}: {error.message}")


def _candidate_artifacts(candidate: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(item["path"]): item for item in candidate["artifacts"]}


def _validate_pair(
    candidate: Mapping[str, Any], build: Mapping[str, Any], build_bytes: bytes
) -> None:
    if candidate["dataProvenanceClass"] != "synthetic-fixture":
        _fail("unsupported-claim", "only explicit synthetic-fixture provenance is supported")
    for field in ("dataReleaseId", "dataProvenanceClass"):
        if build[field] != candidate[field]:
            _fail("candidate-build-identity", f"candidate and build receipt differ: {field}")
    artifacts = _candidate_artifacts(candidate)
    build_artifacts = [item for item in artifacts.values() if item["role"] == "build-receipt"]
    if (
        len(build_artifacts) != 1
        or build_artifacts[0]["sha256"] != hashlib.sha256(build_bytes).hexdigest()
    ):
        _fail("candidate-build-identity", "candidate does not bind the exact build receipt bytes")
    expected_sources = sorted(
        (
            {"path": item["path"], "sha256": item["sha256"]}
            for item in artifacts.values()
            if item["role"] == "source-receipt"
        ),
        key=lambda item: item["path"],
    )
    if sorted(build["sourceReceipts"], key=lambda item: item["path"]) != expected_sources:
        _fail("candidate-build-sources", "candidate and build source receipts differ")
    output_paths = [item["path"] for item in build["outputs"]]
    if len(output_paths) != len(set(output_paths)):
        _fail("candidate-build-outputs", "build output paths must be unique")
    for output in build["outputs"]:
        candidate_output = artifacts.get(output["path"])
        fields = ("role", "mediaType", "byteSize", "sha256")
        if candidate_output is None or tuple(output[key] for key in fields) != tuple(
            candidate_output[key] for key in fields
        ):
            _fail("candidate-build-outputs", f"build output differs: {output['path']}")


def _dependency(uri: str, algorithm: str, digest: str) -> dict[str, Any]:
    return {"uri": uri, "digest": {algorithm: digest}}


def _dependencies(build: Mapping[str, Any]) -> list[dict[str, Any]]:
    revision = build["codeRevision"]
    values = [
        _dependency(
            f"git+https://github.com/artemsemdev/SeaRise-Europe@{revision}",
            "gitCommit",
            revision,
        ),
        _dependency(
            f"urn:searise:environment-lock:{quote(build['environment']['lock']['path'], safe='')}",
            "sha256",
            build["environment"]["lock"]["sha256"],
        ),
    ]
    for kind, key in (("source-receipt", "sourceReceipts"), ("input", "inputs")):
        values.extend(
            _dependency(
                f"urn:searise:{kind}:{quote(item['path'], safe='')}",
                "sha256",
                item["sha256"],
            )
            for item in build[key]
        )
    values.extend(
        _dependency(
            f"pkg:generic/{quote(tool['name'], safe='')}@{quote(tool['version'], safe='')}",
            "sha256",
            tool["identitySha256"],
        )
        for tool in build["tools"]
    )
    values.sort(key=lambda item: item["uri"])
    uris = [item["uri"] for item in values]
    if len(uris) != len(set(uris)):
        _fail("provenance-dependencies", "resolved dependency identities must be unique")
    return values


def _invocation(value: str) -> str:
    if not _INVOCATION.fullmatch(value):
        _fail("trusted-invocation", "invocation must be the approved first-attempt run URI")
    return value


def generate_provenance_statement(
    manifest_path: Path,
    build_receipt_path: Path,
    *,
    trusted_invocation_uri: str,
) -> dict[str, Any]:
    """Derive the exact supported unsigned statement from a validated pair."""
    if manifest_path.name != "manifest.json":
        _fail("candidate-manifest", "candidate metadata path must be named manifest.json")
    try:
        candidate, manifest_bytes = _load_strict(manifest_path, "candidate")
        validate_candidate_document(candidate)
    except CandidateContractError as exc:
        _fail("candidate-contract", str(exc))
    build, build_bytes = _load_strict(build_receipt_path, "build-receipt")
    _validate_build_receipt(build)
    _validate_pair(candidate, build, build_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": "manifest.json", "digest": {"sha256": manifest_sha256}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": {
                    "candidateId": candidate["candidateId"],
                    "dataReleaseId": candidate["dataReleaseId"],
                    "dataProvenanceClass": candidate["dataProvenanceClass"],
                    "actualManifestSha256": manifest_sha256,
                },
                "internalParameters": {
                    "buildReceipt": {
                        "sha256": hashlib.sha256(build_bytes).hexdigest(),
                        "buildId": build["buildId"],
                        "buildMode": build["buildMode"],
                        "networkAccess": build["networkAccess"],
                        "parametersSha256": build["parametersSha256"],
                        "environment": build["environment"],
                    },
                    "claims": {
                        "cryptographicVerification": False,
                        "production": False,
                        "publication": False,
                        "scientific": False,
                        "signing": False,
                        "syntheticFixture": True,
                    },
                    "policyIdentity": POLICY_IDENTITY,
                },
                "resolvedDependencies": _dependencies(build),
            },
            "runDetails": {
                "builder": {"id": BUILDER_ID},
                "metadata": {
                    "invocationId": _invocation(trusted_invocation_uri),
                    "startedOn": build["startedAt"],
                    "finishedOn": build["completedAt"],
                },
            },
        },
    }


def validate_provenance_statement(
    statement_path: Path,
    manifest_path: Path,
    build_receipt_path: Path,
    *,
    trusted_invocation_uri: str,
) -> dict[str, Any]:
    """Validate canonical bytes against the complete closed supported statement."""
    statement, raw = _load_strict(statement_path, "provenance")
    if raw != canonical_provenance_bytes(statement):
        _fail("provenance-canonical", "statement must be canonical single-line JSON")
    expected = generate_provenance_statement(
        manifest_path,
        build_receipt_path,
        trusted_invocation_uri=trusted_invocation_uri,
    )
    if statement.get("subject") != expected["subject"]:
        _fail("provenance-subjects", "the sole manifest subject is missing or changed")
    predicate = statement.get("predicate")
    actual_definition = predicate.get("buildDefinition", {}) if isinstance(predicate, dict) else {}
    if not isinstance(actual_definition, dict):
        actual_definition = {}
    expected_definition = expected["predicate"]["buildDefinition"]
    if actual_definition.get("resolvedDependencies") != expected_definition["resolvedDependencies"]:
        _fail(
            "provenance-dependencies",
            "dependencies are missing, duplicated, unsorted, or changed",
        )
    if statement != expected:
        _fail("provenance-identity", "statement identity, workflow, policy, or claims changed")
    return statement
