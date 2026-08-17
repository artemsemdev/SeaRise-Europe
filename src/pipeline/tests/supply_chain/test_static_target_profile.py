"""Fail-closed tests for the static-browser supply-chain transition profile."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    discover_dependency_inputs,
    generate_npm_sbom,
    validate_static_target_profile,
)

ROOT = Path(__file__).resolve().parents[4]
PROFILE = ROOT / "contracts/supply-chain/v2/static-target-profile.json"
SCHEMA = ROOT / "contracts/supply-chain/v2/static-target-profile.schema.json"


def _load(path: Path = PROFILE) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _item(document: dict[str, Any], path: str) -> dict[str, str]:
    return next(
        item
        for component in document["components"]
        for item in component["inputs"]
        if item["path"] == path
    )


def _copy_active_authority(destination: Path) -> None:
    for component in _load()["components"]:
        for item in component["inputs"]:
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / item["path"], target)


def test_profile_schema_passes_draft_2020_12_metaschema() -> None:
    Draft202012Validator.check_schema(_load(SCHEMA))


def test_npm_sbom_rejects_unreviewed_scope() -> None:
    with pytest.raises(SupplyChainContractError, match="unsupported npm SBOM scope"):
        generate_npm_sbom(
            ROOT / "package-lock.json",
            repository_root=ROOT,
            logical_path="package-lock.json",
            scope="unreviewed-runtime",
        )


def test_checked_in_profile_validates_only_the_static_target() -> None:
    document = validate_static_target_profile(PROFILE, repository_root=ROOT)
    paths = {
        item["path"]
        for component in document["components"]
        for item in component["inputs"]
    }

    assert document["target"] == "static-browser"
    assert document["productionClaim"] is False
    assert document["activation"]["status"] == "pending-legacy-removal"
    assert document["activation"]["blockingIssues"] == [71, 72]
    assert document["historicalEvidence"] == {
        "path": "contracts/supply-chain/v1",
        "status": "immutable-phase-1-history",
    }
    assert {"package.json", "package-lock.json", "src/web/package.json"} <= paths
    assert "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json" in paths
    assert "contracts/supply-chain/v1/sboms/frontend-npm.cdx.json" not in paths
    assert "src/pipeline/pyproject.toml" in paths
    assert "src/pipeline/requirements-pipeline.txt" in paths
    assert (
        "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
        not in discover_dependency_inputs()
    )
    assert not any(
        path.startswith(("src/api/", "src/frontend/", "infra/blob-seed/"))
        or Path(path).name.startswith(("compose.", "docker-compose."))
        for path in paths
    )


def test_profile_survives_a_tree_with_no_legacy_runtime(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)

    validated = validate_static_target_profile(PROFILE, repository_root=repository)

    assert len(validated["components"]) == 13
    assert validated["activation"]["status"] == "pending-legacy-removal"
    assert not (repository / "src/api").exists()
    assert not (repository / "src/frontend").exists()
    assert not (repository / "infra/blob-seed").exists()
    assert not (repository / "docker-compose.yml").exists()


def test_profile_rejects_legacy_runtime_as_an_active_input(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    legacy = ROOT / "src/frontend/package.json"
    component = next(item for item in document["components"] if item["id"] == "static-web-npm")
    component["inputs"].append(
        {
            "path": "src/frontend/package.json",
            "role": "manifest",
            "sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
        }
    )
    component["inputs"].sort(key=lambda item: item["path"])

    with pytest.raises(SupplyChainContractError, match="legacy runtime"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_rejects_missing_required_static_input(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    component = next(item for item in document["components"] if item["id"] == "static-web-npm")
    component["inputs"] = [
        item for item in component["inputs"] if item["path"] != "src/web/package.json"
    ]

    with pytest.raises(SupplyChainContractError, match="input set drifted"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_rejects_changed_authority_bytes(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    _item(document, "package.json")["sha256"] = "f" * 64

    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch: package.json"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_cannot_claim_active_while_legacy_selectors_remain(tmp_path: Path) -> None:
    document = copy.deepcopy(_load())
    document["activation"] = {
        "status": "active",
        "blockingIssues": [],
        "pendingSelectors": [],
    }

    with pytest.raises(SupplyChainContractError, match="activation does not match"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


@pytest.mark.parametrize("mutation", ["component", "role"])
def test_profile_rejects_input_owner_or_role_drift(tmp_path: Path, mutation: str) -> None:
    document = copy.deepcopy(_load())
    source = next(item for item in document["components"] if item["id"] == "static-web-npm")
    item = next(item for item in source["inputs"] if item["path"] == "src/web/package.json")
    if mutation == "role":
        item["role"] = "lock"
    else:
        source["inputs"].remove(item)
        target = next(
            component
            for component in document["components"]
            if component["id"] == "pipeline-python-contributor"
        )
        target["inputs"].append(item)
        target["inputs"].sort(key=lambda candidate: candidate["path"])

    with pytest.raises(SupplyChainContractError, match="owner or role drifted"):
        validate_static_target_profile(_write(tmp_path / "profile.json", document))


def test_profile_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = PROFILE.read_text(encoding="utf-8").replace(
        '  "schemaVersion": "2.0.0",',
        '  "schemaVersion": "2.0.0",\n  "schemaVersion": "2.0.0",',
        1,
    )
    path = tmp_path / "profile.json"
    path.write_text(duplicate, encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match="duplicate static supply-chain profile key"):
        validate_static_target_profile(path)


def test_profile_rejects_symlinked_authority(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    package = repository / "package.json"
    real = repository / "package.real.json"
    package.rename(real)
    package.symlink_to(real.name)

    with pytest.raises(SupplyChainContractError, match="must not use symlinks: package.json"):
        validate_static_target_profile(PROFILE, repository_root=repository)


def test_profile_loads_its_bound_schema_from_repository_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    (repository / "contracts/supply-chain/v2/static-target-profile.schema.json").unlink()

    with pytest.raises(SupplyChainContractError, match="outside or missing"):
        validate_static_target_profile(PROFILE, repository_root=repository)


def test_profile_rejects_repository_schema_hash_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    schema_path = repository / "contracts/supply-chain/v2/static-target-profile.schema.json"
    schema = json.loads(schema_path.read_bytes())
    schema["description"] = "Unreviewed but structurally valid schema mutation."
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch.*profile.schema"):
        validate_static_target_profile(PROFILE, repository_root=repository)


def test_profile_rejects_web_manifest_lock_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    manifest_path = repository / "src/web/package.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["dependencies"]["react"] = "0.0.0"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    document = copy.deepcopy(_load())
    _item(document, "src/web/package.json")["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()

    with pytest.raises(SupplyChainContractError, match="differs from its exact lock workspace"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )


@pytest.mark.parametrize("legacy_package", ["azure-storage-blob", "psycopg2-binary"])
def test_profile_rejects_legacy_python_packages(
    tmp_path: Path,
    legacy_package: str,
) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    manifest_path = (
        repository
        / "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
    )
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + f"{legacy_package}>=1,<99\n",
        encoding="utf-8",
    )
    document = copy.deepcopy(_load())
    _item(
        document,
        "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt",
    )["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(SupplyChainContractError, match="legacy Python packages"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )


@pytest.mark.parametrize("mutation", ["next-component", "frontend-workspace"])
def test_profile_rejects_legacy_npm_graph_entries(tmp_path: Path, mutation: str) -> None:
    repository = tmp_path / "repository"
    _copy_active_authority(repository)
    sbom_path = repository / "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json"
    sbom = json.loads(sbom_path.read_bytes())
    if mutation == "next-component":
        sbom["components"].append({"type": "library", "name": "next", "version": "15.0.0"})
    else:
        properties = sbom["metadata"]["component"]["properties"]
        next(item for item in properties if item["name"].endswith("workspace.path"))["value"] = (
            "src/frontend"
        )
    sbom_path.write_text(json.dumps(sbom, separators=(",", ":")) + "\n", encoding="utf-8")
    document = copy.deepcopy(_load())
    _item(document, "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json")[
        "sha256"
    ] = hashlib.sha256(sbom_path.read_bytes()).hexdigest()

    with pytest.raises(SupplyChainContractError, match="Next.js or src/frontend"):
        validate_static_target_profile(
            _write(tmp_path / "profile.json", document),
            repository_root=repository,
        )
