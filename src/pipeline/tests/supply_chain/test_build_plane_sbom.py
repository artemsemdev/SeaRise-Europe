"""Fail-closed tests for the canonical candidate build-plane SBOM."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from searise_pipeline.supply_chain.build_plane_sbom import (
    generate_build_plane_sbom,
    publish_build_plane_sbom,
    validate_build_plane_sbom,
)
from searise_pipeline.supply_chain.contracts import SupplyChainContractError
from searise_pipeline.supply_chain.sbom import canonical_sbom_bytes

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
INVENTORY = REPOSITORY_ROOT / "contracts/supply-chain/v1/dependency-inventory.json"
ARTIFACT = REPOSITORY_ROOT / "contracts/supply-chain/v1/sboms/build-plane.cdx.json"
INVENTORY_LOGICAL = Path("contracts/supply-chain/v1/dependency-inventory.json")
EXPECTED_COMPONENTS = {
    "github-actions": 4,
    "native-geospatial-toolchain": 5,
    "release-container-image": 1,
}


def _properties(component: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in component["properties"]}


def _inventory() -> dict[str, Any]:
    return json.loads(INVENTORY.read_bytes())


def _copy_authority(destination: Path) -> Path:
    document = _inventory()
    for component in document["components"]:
        for item in component["inputs"]:
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY_ROOT / item["path"], target)
    inventory = destination / INVENTORY_LOGICAL
    inventory.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INVENTORY, inventory)
    return inventory


def test_checked_in_artifact_exactly_binds_reviewed_build_plane_inputs() -> None:
    raw = ARTIFACT.read_bytes()
    document = validate_build_plane_sbom(
        ARTIFACT,
        INVENTORY,
        repository_root=REPOSITORY_ROOT,
    )
    recorded = {
        item["path"]: (component["id"], item)
        for component in _inventory()["components"]
        if component["id"] in EXPECTED_COMPONENTS
        for item in component["inputs"]
    }

    assert raw == canonical_sbom_bytes(document)
    assert len(document["components"]) == sum(EXPECTED_COMPONENTS.values())
    assert {component["name"] for component in document["components"]} == set(recorded)
    for component in document["components"]:
        source_id, item = recorded[component["name"]]
        properties = _properties(component)
        assert component["type"] == "file"
        assert "purl" not in component
        assert component["hashes"] == [{"alg": "SHA-256", "content": item["sha256"]}]
        assert properties["org.searise.sbom.build-plane.input.path"] == item["path"]
        assert properties["org.searise.sbom.build-plane.input.role"] == item["role"]
        assert properties["org.searise.sbom.build-plane.inventory.component"] == source_id


def test_root_records_opentofu_absence_and_explicit_nonclaims() -> None:
    document = generate_build_plane_sbom(
        INVENTORY,
        repository_root=REPOSITORY_ROOT,
    )
    root = document["metadata"]["component"]
    properties = _properties(root)

    assert not any("opentofu" in component["name"].lower() for component in document["components"])
    assert properties["org.searise.sbom.build-plane.opentofu.coverage"] == "not-present"
    assert properties["org.searise.sbom.build-plane.opentofu.input-count"] == "0"
    assert properties["org.searise.sbom.build-plane.production-claim"] == "false"
    for nonclaim in (
        "candidate-attachment",
        "license-completeness",
        "release-approved",
        "signed",
        "vulnerability-completeness",
    ):
        assert properties[f"org.searise.sbom.build-plane.{nonclaim}"] == "false"


def test_generation_is_byte_stable() -> None:
    first = generate_build_plane_sbom(INVENTORY, repository_root=REPOSITORY_ROOT)
    second = generate_build_plane_sbom(INVENTORY, repository_root=REPOSITORY_ROOT)

    assert canonical_sbom_bytes(first) == canonical_sbom_bytes(second)
    assert first["serialNumber"] == second["serialNumber"]


def test_changed_or_symlinked_input_fails_closed(tmp_path: Path) -> None:
    repository = tmp_path / "changed"
    inventory = _copy_authority(repository)
    target = repository / ".github/workflows/ci.yml"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository = tmp_path / "symlinked"
    inventory = _copy_authority(repository)
    target = repository / "src/pipeline/offline_release/Dockerfile"
    outside = tmp_path / "outside-Dockerfile"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(SupplyChainContractError, match="symlink"):
        generate_build_plane_sbom(inventory, repository_root=repository)


def test_inventory_path_and_symlink_mutations_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(SupplyChainContractError, match="must be beneath"):
        generate_build_plane_sbom(INVENTORY, repository_root=tmp_path)

    repository = tmp_path / "repository"
    inventory = _copy_authority(repository)
    outside = tmp_path / "inventory.json"
    shutil.copy2(inventory, outside)
    inventory.unlink()
    inventory.symlink_to(outside)
    with pytest.raises(SupplyChainContractError, match="symlink"):
        generate_build_plane_sbom(inventory, repository_root=repository)


def test_inventory_byte_mutation_invalidates_the_checked_in_artifact(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    inventory = _copy_authority(repository)
    document = json.loads(inventory.read_bytes())
    document["components"][0]["note"] += " Reviewed mutation."
    inventory.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match="differs from"):
        validate_build_plane_sbom(ARTIFACT, inventory, repository_root=repository)


def test_noncanonical_or_semantically_changed_artifact_fails_closed(tmp_path: Path) -> None:
    document = json.loads(ARTIFACT.read_bytes())
    noncanonical = tmp_path / "pretty.cdx.json"
    noncanonical.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="not canonical"):
        validate_build_plane_sbom(
            noncanonical,
            INVENTORY,
            repository_root=REPOSITORY_ROOT,
        )

    root_properties = document["metadata"]["component"]["properties"]
    next(
        item
        for item in root_properties
        if item["name"] == "org.searise.sbom.build-plane.production-claim"
    )["value"] = "true"
    changed = tmp_path / "changed.cdx.json"
    changed.write_bytes(canonical_sbom_bytes(document))
    with pytest.raises(SupplyChainContractError, match="differs from"):
        validate_build_plane_sbom(
            changed,
            INVENTORY,
            repository_root=REPOSITORY_ROOT,
        )


def test_publication_is_immutable(tmp_path: Path) -> None:
    output = tmp_path / "build-plane.cdx.json"
    document = publish_build_plane_sbom(
        output,
        INVENTORY,
        repository_root=REPOSITORY_ROOT,
    )

    assert output.read_bytes() == ARTIFACT.read_bytes() == canonical_sbom_bytes(document)
    with pytest.raises(SupplyChainContractError, match="already exists"):
        publish_build_plane_sbom(
            output,
            INVENTORY,
            repository_root=REPOSITORY_ROOT,
        )
