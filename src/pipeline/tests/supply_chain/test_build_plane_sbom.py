"""Fail-closed tests for the canonical candidate build-plane SBOM."""

from __future__ import annotations

import hashlib
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
EXPECTED_FILE_COMPONENTS = {
    "github-actions": 4,
    "native-geospatial-toolchain": 5,
    "release-container-image": 1,
}
EXPECTED_OBSERVABLES = {
    ("github-action", "actions/cache", "4.2.4", "github-actions"),
    ("github-action", "actions/checkout", "4.3.1", "github-actions"),
    ("github-action", "actions/download-artifact", "4.3.0", "github-actions"),
    ("github-action", "actions/setup-dotnet", "4.3.1", "github-actions"),
    ("github-action", "actions/setup-node", "4.4.0", "github-actions"),
    ("github-action", "actions/setup-python", "5.6.0", "github-actions"),
    ("github-action", "actions/upload-artifact", "4.6.2", "github-actions"),
    ("github-action", "github/codeql-action/analyze", "3.28.16", "github-actions"),
    ("github-action", "github/codeql-action/init", "3.28.16", "github-actions"),
    ("native-binary", "tippecanoe", "2.79.0", "macos-arm64"),
    ("native-binary", "tippecanoe", "2.79.0", "linux-x86_64"),
    ("native-binary", "tippecanoe-decode", "2.79.0", "macos-arm64"),
    ("native-binary", "tippecanoe-decode", "2.79.0", "linux-x86_64"),
    ("native-package", "build-essential", "12.10ubuntu1", "linux-x86_64"),
    ("native-package", "ca-certificates", "20260601~24.04.1", "linux-x86_64"),
    ("native-package", "libc6", "2.39-0ubuntu8.8", "linux-x86_64"),
    ("native-package", "libsqlite3-0", "3.45.1-1ubuntu2.7", "linux-x86_64"),
    ("native-package", "libsqlite3-dev", "3.45.1-1ubuntu2.7", "linux-x86_64"),
    ("native-package", "libstdc++6", "14.2.0-4ubuntu2~24.04.1", "linux-x86_64"),
    ("native-package", "zlib1g", "1:1.3.dfsg-3.1ubuntu2.1", "linux-x86_64"),
    ("native-package", "zlib1g-dev", "1:1.3.dfsg-3.1ubuntu2.1", "linux-x86_64"),
    ("oci-base", "python", "3.11.15-bookworm", "linux-container"),
    ("oci-base", "ubuntu", "24.04", "linux-x86_64"),
    *(
        (
            "duckdb-artifact",
            name,
            "1.5.4" if name == "duckdb-python-wheel" else "v1.5.4",
            platform,
        )
        for name in (
            "duckdb-python-wheel",
            "duckdb-spatial-extension",
            "duckdb-spatial-extension-archive",
        )
        for platform in ("linux-x86_64", "macos-arm64")
    ),
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


def _replace_authority(repository: Path, inventory: Path, path: str, value: bytes) -> None:
    (repository / path).write_bytes(value)
    document = json.loads(inventory.read_bytes())
    item = next(
        item
        for component in document["components"]
        for item in component["inputs"]
        if item["path"] == path
    )
    item["sha256"] = hashlib.sha256(value).hexdigest()
    inventory.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


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
        if component["id"] in EXPECTED_FILE_COMPONENTS
        for item in component["inputs"]
    }

    assert raw == canonical_sbom_bytes(document)
    files = [component for component in document["components"] if component["type"] == "file"]
    observables = [component for component in document["components"] if component["type"] != "file"]
    assert len(document["components"]) == 39
    assert len(files) == sum(EXPECTED_FILE_COMPONENTS.values()) == 10
    assert {component["name"] for component in files} == set(recorded)
    for component in files:
        source_id, item = recorded[component["name"]]
        properties = _properties(component)
        assert component["type"] == "file"
        assert "purl" not in component
        assert component["hashes"] == [{"alg": "SHA-256", "content": item["sha256"]}]
        assert properties["org.searise.sbom.build-plane.input.path"] == item["path"]
        assert properties["org.searise.sbom.build-plane.input.role"] == item["role"]
        assert properties["org.searise.sbom.build-plane.inventory.component"] == source_id
    assert {
        (
            _properties(component)["org.searise.sbom.build-plane.kind"],
            component["name"],
            component["version"],
            _properties(component)["org.searise.sbom.build-plane.platform"],
        )
        for component in observables
    } == EXPECTED_OBSERVABLES
    for component in observables:
        properties = _properties(component)
        bindings = json.loads(properties["org.searise.sbom.build-plane.authority.inputs"])
        assert bindings
        assert all(
            item["sha256"]
            == hashlib.sha256((REPOSITORY_ROOT / item["path"]).read_bytes()).hexdigest()
            for item in bindings
        )
        assert properties["org.searise.sbom.build-plane.digest"]


