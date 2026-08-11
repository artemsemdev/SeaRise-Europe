"""Fail-closed tests for the canonical candidate build-plane SBOM."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from searise_pipeline.supply_chain.build_plane_sbom import (
    _actions,
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
PROPERTY_PREFIX = "org.searise.sbom.build-plane."
EXPECTED_FILE_COMPONENTS = {
    "github-actions": 4,
    "native-geospatial-toolchain": 5,
    "release-container-image": 1,
}
EXPECTED_ACTIONS = dict(
    item.split("@")
    for item in (
        "actions/cache@0400d5f644dc74513175e3cd8d07132dd4860809",
        "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        "actions/setup-dotnet@67a3573c9a986a3f9c594539f4ab511d57bb3ce9",
        "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "github/codeql-action/analyze@28deaeda66b76a05916b6923827895f2b14ab387",
        "github/codeql-action/init@28deaeda66b76a05916b6923827895f2b14ab387",
    )
)
EXPECTED_OBSERVABLES = {
    *(
        ("github-action", name, revision, "github-actions")
        for name, revision in EXPECTED_ACTIONS.items()
    ),
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
    ("duckdb-artifact", "duckdb-python-wheel", "1.5.4", "linux-x86_64"),
    ("duckdb-artifact", "duckdb-python-wheel", "1.5.4", "macos-arm64"),
    ("duckdb-artifact", "duckdb-spatial-extension", "v1.5.4", "linux-x86_64"),
    ("duckdb-artifact", "duckdb-spatial-extension", "v1.5.4", "macos-arm64"),
    ("duckdb-artifact", "duckdb-spatial-extension-archive", "v1.5.4", "linux-x86_64"),
    ("duckdb-artifact", "duckdb-spatial-extension-archive", "v1.5.4", "macos-arm64"),
}


def _properties(component: dict[str, Any]) -> dict[str, str]:
    return {
        item["name"].removeprefix(PROPERTY_PREFIX): item["value"]
        for item in component["properties"]
    }


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


def _mutate(tmp_path: Path, label: str, path: str, old: bytes, new: bytes) -> tuple[Path, Path]:
    repository = tmp_path / label
    inventory = _copy_authority(repository)
    original = (repository / path).read_bytes()
    value = original.replace(old, new, 1)
    assert value != original
    _replace_authority(repository, inventory, path, value)
    return repository, inventory


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
        assert properties["input.path"] == item["path"]
        assert properties["input.role"] == item["role"]
        assert properties["inventory.component"] == source_id
    assert {
        (
            _properties(component)["kind"],
            component["name"],
            component["version"],
            _properties(component)["platform"],
        )
        for component in observables
    } == EXPECTED_OBSERVABLES
    for component in observables:
        properties = _properties(component)
        bindings = json.loads(properties["authority.inputs"])
        assert bindings
        assert all(
            item["sha256"]
            == hashlib.sha256((REPOSITORY_ROOT / item["path"]).read_bytes()).hexdigest()
            for item in bindings
        )
        assert properties["digest"]
        if properties["kind"] == "github-action":
            assert "hashes" not in component
            assert properties["digest"].startswith("authority-sha256:")
            assert component["version"] == properties["action.revision"]
            assert properties["action.comment-version-authoritative"] == "false"


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
            in {item["path"] for item in json.loads(_properties(candidate)["authority.inputs"])}
        }

    def key(component: dict[str, Any]) -> tuple[str, str | None]:
        return component["name"], _properties(component).get("platform")

    actual = {
        (key(component), key(by_ref[dependency]))
        for reference, component in by_ref.items()
        for dependency in edges[reference]
        if component["type"] != "file" and by_ref[dependency]["type"] != "file"
    }
    expected = {
        *(
            (
                ("duckdb-spatial-extension", platform),
                ("duckdb-spatial-extension-archive", platform),
            )
            for platform in ("linux-x86_64", "macos-arm64")
        ),
        *(
            ((binary, "linux-x86_64"), (dependency, "linux-x86_64"))
            for binary in ("tippecanoe", "tippecanoe-decode")
            for dependency in ("ubuntu", "libc6", "libsqlite3-0", "libstdc++6", "zlib1g")
        ),
    }
    assert actual == expected


def test_root_records_opentofu_absence_and_explicit_nonclaims() -> None:
    document = generate_build_plane_sbom(
        INVENTORY,
        repository_root=REPOSITORY_ROOT,
    )
    root = document["metadata"]["component"]
    properties = _properties(root)

    assert not any("opentofu" in component["name"].lower() for component in document["components"])
    assert properties["opentofu.coverage"] == "not-present"
    assert properties["opentofu.input-count"] == "0"
    assert properties["production-claim"] == "false"
    assert properties["production-ready"] == "false"
    assert properties["native-package-digest-completeness"] == "false"
    for nonclaim in (
        "candidate-attachment",
        "license-completeness",
        "release-approved",
        "signed",
        "vulnerability-completeness",
    ):
        assert properties[nonclaim] == "false"


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
    with pytest.raises(SupplyChainContractError, match="reviewed build-plane authority"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository, inventory = _mutate(
        tmp_path,
        "wheel-url",
        "src/pipeline/toolchain/duckdb-spatial-extensions.json",
        b"https://files.pythonhosted.org/",
        b"https://example.invalid/",
    )
    with pytest.raises(SupplyChainContractError, match="reviewed build-plane authority"):
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
    repository, inventory = _mutate(
        tmp_path,
        "action",
        ".github/workflows/ci.yml",
        b"actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1",
        b"actions/checkout@v4",
    )
    with pytest.raises(SupplyChainContractError, match="not fully pinned"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository, inventory = _mutate(
        tmp_path, "comment", ".github/workflows/ci.yml", b"# v4.3.1", b"# v999"
    )
    with pytest.raises(SupplyChainContractError, match="not fully pinned"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository, inventory = _mutate(
        tmp_path,
        "receipt",
        "src/pipeline/toolchain/tippecanoe-darwin-arm64-build-receipt.json",
        b'"architecture": "arm64"',
        b'"architecture": "x86_64"',
    )
    with pytest.raises(SupplyChainContractError, match="toolchain semantics changed"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    linux_receipt = "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json"
    for message, old, new in (
        ("compiler semantics", b'13.3.0"', b'fabricated"'),
        ("base images", b"ubuntu:24.04@", b"ubuntu:fake@"),
    ):
        repository, inventory = _mutate(tmp_path, message, linux_receipt, old, new)
        with pytest.raises(SupplyChainContractError, match=message):
            generate_build_plane_sbom(inventory, repository_root=repository)


def test_local_composite_action_descriptor_fails_closed() -> None:
    with pytest.raises(SupplyChainContractError, match="local composite Actions"):
        _actions({".github/actions/local/action.yml": b"runs:\n  using: composite\n"}, {})


def test_mutable_or_inconsistent_dockerfile_base_fails_closed(tmp_path: Path) -> None:
    repository, inventory = _mutate(
        tmp_path,
        "release",
        "src/pipeline/offline_release/Dockerfile",
        b"python:3.11.15-bookworm@sha256:a8f8fbe1a0edc9e4dddafa64ba73f7e04be7be5ebc23f332362e779e0a2e4e52",
        b"python:3.11-bookworm",
    )
    with pytest.raises(SupplyChainContractError, match="digest pinned"):
        generate_build_plane_sbom(inventory, repository_root=repository)

    repository = tmp_path / "native"
    inventory = _copy_authority(repository)
    path = "src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64"
    value = (repository / path).read_bytes() + b"\nRUN apt-get install curl=8.5.0-2ubuntu10.6\n"
    _replace_authority(repository, inventory, path, value)
    receipt_path = "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json"
    receipt = json.loads((repository / receipt_path).read_bytes())
    receipt["buildEnvironment"]["buildRecipeSha256"] = hashlib.sha256(value).hexdigest()
    _replace_authority(repository, inventory, receipt_path, json.dumps(receipt).encode())
    with pytest.raises(SupplyChainContractError, match="reviewed build-plane authority"):
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
