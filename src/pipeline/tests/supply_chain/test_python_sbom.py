"""Fail-closed tests for target-specific Python CycloneDX SBOMs."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from searise_pipeline.supply_chain import SupplyChainContractError, write_new_sbom
from searise_pipeline.supply_chain.python_sbom import (
    generate_python_sbom,
    validate_python_sbom,
)
from searise_pipeline.supply_chain.sbom import canonical_sbom_bytes

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1" / "fixtures" / "python-graph"
ANNOTATION = FIXTURE_ROOT / "valid.json"
LINUX = "linux-x86-64-cp311"
MACOS = "macos-arm64-cp311"
SBOM_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1" / "sboms"
REAL_TARGETS = (
    (
        "release-linux",
        REPOSITORY_ROOT / "contracts/supply-chain/v1/python-graphs/release-runtime.json",
        LINUX,
        SBOM_ROOT / "python-release-linux-x86-64-cp311.cdx.json",
        39,
    ),
    (
        "release-macos",
        REPOSITORY_ROOT / "contracts/supply-chain/v1/python-graphs/release-runtime.json",
        MACOS,
        SBOM_ROOT / "python-release-macos-arm64-cp311.cdx.json",
        39,
    ),
    (
        "settlement-spatial-linux",
        REPOSITORY_ROOT / "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json",
        LINUX,
        SBOM_ROOT / "python-settlement-spatial-linux-x86-64-cp311.cdx.json",
        1,
    ),
    (
        "settlement-spatial-macos",
        REPOSITORY_ROOT / "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json",
        MACOS,
        SBOM_ROOT / "python-settlement-spatial-macos-arm64-cp311.cdx.json",
        1,
    ),
)


def _generate(target_id: str = LINUX, *, repository: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    annotation = (
        ANNOTATION
        if repository == REPOSITORY_ROOT
        else repository / "contracts/supply-chain/v1/fixtures/python-graph/valid.json"
    )
    return generate_python_sbom(annotation, repository_root=repository, target_id=target_id)


def _properties(component: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in component["properties"]}


def _components(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {component["name"]: component for component in document["components"]}


def _dependencies(document: dict[str, Any]) -> dict[str, list[str]]:
    return {
        relationship["ref"]: relationship["dependsOn"] for relationship in document["dependencies"]
    }


def _set_root_property(document: dict[str, Any], name: str, value: str) -> None:
    properties = document["metadata"]["component"]["properties"]
    next(item for item in properties if item["name"] == name)["value"] = value


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    destination = repository / "contracts/supply-chain/v1/fixtures"
    destination.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, destination / "python-graph")
    return repository, destination / "python-graph/valid.json"


def _write_annotation(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _write_sbom(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes(canonical_sbom_bytes(document))


def test_each_target_gets_one_complete_graph_with_its_exact_wheel_hashes() -> None:
    linux = _generate(LINUX)
    macos = _generate(MACOS)
    linux_components = _components(linux)
    macos_components = _components(macos)
    linux_graph = _dependencies(linux)
    root = linux["metadata"]["component"]["bom-ref"]

    assert linux["specVersion"] == "1.7"
    assert list(linux_components) == ["alpha", "bravo", "charlie"]
    assert [linux_components[name]["hashes"][0]["content"] for name in linux_components] == [
        "a" * 64,
        "b" * 64,
        "c" * 64,
    ]
    assert [macos_components[name]["hashes"][0]["content"] for name in macos_components] == [
        "d" * 64,
        "e" * 64,
        "f" * 64,
    ]
    assert all(
        component["bom-ref"] == component["purl"] == f"pkg:pypi/{name}@{component['version']}"
        for name, component in linux_components.items()
    )
    assert linux_graph[root] == [linux_components["alpha"]["bom-ref"]]
    assert linux_graph[linux_components["alpha"]["bom-ref"]] == [
        linux_components["bravo"]["bom-ref"]
    ]
    assert linux_graph[linux_components["bravo"]["bom-ref"]] == [
        linux_components["charlie"]["bom-ref"]
    ]
    assert linux_graph[linux_components["charlie"]["bom-ref"]] == []
    assert linux["serialNumber"] != macos["serialNumber"]


def test_root_binds_annotation_lock_target_environment_and_claim_boundaries() -> None:
    document = _generate()
    properties = _properties(document["metadata"]["component"])
    annotation = json.loads(ANNOTATION.read_bytes())
    target = annotation["targets"][0]

    assert properties["org.searise.sbom.annotation.id"] == annotation["annotationId"]
    assert properties["org.searise.sbom.annotation.path"] == (
        "contracts/supply-chain/v1/fixtures/python-graph/valid.json"
    )
    assert (
        properties["org.searise.sbom.annotation.sha256"]
        == hashlib.sha256(ANNOTATION.read_bytes()).hexdigest()
    )
    assert properties["org.searise.sbom.python.lock.path"] == target["lock"]["path"]
    assert properties["org.searise.sbom.python.lock.sha256"] == target["lock"]["sha256"]
    assert properties["org.searise.sbom.python.target.id"] == LINUX
    assert properties["org.searise.sbom.python.target.marker-environment"] == json.dumps(
        target["markerEnvironment"], separators=(",", ":"), sort_keys=True
    )
    assert properties["org.searise.sbom.data-provenance-class"] == "synthetic-fixture"
    assert properties["org.searise.sbom.production-claim"] == "false"


def test_reviewed_metadata_maps_to_real_source_without_creating_a_production_claim(
    tmp_path: Path,
) -> None:
    repository, annotation_path = _copy_fixture(tmp_path)
    annotation = json.loads(annotation_path.read_bytes())
    annotation["review"].update(
        status="reviewed-wheel-metadata",
        note="Reviewed synthetic wheel metadata used only to exercise the boundary.",
    )
    _write_annotation(annotation_path, annotation)

    properties = _properties(_generate(repository=repository)["metadata"]["component"])
    assert properties["org.searise.sbom.data-provenance-class"] == "real-source"
    assert properties["org.searise.sbom.production-claim"] == "false"


def test_generation_and_validation_are_byte_stable(tmp_path: Path) -> None:
    first = canonical_sbom_bytes(_generate())
    assert canonical_sbom_bytes(_generate()) == first
    output = tmp_path / "python-sbom.json"
    output.write_bytes(first)

    validated = validate_python_sbom(
        output,
        ANNOTATION,
        repository_root=REPOSITORY_ROOT,
        target_id=LINUX,
    )
    assert canonical_sbom_bytes(validated) == first
    with pytest.raises(SupplyChainContractError, match="already exists"):
        write_new_sbom(output, first)
    assert output.read_bytes() == first


@pytest.mark.parametrize(
    ("_name", "annotation", "target_id", "artifact", "component_count"),
    REAL_TARGETS,
)
def test_checked_in_real_artifacts_match_exact_reviewed_target_authority(
    _name: str,
    annotation: Path,
    target_id: str,
    artifact: Path,
    component_count: int,
) -> None:
    document = validate_python_sbom(
        artifact,
        annotation,
        repository_root=REPOSITORY_ROOT,
        target_id=target_id,
    )
    properties = _properties(document["metadata"]["component"])
    annotation_document = json.loads(annotation.read_bytes())
    target = next(item for item in annotation_document["targets"] if item["id"] == target_id)

    assert artifact.read_bytes() == canonical_sbom_bytes(document)
    assert len(document["components"]) == component_count
    assert properties["org.searise.sbom.annotation.id"] == annotation_document["annotationId"]
    assert properties["org.searise.sbom.python.target.id"] == target_id
    assert properties["org.searise.sbom.python.lock.path"] == target["lock"]["path"]
    assert properties["org.searise.sbom.python.lock.sha256"] == target["lock"]["sha256"]
    assert properties["org.searise.sbom.data-provenance-class"] == "real-source"
    assert properties["org.searise.sbom.production-claim"] == "false"


@pytest.mark.parametrize(
    ("_name", "annotation", "target_id", "artifact", "_component_count"),
    REAL_TARGETS,
)
def test_real_artifact_mutation_and_wrong_target_fail_closed(
    _name: str,
    annotation: Path,
    target_id: str,
    artifact: Path,
    _component_count: int,
    tmp_path: Path,
) -> None:
    mutated = json.loads(artifact.read_bytes())
    mutated["components"].pop()
    candidate = tmp_path / artifact.name
    _write_sbom(candidate, mutated)

    with pytest.raises(SupplyChainContractError, match="graph target authority"):
        validate_python_sbom(
            candidate,
            annotation,
            repository_root=REPOSITORY_ROOT,
            target_id=target_id,
        )

    other_target = MACOS if target_id == LINUX else LINUX
    with pytest.raises(SupplyChainContractError, match="graph target authority"):
        validate_python_sbom(
            artifact,
            annotation,
            repository_root=REPOSITORY_ROOT,
            target_id=other_target,
        )


@pytest.mark.parametrize(("_name", "annotation", "_target_id", "artifact", "_count"), REAL_TARGETS)
def test_real_annotations_reject_missing_target_before_artifact_validation(
    _name: str,
    annotation: Path,
    _target_id: str,
    artifact: Path,
    _count: int,
    tmp_path: Path,
) -> None:
    document = json.loads(annotation.read_bytes())
    repository = tmp_path / "repository"
    for target in document["targets"]:
        lock = REPOSITORY_ROOT / target["lock"]["path"]
        copied_lock = repository / target["lock"]["path"]
        copied_lock.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(lock, copied_lock)
    document["targets"] = []
    missing_target_annotation = repository / annotation.relative_to(REPOSITORY_ROOT)
    missing_target_annotation.parent.mkdir(parents=True, exist_ok=True)
    _write_annotation(missing_target_annotation, document)

    with pytest.raises(SupplyChainContractError, match="non-empty"):
        validate_python_sbom(
            artifact,
            missing_target_annotation,
            repository_root=repository,
            target_id=LINUX,
        )


@pytest.mark.parametrize("target_id", ["missing-target", "", True, 1])
def test_target_selection_must_be_explicit_and_unambiguous(
    target_id: object,
) -> None:
    with pytest.raises(SupplyChainContractError, match="target ID"):
        generate_python_sbom(
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=target_id,  # type: ignore[arg-type]
        )


def test_ambiguous_graph_targets_fail_before_generation(tmp_path: Path) -> None:
    repository, annotation_path = _copy_fixture(tmp_path)
    annotation = json.loads(annotation_path.read_bytes())
    annotation["targets"][1]["id"] = annotation["targets"][0]["id"]
    _write_annotation(annotation_path, annotation)

    with pytest.raises(SupplyChainContractError, match="unique"):
        _generate(repository=repository)


def _remove_component(document: dict[str, Any]) -> None:
    document["components"].pop()


def _add_component(document: dict[str, Any]) -> None:
    component = copy.deepcopy(document["components"][0])
    component.update(
        name="delta",
        version="4.0.0",
        purl="pkg:pypi/delta@4.0.0",
        **{"bom-ref": "pkg:pypi/delta@4.0.0"},
    )
    document["components"].append(component)


def _remove_edge(document: dict[str, Any]) -> None:
    document["dependencies"][0]["dependsOn"] = []


def _add_edge(document: dict[str, Any]) -> None:
    document["dependencies"][0]["dependsOn"].append("pkg:pypi/charlie@3.0.0")


@pytest.mark.parametrize(
    "mutation",
    [_remove_component, _add_component, _remove_edge, _add_edge],
    ids=["missing-component", "extra-component", "missing-edge", "extra-edge"],
)
def test_missing_or_extra_components_and_edges_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    document = _generate()
    mutation(document)
    output = tmp_path / "mutated.json"
    _write_sbom(output, document)

    with pytest.raises(SupplyChainContractError, match="graph target authority"):
        validate_python_sbom(
            output,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=LINUX,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.update(version=True),
        lambda document: _set_root_property(document, "org.searise.sbom.production-claim", "true"),
        lambda document: document["components"][0].update(purl="pkg:pypi/alpha@9.0.0"),
        lambda document: document["components"][0]["hashes"][0].update(content="0" * 64),
    ],
    ids=["bool-int-drift", "production-claim", "purl", "wheel-hash"],
)
def test_type_identity_claim_purl_and_hash_drift_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    document = _generate()
    mutation(document)
    output = tmp_path / "mutated.json"
    _write_sbom(output, document)

    with pytest.raises(SupplyChainContractError):
        validate_python_sbom(
            output,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=LINUX,
        )


@pytest.mark.parametrize(
    "content",
    [
        b'{"bomFormat":"CycloneDX"}',
        b'{"bomFormat":"CycloneDX","bomFormat":"CycloneDX"}\n',
        b'{"value":NaN}\n',
        b'{"value":1e400}\n',
        b"[]\n",
        b"{\xff}\n",
    ],
    ids=[
        "noncanonical",
        "duplicate-key",
        "non-json-number",
        "non-finite-float",
        "non-object",
        "non-utf8",
    ],
)
def test_noncanonical_or_malformed_sbom_json_fails_closed(
    tmp_path: Path,
    content: bytes,
) -> None:
    output = tmp_path / "invalid.json"
    output.write_bytes(content)
    with pytest.raises(SupplyChainContractError):
        validate_python_sbom(
            output,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=LINUX,
        )


def test_annotation_and_lock_mutation_invalidate_existing_sbom(tmp_path: Path) -> None:
    repository, annotation_path = _copy_fixture(tmp_path)
    output = tmp_path / "python-sbom.json"
    _write_sbom(output, _generate(repository=repository))

    annotation = json.loads(annotation_path.read_bytes())
    annotation["review"]["note"] = "Mutated annotation authority."
    _write_annotation(annotation_path, annotation)
    with pytest.raises(SupplyChainContractError, match="graph target authority"):
        validate_python_sbom(
            output,
            annotation_path,
            repository_root=repository,
            target_id=LINUX,
        )

    repository, annotation_path = _copy_fixture(tmp_path / "lock-case")
    output = tmp_path / "lock-sbom.json"
    _write_sbom(output, _generate(repository=repository))
    annotation = json.loads(annotation_path.read_bytes())
    lock = repository / annotation["targets"][0]["lock"]["path"]
    lock.write_bytes(lock.read_bytes().replace(b"a" * 64, b"1" * 64))
    annotation["targets"][0]["lock"]["sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    _write_annotation(annotation_path, annotation)
    with pytest.raises(SupplyChainContractError, match="graph target authority"):
        validate_python_sbom(
            output,
            annotation_path,
            repository_root=repository,
            target_id=LINUX,
        )


def test_symlinked_and_outside_authority_paths_fail_closed(tmp_path: Path) -> None:
    repository, annotation_path = _copy_fixture(tmp_path)
    real_annotation = annotation_path.with_suffix(".real")
    annotation_path.rename(real_annotation)
    annotation_path.symlink_to(real_annotation)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        _generate(repository=repository)

    with pytest.raises(SupplyChainContractError, match="beneath the repository"):
        generate_python_sbom(
            ANNOTATION,
            repository_root=repository,
            target_id=LINUX,
        )

    repository, annotation_path = _copy_fixture(tmp_path / "parent-case")
    parent = annotation_path.parent
    moved_parent = parent.with_name("python-graph-real")
    parent.rename(moved_parent)
    parent.symlink_to(moved_parent, target_is_directory=True)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        _generate(repository=repository)

    repository, annotation_path = _copy_fixture(tmp_path / "lock-case")
    annotation = json.loads(annotation_path.read_bytes())
    lock = repository / annotation["targets"][0]["lock"]["path"]
    real_lock = lock.with_suffix(".real")
    lock.rename(real_lock)
    lock.symlink_to(real_lock)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        _generate(repository=repository)


def test_symlinked_sbom_file_or_parent_fails_closed(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    _write_sbom(real, _generate())
    alias = tmp_path / "alias.json"
    alias.symlink_to(real)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        validate_python_sbom(
            alias,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=LINUX,
        )

    parent = tmp_path / "real-parent"
    parent.mkdir()
    nested = parent / "sbom.json"
    _write_sbom(nested, _generate())
    parent_alias = tmp_path / "parent-alias"
    parent_alias.symlink_to(parent, target_is_directory=True)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        validate_python_sbom(
            parent_alias / nested.name,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=LINUX,
        )
