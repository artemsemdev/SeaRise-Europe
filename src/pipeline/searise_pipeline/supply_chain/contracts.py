"""Validate immutable signed-candidate evidence and exception contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker
from referencing import Registry, Resource

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1"


class SupplyChainContractError(ValueError):
    """Supply-chain evidence failed a schema or semantic boundary."""


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object without accepting non-object roots."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SupplyChainContractError(f"{path}: JSON root must be an object")
    return document


def parse_timestamp(value: str) -> datetime:
    """Parse one timezone-aware RFC 3339 timestamp."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SupplyChainContractError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SupplyChainContractError(f"timestamp must include a timezone: {value}")
    return parsed


def _validate_schema(document: Mapping[str, Any], schema_name: str) -> None:
    schema = load_json(CONTRACT_ROOT / schema_name)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SupplyChainContractError(f"{location}: {error.message}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_remote_schema(uri: str) -> Resource:
    raise SupplyChainContractError(f"remote schema retrieval is prohibited: {uri}")


def _validate_cyclonedx(document: Mapping[str, Any]) -> None:
    vendor_root = CONTRACT_ROOT / "vendor"
    manifest = load_json(vendor_root / "manifest.json")
    if (manifest.get("standard"), manifest.get("specVersion")) != ("CycloneDX", "1.7"):
        raise SupplyChainContractError("vendored CycloneDX identity is not version 1.7")

    schemas: list[dict[str, Any]] = []
    for record in manifest.get("schemas", []):
        relative_path = Path(record["path"])
        if relative_path.name != str(relative_path):
            raise SupplyChainContractError("vendored schema path must be one file name")
        schema_path = vendor_root / relative_path
        if _sha256(schema_path) != record["sha256"]:
            raise SupplyChainContractError(f"vendored schema SHA-256 mismatch: {relative_path}")
        schemas.append(load_json(schema_path))
    if len(schemas) != 4:
        raise SupplyChainContractError("vendored CycloneDX schema bundle is incomplete")

    bom_schema = next(
        schema for schema in schemas if schema["$id"].endswith("/bom-1.7.schema.json")
    )
    registry = Registry(retrieve=_reject_remote_schema)
    for schema in schemas:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    Draft7Validator.check_schema(bom_schema)
    errors = sorted(
        Draft7Validator(
            bom_schema,
            registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SupplyChainContractError(f"SBOM {location}: {error.message}")
    if document.get("specVersion") != "1.7":
        raise SupplyChainContractError("SBOM specVersion must be '1.7'")


def validate_evidence_files(
    envelope_path: Path,
    identity_policy_path: Path,
    sbom_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """Validate a candidate envelope and its exact local policy/SBOM bytes."""
    envelope = load_json(envelope_path)
    policy = load_json(identity_policy_path)
    _validate_schema(policy, "identity-policy.schema.json")
    _validate_schema(envelope, "evidence-envelope.schema.json")

    if envelope["identityPolicy"]["sha256"] != _sha256(identity_policy_path):
        raise SupplyChainContractError("identity policy SHA-256 does not match its bytes")
    verification = envelope["verification"]
    for field in ("certificateIdentity", "oidcIssuer"):
        if verification[field] != policy[field]:
            raise SupplyChainContractError(f"verification {field} violates identity policy")

    subjects = {
        envelope["candidateManifest"]["path"]: envelope["candidateManifest"]["sha256"],
        envelope["provenance"]["path"]: envelope["provenance"]["sha256"],
    }
    signed_subjects = {
        item["subjectPath"]: item["subjectSha256"] for item in envelope["signatures"]
    }
    if len(signed_subjects) != len(envelope["signatures"]):
        raise SupplyChainContractError("each signed subject must appear exactly once")
    if signed_subjects != subjects:
        raise SupplyChainContractError("signatures must bind the manifest and provenance hashes")

    artifact_paths = [
        envelope["candidateManifest"]["path"],
        envelope["provenance"]["path"],
    ]
    artifact_paths.extend(item["path"] for item in envelope["signatures"])
    artifact_paths.extend(item["path"] for item in envelope["softwareBillsOfMaterials"])
    if len(artifact_paths) != len(set(artifact_paths)):
        raise SupplyChainContractError("supply-chain artifact paths must be unique")

    descriptors = {item["path"]: item for item in envelope["softwareBillsOfMaterials"]}
    if set(descriptors) != set(sbom_paths):
        raise SupplyChainContractError("SBOM paths do not match the evidence envelope")
    for logical_path, descriptor in descriptors.items():
        file_path = sbom_paths[logical_path]
        if descriptor["sha256"] != _sha256(file_path):
            raise SupplyChainContractError(f"SBOM SHA-256 mismatch: {logical_path}")
        _validate_cyclonedx(load_json(file_path))

    if not verification["fixtureOnly"]:
        raise SupplyChainContractError(
            "production evidence requires the separate cryptographic verifier"
        )
    return envelope


def validate_dependency_exception(
    document: Mapping[str, Any],
    *,
    as_of: datetime,
) -> None:
    """Validate exception ownership and its deterministic effective interval."""
    if as_of.tzinfo is None:
        raise SupplyChainContractError("validation instant must include a timezone")
    _validate_schema(document, "dependency-exception.schema.json")
    approved_at = parse_timestamp(str(document["approvedAt"]))
    expires_at = parse_timestamp(str(document["expiresAt"]))
    if expires_at <= approved_at:
        raise SupplyChainContractError("dependency exception must expire after approval")
    if as_of < approved_at:
        raise SupplyChainContractError("dependency exception is not effective yet")
    if as_of >= expires_at:
        raise SupplyChainContractError("dependency exception is expired")
