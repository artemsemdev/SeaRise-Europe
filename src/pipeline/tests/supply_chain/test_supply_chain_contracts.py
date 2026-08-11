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
    discover_dependency_inputs,
    load_json,
    parse_timestamp,
    validate_dependency_exception,
    validate_dependency_inventory,
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
DEPENDENCY_INVENTORY = CONTRACT_ROOT / "dependency-inventory.json"


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _validate(envelope: Path = ENVELOPE, policy: Path = POLICY, sbom: Path = SBOM) -> None:
    validate_evidence_files(
        envelope,
        policy,
        {SBOM_LOGICAL_PATH: sbom},
    )


def _dependency_document() -> dict[str, Any]:
    return copy.deepcopy(load_json(DEPENDENCY_INVENTORY))


def _copy_dependency_inputs(destination: Path) -> None:
    for component in _dependency_document()["components"]:
        for item in component["inputs"]:
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY_ROOT / item["path"], target)


def _dependency_component(document: dict[str, Any], component_id: str) -> dict[str, Any]:
    return next(
        component for component in document["components"] if component["id"] == component_id
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


def test_dependency_inventory_exactly_binds_discovered_inputs() -> None:
    document = validate_dependency_inventory(DEPENDENCY_INVENTORY)
    discovered = discover_dependency_inputs()
    recorded = tuple(
        item["path"] for component in document["components"] for item in component["inputs"]
    )
    opentofu = _dependency_component(document, "deployment-opentofu")

    assert len(discovered) == 41
    assert discovered == tuple(sorted(set(discovered)))
    assert set(recorded) == set(discovered)
    assert document["inventoryKind"] == "dependency-defining-inputs"
    assert document["productionClaim"] is False
    assert (opentofu["releaseUse"], opentofu["coverage"], opentofu["inputs"]) == (
        "not-present",
        "not-present",
        [],
    )


def test_dependency_inventory_rejects_stale_recorded_hash(tmp_path: Path) -> None:
    document = _dependency_document()
    document["components"][0]["inputs"][0]["sha256"] = "f" * 64

    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


def test_dependency_inventory_rejects_changed_input_bytes(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_dependency_inputs(repository)
    changed = repository / "src" / "frontend" / "package.json"
    changed.write_bytes(changed.read_bytes() + b"\n")

    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch"):
        validate_dependency_inventory(DEPENDENCY_INVENTORY, repository_root=repository)


def test_dependency_inventory_rejects_missing_record(tmp_path: Path) -> None:
    document = _dependency_document()
    document["components"][0]["inputs"].pop(0)

    with pytest.raises(SupplyChainContractError, match="discovery mismatch"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


def test_dependency_inventory_rejects_extra_record(tmp_path: Path) -> None:
    document = _dependency_document()
    component = _dependency_component(document, "pipeline-python-contributor")
    extra_path = "scripts/release/validate_supply_chain_contract.py"
    component["inputs"].append(
        {
            "path": extra_path,
            "role": "manifest",
            "sha256": hashlib.sha256((REPOSITORY_ROOT / extra_path).read_bytes()).hexdigest(),
        }
    )
    component["inputs"].sort(key=lambda item: item["path"])

    with pytest.raises(SupplyChainContractError, match="unclassified dependency input"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


def test_dependency_inventory_rejects_duplicate_input(tmp_path: Path) -> None:
    document = _dependency_document()
    component = document["components"][0]
    duplicate = copy.deepcopy(component["inputs"][0])
    duplicate["sha256"] = "f" * 64
    component["inputs"].insert(1, duplicate)

    with pytest.raises(SupplyChainContractError, match="duplicate dependency input"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_dependency_inventory_rejects_component_set_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    document = _dependency_document()
    if mutation == "missing":
        document["components"].pop(0)
    elif mutation == "extra":
        document["components"].append(
            {
                "id": "unexpected-component",
                "ecosystem": "opentofu",
                "releaseUse": "not-present",
                "coverage": "not-present",
                "inputs": [],
                "note": "Unexpected test component.",
            }
        )
        document["components"].sort(key=lambda component: component["id"])
    else:
        duplicate = copy.deepcopy(document["components"][0])
        duplicate["note"] = "Duplicate identifier with distinct content."
        document["components"].append(duplicate)
        document["components"].sort(key=lambda component: component["id"])

    with pytest.raises(
        SupplyChainContractError,
        match="component set mismatch|identifiers must be unique",
    ):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


def test_dependency_inventory_rejects_path_escape(tmp_path: Path) -> None:
    document = _dependency_document()
    document["components"][0]["inputs"][0]["path"] = "../outside"

    with pytest.raises(SupplyChainContractError, match="unsafe dependency input path"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


def test_dependency_inventory_rejects_symlinked_input(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_dependency_inputs(repository)
    path = repository / "src" / "api" / "Directory.Build.props"
    outside = tmp_path / "outside"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)

    with pytest.raises(SupplyChainContractError, match="must not use symlinks"):
        validate_dependency_inventory(DEPENDENCY_INVENTORY, repository_root=repository)


def test_dependency_inventory_rejects_nonregular_input(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_dependency_inputs(repository)
    path = repository / "src" / "api" / "Directory.Build.props"
    path.unlink()
    path.mkdir()

    with pytest.raises(SupplyChainContractError, match="must be a regular file"):
        validate_dependency_inventory(DEPENDENCY_INVENTORY, repository_root=repository)


def test_dependency_inventory_rejects_invalid_status_combination(tmp_path: Path) -> None:
    document = _dependency_document()
    document["components"][0]["coverage"] = "range-constrained"

    with pytest.raises(SupplyChainContractError, match="invalid dependency status combination"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


@pytest.mark.parametrize("level", ["component", "input"])
def test_dependency_inventory_rejects_unstable_order(tmp_path: Path, level: str) -> None:
    document = _dependency_document()
    if level == "component":
        document["components"].reverse()
    else:
        document["components"][0]["inputs"].reverse()

    with pytest.raises(SupplyChainContractError, match="stable sorted order"):
        validate_dependency_inventory(_write_json(tmp_path / "inventory.json", document))


def test_dependency_discovery_rejects_new_unclassified_input(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_dependency_inputs(repository)
    unclassified = repository / "tools" / "package.json"
    unclassified.parent.mkdir(parents=True)
    unclassified.write_text('{"private": true}\n', encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match=r"unclassified=.*tools/package.json"):
        validate_dependency_inventory(DEPENDENCY_INVENTORY, repository_root=repository)


def test_dependency_discovery_includes_local_composite_actions(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_dependency_inputs(repository)
    action = repository / ".github" / "actions" / "local" / "action.yml"
    action.parent.mkdir(parents=True)
    action.write_text("name: local\nruns:\n  using: composite\n  steps: []\n", encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match=r"unclassified=.*action.yml"):
        validate_dependency_inventory(DEPENDENCY_INVENTORY, repository_root=repository)


def test_dependency_discovery_rejects_unmanifested_vendored_schema(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_dependency_inputs(repository)
    schema = repository / "contracts" / "supply-chain" / "v1" / "vendor" / "new.schema.json"
    schema.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match=r"unclassified=.*new.schema.json"):
        validate_dependency_inventory(DEPENDENCY_INVENTORY, repository_root=repository)


@pytest.mark.parametrize(
    "generated_directory",
    [
        ".mypy_cache",
        ".next",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "target",
    ],
)
def test_dependency_discovery_ignores_generated_package_manifests(
    tmp_path: Path,
    generated_directory: str,
) -> None:
    generated = tmp_path / generated_directory / "nested" / "package.json"
    generated.parent.mkdir(parents=True)
    generated.write_text('{"private": true}\n', encoding="utf-8")

    assert discover_dependency_inputs(tmp_path) == ()
