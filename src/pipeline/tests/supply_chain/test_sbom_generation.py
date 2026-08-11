"""Deterministic, fail-closed tests for supported SBOM input locks."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import searise_pipeline.supply_chain.sbom as sbom_module
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    canonical_sbom_bytes,
    generate_npm_sbom,
    write_new_sbom,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
FIXTURE = (
    REPOSITORY_ROOT
    / "contracts"
    / "supply-chain"
    / "v1"
    / "fixtures"
    / "sbom"
    / "npm-lock.synthetic.json"
)
REAL_LOCK = REPOSITORY_ROOT / "src" / "frontend" / "package-lock.json"
LOGICAL_PATH = "contracts/supply-chain/v1/fixtures/sbom/npm-lock.synthetic.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_bytes())


def _write_lock(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _generate(path: Path = FIXTURE) -> dict[str, Any]:
    return generate_npm_sbom(path, logical_path=LOGICAL_PATH)


def _properties(component: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in component["properties"]}


def _components_by_path(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _properties(component)["org.searise.sbom.npm.lock-path"]: component
        for component in document["components"]
    }


def _dependencies(document: dict[str, Any]) -> dict[str, list[str]]:
    return {item["ref"]: item["dependsOn"] for item in document["dependencies"]}


def test_synthetic_lock_generates_complete_path_qualified_graph() -> None:
    document = _generate()
    components = _components_by_path(document)
    graph = _dependencies(document)
    root = document["metadata"]["component"]

    assert document["specVersion"] == "1.7"
    assert len(components) == 6
    assert set(graph) == {root["bom-ref"], *(item["bom-ref"] for item in components.values())}
    assert graph[root["bom-ref"]] == sorted(
        components[path]["bom-ref"]
        for path in (
            "node_modules/alpha",
            "node_modules/optional-package",
            "node_modules/peer-package",
            "node_modules/shared",
            "node_modules/tooling",
        )
    )
    assert graph[components["node_modules/alpha"]["bom-ref"]] == [
        components["node_modules/shared"]["bom-ref"]
    ]
    assert graph[components["node_modules/tooling"]["bom-ref"]] == [
        components["node_modules/tooling/node_modules/shared"]["bom-ref"]
    ]
    assert components["node_modules/optional-package"]["scope"] == "optional"

    duplicate_shared = [
        component for component in components.values() if component["name"] == "shared"
    ]
    assert {component["purl"] for component in duplicate_shared} == {"pkg:npm/shared@1.0.0"}
    assert len({component["bom-ref"] for component in duplicate_shared}) == 2


def test_lock_and_component_bytes_are_bound_by_sha256() -> None:
    document = _generate()
    root_properties = _properties(document["metadata"]["component"])
    components = _components_by_path(document)
    packages = _fixture()["packages"]
    alpha = components["node_modules/alpha"]
    expected_entry = packages["node_modules/alpha"]
    expected_entry_bytes = canonical_sbom_bytes(expected_entry)

    assert root_properties["org.searise.sbom.input.path"] == LOGICAL_PATH
    assert (
        root_properties["org.searise.sbom.input.sha256"]
        == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    )
    assert root_properties["org.searise.sbom.npm.root.dependencies"] == (
        '{"alpha":"1.0.0","shared":"1.0.0"}'
    )
    assert _properties(alpha)["org.searise.sbom.npm.lock-entry-sha256"] == (
        hashlib.sha256(expected_entry_bytes).hexdigest()
    )
    expected_integrities = set()
    for path, component in components.items():
        integrity = packages[path]["integrity"].removeprefix("sha512-")
        expected_integrities.add(integrity)
        assert component["hashes"] == [
            {"alg": "SHA-512", "content": base64.b64decode(integrity).hex()}
        ]
    assert len(expected_integrities) == len(components)


def test_generation_is_byte_stable_and_input_tamper_changes_identity(
    tmp_path: Path,
) -> None:
    first = canonical_sbom_bytes(_generate())
    assert canonical_sbom_bytes(_generate()) == first

    mutated = _fixture()
    mutated["packages"]["node_modules/alpha"]["license"] = "MIT"
    changed = canonical_sbom_bytes(_generate(_write_lock(tmp_path, mutated)))

    assert changed != first
    assert json.loads(changed)["serialNumber"] != json.loads(first)["serialNumber"]


def test_canonical_rendering_rejects_non_json_numbers() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_sbom_bytes({"invalid": float("nan")})


def test_real_lock_generates_reachable_graph_and_validated_aliases() -> None:
    document = generate_npm_sbom(
        REAL_LOCK,
        logical_path="src/frontend/package-lock.json",
    )
    components = document["components"]
    graph = _dependencies(document)
    reachable = {document["metadata"]["component"]["bom-ref"]}
    pending = list(reachable)
    while pending:
        for reference in graph[pending.pop()]:
            if reference not in reachable:
                reachable.add(reference)
                pending.append(reference)

    assert len(components) == 597
    assert len(reachable) == 598
    alias = next(
        component
        for component in components
        if _properties(component)["org.searise.sbom.npm.install-name"] == "string-width-cjs"
    )
    assert (alias["name"], alias["purl"]) == (
        "string-width",
        "pkg:npm/string-width@4.2.3",
    )
    by_path = _components_by_path(document)
    assert {
        path
        for path, component in by_path.items()
        if _properties(component)["org.searise.sbom.npm.devOptional"] == "true"
    } == {
        "node_modules/@types/prop-types",
        "node_modules/@types/react",
        "node_modules/csstype",
    }
    for path in (
        "node_modules/@types/prop-types",
        "node_modules/@types/react",
        "node_modules/csstype",
    ):
        assert by_path[path]["scope"] == "optional"

    assert (
        by_path["node_modules/supports-color"]["bom-ref"]
        not in graph[by_path["node_modules/debug"]["bom-ref"]]
    )
    assert (
        by_path["node_modules/eslint"]["bom-ref"]
        not in graph[by_path["node_modules/eslint-module-utils"]["bom-ref"]]
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda lock: lock.update(lockfileVersion=2), "package-lock v3"),
        (lambda lock: lock["packages"][""].update(workspaces=["packages/*"]), "workspaces"),
        (lambda lock: lock["packages"]["node_modules/alpha"].update(link=True), "links"),
        (
            lambda lock: lock["packages"]["node_modules/alpha"].update(integrity="sha256-invalid"),
            "integrity",
        ),
        (
            lambda lock: lock["packages"]["node_modules/alpha"].update(
                resolved="https://example.com/alpha-1.0.0.tgz"
            ),
            "tarball",
        ),
        (
            lambda lock: lock["packages"]["node_modules/alpha"].update(
                resolved=("https://registry.npmjs.org/alpha/-/extra/alpha-1.0.0.tgz")
            ),
            "tarball",
        ),
        (
            lambda lock: lock["packages"]["node_modules/alpha"].update(
                resolved=("https://registry.npmjs.org/alpha/-/../-/alpha-1.0.0.tgz")
            ),
            "tarball",
        ),
        (
            lambda lock: lock["packages"]["node_modules/alpha"].update(name="different"),
            "name/path mismatch",
        ),
        (
            lambda lock: lock["packages"]["node_modules/alpha"].update(devOptional="yes"),
            "devOptional flag",
        ),
    ],
)
def test_unsupported_or_inconsistent_lock_features_fail_closed(
    tmp_path: Path,
    mutation: Any,
    message: str,
) -> None:
    lock = _fixture()
    mutation(lock)
    with pytest.raises(SupplyChainContractError, match=message):
        _generate(_write_lock(tmp_path, lock))


@pytest.mark.parametrize("name", ["@/alpha", "@scope/", "bad,name", "bad:name", "bad\nname"])
def test_invalid_npm_names_fail_closed(tmp_path: Path, name: str) -> None:
    lock = _fixture()
    lock["packages"]["node_modules/alpha"]["name"] = name
    with pytest.raises(SupplyChainContractError, match="invalid npm package name"):
        _generate(_write_lock(tmp_path, lock))


@pytest.mark.parametrize(
    "metadata",
    [
        {"peer-package": {"optional": "yes"}},
        {"peer-package": {"optional": True, "extra": False}},
        {"undeclared-peer": {"optional": False}},
    ],
)
def test_invalid_peer_dependency_metadata_fails_closed(
    tmp_path: Path,
    metadata: dict[str, Any],
) -> None:
    lock = _fixture()
    lock["packages"][""]["peerDependenciesMeta"] = metadata
    with pytest.raises(SupplyChainContractError, match="peerDependenciesMeta"):
        _generate(_write_lock(tmp_path, lock))


def test_unresolved_required_edge_and_unreachable_entry_fail_closed(
    tmp_path: Path,
) -> None:
    unresolved = _fixture()
    unresolved["packages"]["node_modules/alpha"]["dependencies"] = {"missing": "1.0.0"}
    with pytest.raises(SupplyChainContractError, match="unresolved npm dependency"):
        _generate(_write_lock(tmp_path, unresolved))

    orphaned = _fixture()
    orphaned["packages"]["node_modules/orphan"] = copy.deepcopy(
        orphaned["packages"]["node_modules/alpha"]
    )
    orphaned["packages"]["node_modules/orphan"].pop("dependencies")
    orphaned["packages"]["node_modules/orphan"].update(
        resolved="https://registry.npmjs.org/orphan/-/orphan-1.0.0.tgz"
    )
    with pytest.raises(SupplyChainContractError, match="unreachable npm package"):
        _generate(_write_lock(tmp_path, orphaned))


def test_alias_target_mismatch_fails_closed(tmp_path: Path) -> None:
    lock = _fixture()
    lock["packages"][""]["dependencies"]["alpha"] = "npm:other@1.0.0"
    lock["packages"]["node_modules/alpha"]["name"] = "alpha"
    with pytest.raises(SupplyChainContractError, match="alias target mismatch"):
        _generate(_write_lock(tmp_path, lock))


def test_symlink_directory_and_duplicate_keys_fail_closed(tmp_path: Path) -> None:
    symlink = tmp_path / "symlink-lock.json"
    symlink.symlink_to(FIXTURE)
    with pytest.raises(SupplyChainContractError, match="symlink"):
        _generate(symlink)
    with pytest.raises(SupplyChainContractError, match="regular file"):
        _generate(tmp_path)

    duplicate = tmp_path / "duplicate-lock.json"
    duplicate.write_text('{"name":"one","name":"two"}\n', encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="duplicate npm lock key"):
        _generate(duplicate)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numeric_constants_fail_closed(tmp_path: Path, constant: str) -> None:
    invalid = tmp_path / "package-lock.json"
    invalid.write_text('{"value":' + constant + "}\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="non-JSON numeric constant"):
        _generate(invalid)


def test_atomic_output_refuses_overwrite_input_alias_and_symlinks(
    tmp_path: Path,
) -> None:
    original = FIXTURE.read_bytes()
    with pytest.raises(SupplyChainContractError, match="already exists"):
        write_new_sbom(FIXTURE, b"replacement")
    assert FIXTURE.read_bytes() == original

    target = tmp_path / "target.json"
    target.write_bytes(b"existing")
    symlink = tmp_path / "output.json"
    symlink.symlink_to(target)
    with pytest.raises(SupplyChainContractError, match="already exists"):
        write_new_sbom(symlink, b"replacement")
    assert target.read_bytes() == b"existing"


def test_atomic_output_requires_existing_non_symlink_parent(tmp_path: Path) -> None:
    with pytest.raises(SupplyChainContractError, match="already exist"):
        write_new_sbom(tmp_path / "missing" / "output.json", b"content")

    actual_parent = tmp_path / "actual"
    actual_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)
    with pytest.raises(SupplyChainContractError, match="must not be a symlink"):
        write_new_sbom(linked_parent / "output.json", b"content")


def test_atomic_output_promotes_complete_bytes_and_cleans_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    write_new_sbom(output, b"complete\n")
    assert output.read_bytes() == b"complete\n"
    assert not list(tmp_path.glob("*.partial"))

    failed_output = tmp_path / "failed.json"

    def fail_link(_source: Path, _target: Path) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(sbom_module.os, "link", fail_link)
    with pytest.raises(OSError, match="injected link failure"):
        write_new_sbom(failed_output, b"partial")
    assert not failed_output.exists()
    assert not list(tmp_path.glob("*.partial"))