def test_dependency_graph_is_exact_and_closed() -> None:
    document = generate_build_plane_sbom(INVENTORY, repository_root=REPOSITORY_ROOT)
    root_ref = document["metadata"]["component"]["bom-ref"]
    by_ref = {component["bom-ref"]: component for component in document["components"]}
    edges = {item["ref"]: set(item["dependsOn"]) for item in document["dependencies"]}

    assert set(edges) == {root_ref, *by_ref}
    assert edges[root_ref] == {
        ref for ref, component in by_ref.items() if component["type"] == "file"
    }
    assert all(dependency in by_ref for values in edges.values() for dependency in values)
    for reference, component in by_ref.items():
        if component["type"] != "file":
            continue
        assert edges[reference] == {
            candidate_ref
            for candidate_ref, candidate in by_ref.items()
            if candidate["type"] != "file"
            and component["name"]
            in {
                item["path"]
                for item in json.loads(
                    _properties(candidate)["org.searise.sbom.build-plane.authority.inputs"]
                )
            }
        }
    for reference, component in by_ref.items():
        if component["type"] == "file" or component["name"] not in {
            "duckdb-spatial-extension",
            "tippecanoe",
            "tippecanoe-decode",
        }:
            continue
        properties = _properties(component)
        dependencies = [by_ref[item] for item in edges[reference]]
        if component["name"] == "duckdb-spatial-extension":
            assert [
                (item["name"], _properties(item)["org.searise.sbom.build-plane.platform"])
                for item in dependencies
            ] == [
                (
                    "duckdb-spatial-extension-archive",
                    properties["org.searise.sbom.build-plane.platform"],
                )
            ]
        elif properties["org.searise.sbom.build-plane.platform"] == "linux-x86_64":
            assert {item["name"] for item in dependencies} == {
                "ubuntu",
                "libc6",
                "libsqlite3-0",
                "libstdc++6",
                "zlib1g",
            }
        else:
            assert dependencies == []


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
    assert properties["org.searise.sbom.build-plane.production-ready"] == "false"
    assert properties["org.searise.sbom.build-plane.native-package-digest-completeness"] == "false"
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


def test_observable_authority_omission_and_duplicate_fail_closed(tmp_path: Path) -> None:
    repository = tmp_path / "omission"
    inventory = _copy_authority(repository)
    path = "src/pipeline/toolchain/duckdb-spatial-extensions.json"
    document = json.loads((repository / path).read_bytes())
    del document["platforms"]["macos-arm64"]
    _replace_authority(repository, inventory, path, json.dumps(document).encode())
    with pytest.raises(SupplyChainContractError, match="platforms.*not exact"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository = tmp_path / "duplicate"
    inventory = _copy_authority(repository)
    path = "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json"
    value = (
        (repository / path)
        .read_bytes()
        .replace(
            b'"build-essential": "12.10ubuntu1",',
            b'"build-essential": "12.10ubuntu1",\n      "build-essential": "12.10ubuntu1",',
        )
    )
    _replace_authority(repository, inventory, path, value)
    with pytest.raises(SupplyChainContractError, match="duplicate inventory key"):
        generate_build_plane_sbom(inventory, repository_root=repository)


def test_unpinned_action_and_native_semantic_mutations_fail_closed(tmp_path: Path) -> None:
    repository = tmp_path / "action"
    inventory = _copy_authority(repository)
    path = ".github/workflows/ci.yml"
    value = (
        (repository / path)
        .read_bytes()
        .replace(
            b"actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1",
            b"actions/checkout@v4",
        )
    )
    _replace_authority(repository, inventory, path, value)
    with pytest.raises(SupplyChainContractError, match="not fully pinned"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository = tmp_path / "receipt"
    inventory = _copy_authority(repository)
    path = "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json"
    value = (repository / path).read_bytes().replace(b'"version": "2.79.0"', b'"version": "2.80.0"')
    _replace_authority(repository, inventory, path, value)
    with pytest.raises(SupplyChainContractError, match="receipt semantics changed"):
        generate_build_plane_sbom(inventory, repository_root=repository)


def test_mutable_or_inconsistent_dockerfile_base_fails_closed(tmp_path: Path) -> None:
    repository = tmp_path / "release"
    inventory = _copy_authority(repository)
    path = "src/pipeline/offline_release/Dockerfile"
    value = (
        (repository / path)
        .read_bytes()
        .replace(
            b"python:3.11.15-bookworm@sha256:a8f8fbe1a0edc9e4dddafa64ba73f7e04be7be5ebc23f332362e779e0a2e4e52",
            b"python:3.11-bookworm",
        )
    )
    _replace_authority(repository, inventory, path, value)
    with pytest.raises(SupplyChainContractError, match="digest pinned"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository = tmp_path / "native"
    inventory = _copy_authority(repository)
    path = "src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64"
    value = (
        (repository / path)
        .read_bytes()
        .replace(b"build-essential=12.10ubuntu1", b"build-essential=12.11ubuntu1")
    )
    _replace_authority(repository, inventory, path, value)
    with pytest.raises(
        SupplyChainContractError, match="receipt semantics changed|recipe packages differ"
    ):
        generate_build_plane_sbom(inventory, repository_root=repository)


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
