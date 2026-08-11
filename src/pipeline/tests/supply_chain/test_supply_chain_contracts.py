"""Contract and semantic tests for signed candidate evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import searise_pipeline.supply_chain.contracts as supply_chain_contracts
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    load_json,
    parse_timestamp,
    validate_dependency_exception,
    validate_evidence_files,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1"
VALID_ROOT = CONTRACT_ROOT / "fixtures" / "valid"
INVALID_ROOT = CONTRACT_ROOT / "fixtures" / "invalid"
ENVELOPE = VALID_ROOT / "evidence-envelope.json"
POLICY = CONTRACT_ROOT / "identity-policy.json"
SBOM = VALID_ROOT / "frontend.cdx.json"
SBOM_LOGICAL_PATH = "sbom/frontend.cdx.json"


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _validate(envelope: Path = ENVELOPE, policy: Path = POLICY, sbom: Path = SBOM) -> None:
    validate_evidence_files(
        envelope,
        policy,
        {SBOM_LOGICAL_PATH: sbom},
    )


def test_supply_chain_schemas_pass_the_draft_2020_12_metaschema() -> None:
    for schema_path in sorted(CONTRACT_ROOT.glob("*.schema.json")):
        Draft202012Validator.check_schema(load_json(schema_path))


def test_synthetic_evidence_fixture_binds_policy_subjects_and_sbom() -> None:
    _validate()
    envelope = load_json(ENVELOPE)

    assert envelope["identityPolicy"]["sha256"] == hashlib.sha256(POLICY.read_bytes()).hexdigest()
    assert (
        envelope["softwareBillsOfMaterials"][0]["sha256"]
        == hashlib.sha256(SBOM.read_bytes()).hexdigest()
    )
    assert {
        envelope["provenance"]["role"],
        *(item["role"] for item in envelope["signatures"]),
        *(item["role"] for item in envelope["softwareBillsOfMaterials"]),
    } == {"provenance", "signature", "software-bill-of-materials"}


def test_standard_and_identity_identifiers_are_exactly_pinned() -> None:
    policy = load_json(POLICY)
    envelope = load_json(ENVELOPE)
    sbom = load_json(SBOM)

    assert policy["certificateIdentity"] == (
        "https://github.com/artemsemdev/SeaRise-Europe/.github/workflows/"
        "phase-1-release-sign.yml@refs/heads/master"
    )
    assert policy["oidcIssuer"] == "https://token.actions.githubusercontent.com"
    assert envelope["provenance"]["statementType"] == "https://in-toto.io/Statement/v1"
    assert envelope["provenance"]["predicateType"] == "https://slsa.dev/provenance/v1"
    assert envelope["provenance"]["path"] == "provenance.intoto.jsonl"
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.7"


def test_missing_sbom_fixture_fails_closed() -> None:
    with pytest.raises(SupplyChainContractError, match="softwareBillsOfMaterials"):
        _validate(INVALID_ROOT / "missing-sbom.json")


def test_wrong_workflow_identity_fixture_fails_closed() -> None:
    with pytest.raises(SupplyChainContractError, match="certificateIdentity|workflowPath"):
        _validate(policy=INVALID_ROOT / "wrong-workflow-identity.json")


def test_signature_subject_substitution_fails_closed(tmp_path: Path) -> None:
    envelope = copy.deepcopy(load_json(ENVELOPE))
    envelope["signatures"][1]["subjectSha256"] = "f" * 64
    mutated = _write_json(tmp_path / "evidence-envelope.json", envelope)

    with pytest.raises(SupplyChainContractError, match="manifest and provenance"):
        _validate(mutated)


def test_duplicate_artifact_paths_fail_closed(tmp_path: Path) -> None:
    envelope = copy.deepcopy(load_json(ENVELOPE))
    envelope["signatures"][0]["path"] = envelope["provenance"]["path"]
    mutated = _write_json(tmp_path / "evidence-envelope.json", envelope)

    with pytest.raises(SupplyChainContractError, match="artifact paths must be unique"):
        _validate(mutated)


def test_supply_chain_artifact_cannot_overwrite_manifest(tmp_path: Path) -> None:
    envelope = copy.deepcopy(load_json(ENVELOPE))
    envelope["signatures"][0]["path"] = envelope["candidateManifest"]["path"]
    mutated = _write_json(tmp_path / "evidence-envelope.json", envelope)

    with pytest.raises(SupplyChainContractError, match="artifact paths must be unique"):
        _validate(mutated)


def test_production_claim_requires_a_cryptographic_verifier(tmp_path: Path) -> None:
    envelope = copy.deepcopy(load_json(ENVELOPE))
    envelope["verification"].update(
        {
            "status": "verified-production",
            "fixtureOnly": False,
            "verified": True,
            "policySatisfied": True,
            "productionClaim": True,
            "reason": None,
        }
    )
    mutated = _write_json(tmp_path / "evidence-envelope.json", envelope)

    with pytest.raises(SupplyChainContractError, match="cryptographic verifier"):
        _validate(mutated)


def test_cyclonedx_version_drift_fails_closed(tmp_path: Path) -> None:
    sbom = copy.deepcopy(load_json(SBOM))
    sbom["specVersion"] = "1.6"
    mutated_sbom = _write_json(tmp_path / "frontend.cdx.json", sbom)
    envelope = copy.deepcopy(load_json(ENVELOPE))
    envelope["softwareBillsOfMaterials"][0]["sha256"] = hashlib.sha256(
        mutated_sbom.read_bytes()
    ).hexdigest()
    mutated_envelope = _write_json(tmp_path / "evidence-envelope.json", envelope)

    with pytest.raises(SupplyChainContractError, match="specVersion"):
        _validate(mutated_envelope, sbom=mutated_sbom)


def test_official_cyclonedx_schema_rejects_unknown_fields(tmp_path: Path) -> None:
    sbom = copy.deepcopy(load_json(SBOM))
    sbom["unexpected"] = True
    mutated_sbom = _write_json(tmp_path / "frontend.cdx.json", sbom)
    envelope = copy.deepcopy(load_json(ENVELOPE))
    envelope["softwareBillsOfMaterials"][0]["sha256"] = hashlib.sha256(
        mutated_sbom.read_bytes()
    ).hexdigest()
    mutated_envelope = _write_json(tmp_path / "evidence-envelope.json", envelope)

    with pytest.raises(SupplyChainContractError, match="unexpected"):
        _validate(mutated_envelope, sbom=mutated_sbom)


def test_vendored_cyclonedx_schema_hash_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied_contract_root = tmp_path / "v1"
    shutil.copytree(CONTRACT_ROOT, copied_contract_root)
    vendor_schema = copied_contract_root / "vendor" / "bom-1.7.schema.json"
    vendor_schema.write_bytes(vendor_schema.read_bytes() + b"\n")
    monkeypatch.setattr(supply_chain_contracts, "CONTRACT_ROOT", copied_contract_root)

    with pytest.raises(SupplyChainContractError, match="vendored schema SHA-256 mismatch"):
        _validate()


def test_dependency_exception_is_time_bound() -> None:
    exception = load_json(VALID_ROOT / "dependency-exception.json")
    as_of = parse_timestamp("2026-08-11T12:00:00Z")

    assert as_of.tzinfo == timezone.utc
    validate_dependency_exception(exception, as_of=as_of)


def test_expired_dependency_exception_fails_closed() -> None:
    exception = load_json(INVALID_ROOT / "expired-exception.json")

    with pytest.raises(SupplyChainContractError, match="expired"):
        validate_dependency_exception(
            exception,
            as_of=parse_timestamp("2026-08-11T12:00:00Z"),
        )
