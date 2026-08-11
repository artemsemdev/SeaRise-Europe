"""Fail-closed tests for reviewed Python lock graph annotations."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest
from packaging import markers as packaging_markers

import searise_pipeline.supply_chain.python_graph as python_graph_module
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    validate_python_lock_graph,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1" / "fixtures" / "python-graph"
VALID = FIXTURE_ROOT / "valid.json"


def _document() -> dict[str, Any]:
    return copy.deepcopy(json.loads(VALID.read_bytes()))


def _copy_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "contracts" / "supply-chain" / "v1" / "fixtures"
    destination.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, destination / "python-graph")
    return destination / "python-graph" / "valid.json"


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _package(document: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in document["packages"] if item["name"] == name)


def _lock_path(repository: Path, document: dict[str, Any], target_index: int = 0) -> Path:
    return repository / document["targets"][target_index]["lock"]["path"]


def _replace_lock(
    annotation: Path,
    repository: Path,
    content: bytes,
    target_index: int = 0,
) -> None:
    document = json.loads(annotation.read_bytes())
    lock = _lock_path(repository, document, target_index)
    lock.write_bytes(content)
    document["targets"][target_index]["lock"]["sha256"] = hashlib.sha256(content).hexdigest()
    _write(annotation, document)


def _disconnect_root(document: dict[str, Any]) -> None:
    _package(document, "alpha")["dependencies"] = []
    bravo = _package(document, "bravo")
    bravo["selectedExtras"] = []
    bravo["dependencies"][0]["requirement"] = "charlie==3.0.0"


def _duplicate_package(document: dict[str, Any]) -> None:
    duplicate = copy.deepcopy(_package(document, "alpha"))
    duplicate["root"] = False
    document["packages"].insert(1, duplicate)


def test_synthetic_multi_target_graph_is_the_reviewed_authority() -> None:
    document = validate_python_lock_graph(VALID, repository_root=REPOSITORY_ROOT)

    assert document["review"] == {
        "status": "synthetic",
        "productionClaim": False,
        "note": "Synthetic graph metadata for contract tests only.",
    }
    assert [target["id"] for target in document["targets"]] == [
        "linux-x86-64-cp311",
        "macos-arm64-cp311",
    ]
    assert [item["name"] for item in document["packages"]] == [
        "alpha",
        "bravo",
        "charlie",
    ]


@pytest.mark.parametrize("content", [b'{"schemaVersion":', b'{"value": tru}', b"["])
def test_malformed_annotation_json_is_a_contract_error(
    tmp_path: Path,
    content: bytes,
) -> None:
    annotation = tmp_path / "annotation.json"
    annotation.write_bytes(content)
    with pytest.raises(SupplyChainContractError, match="JSON is malformed"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.update(unexpected=True),
        lambda document: document["review"].update(productionClaim=True),
        lambda document: document["targets"][0]["markerEnvironment"].update(python_version="3.12"),
    ],
)
def test_schema_boundary_rejects_unknown_fields_claims_and_python_drift(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    annotation = tmp_path / "annotation.json"
    document = _document()
    mutation(document)
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)


def test_lock_hash_tamper_and_symlink_fail_closed(tmp_path: Path) -> None:
    annotation = _copy_fixture(tmp_path)
    document = json.loads(annotation.read_bytes())
    lock = _lock_path(tmp_path, document)
    lock.write_bytes(lock.read_bytes() + b"# tamper\n")
    with pytest.raises(SupplyChainContractError, match="SHA-256"):
        validate_python_lock_graph(annotation, repository_root=tmp_path)

    lock.write_bytes((FIXTURE_ROOT / "target-linux.lock").read_bytes())
    target = lock.with_suffix(".real")
    lock.rename(target)
    lock.symlink_to(target)
    with pytest.raises(SupplyChainContractError, match="symlink"):
        validate_python_lock_graph(annotation, repository_root=tmp_path)

    lock.unlink()
    lock.mkdir()
    with pytest.raises(SupplyChainContractError, match="regular file"):
        validate_python_lock_graph(annotation, repository_root=tmp_path)


def test_lock_read_keeps_the_open_descriptor_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotation = _copy_fixture(tmp_path)
    document = json.loads(annotation.read_bytes())
    lock = _lock_path(tmp_path, document)
    original = lock.read_bytes()
    moved = lock.with_suffix(".opened")
    real_open = python_graph_module.os.open

    def swap_after_open(path: object, flags: int, **kwargs: int) -> int:
        descriptor = real_open(path, flags, **kwargs)
        if path == lock.name and kwargs.get("dir_fd") is not None:
            lock.rename(moved)
            lock.write_bytes(original + b"# replacement\n")
        return descriptor

    monkeypatch.setattr(python_graph_module.os, "open", swap_after_open)
    validate_python_lock_graph(annotation, repository_root=tmp_path)
    assert lock.read_bytes() != moved.read_bytes()


def test_lock_parent_swap_keeps_open_directory_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    annotation = _copy_fixture(repository)
    document = json.loads(annotation.read_bytes())
    document["targets"] = document["targets"][:1]
    _write(annotation, document)
    parent = _lock_path(repository, document).parent
    moved, outside = parent.with_name("python-graph-opened"), tmp_path / "outside"
    outside.mkdir()
    real_open, swapped = python_graph_module.os.open, False

    def swap_parent(path: object, flags: int, **kwargs: int) -> int:
        nonlocal swapped
        descriptor = real_open(path, flags, **kwargs)
        if path == parent.name and not swapped:
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return descriptor

    monkeypatch.setattr(python_graph_module.os, "open", swap_parent)
    validate_python_lock_graph(annotation, repository_root=repository)
    assert parent.is_symlink()
    _write(tmp_path / "annotation.json", document)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        validate_python_lock_graph(tmp_path / "annotation.json", repository_root=repository)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"alpha==1.0.0 --hash=sha256:" + b"a" * 64 + b"\r\n", "CRLF"),
        (b"alpha >= 1.0 --hash=sha256:" + b"a" * 64 + b"\n", "canonical"),
        (b"\xff\n", "UTF-8"),
        (b"alpha==1.0.0 --hash=sha256:" + b"a" * 64, "newline"),
    ],
)
def test_noncanonical_lock_bytes_fail_closed(
    tmp_path: Path,
    content: bytes,
    message: str,
) -> None:
    annotation = _copy_fixture(tmp_path)
    _replace_lock(annotation, tmp_path, content)
    with pytest.raises(SupplyChainContractError, match=message):
        validate_python_lock_graph(annotation, repository_root=tmp_path)


def test_duplicate_normalized_lock_name_fails_closed(tmp_path: Path) -> None:
    annotation = _copy_fixture(tmp_path)
    document = json.loads(annotation.read_bytes())
    lock = _lock_path(tmp_path, document)
    content = lock.read_bytes() + (b"Alpha==1.0.0 --hash=sha256:" + b"1" * 64 + b"\n")
    _replace_lock(annotation, tmp_path, content)
    with pytest.raises(SupplyChainContractError, match="duplicate normalized"):
        validate_python_lock_graph(annotation, repository_root=tmp_path)


def test_targets_must_have_identical_package_versions(tmp_path: Path) -> None:
    annotation = _copy_fixture(tmp_path)
    document = json.loads(annotation.read_bytes())
    lock = _lock_path(tmp_path, document, 1)
    content = lock.read_bytes().replace(b"charlie==3.0.0", b"charlie==3.1.0")
    _replace_lock(annotation, tmp_path, content, 1)
    with pytest.raises(SupplyChainContractError, match="package/version set"):
        validate_python_lock_graph(annotation, repository_root=tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda document: document["packages"].reverse(), "sorted"),
        (_duplicate_package, "unique"),
        (lambda document: document["packages"].pop(), "package parity"),
        (_disconnect_root, "unreachable"),
        (
            lambda document: _package(document, "charlie")["dependencies"].append(
                {"name": "alpha", "requirement": "alpha==1.0.0"}
            ),
            "cycle",
        ),
        (
            lambda document: _package(document, "alpha")["dependencies"].insert(
                0, {"name": "alpha", "requirement": "alpha==1.0.0"}
            ),
            "itself",
        ),
        (
            lambda document: _package(document, "alpha")["dependencies"].append(
                {"name": "delta", "requirement": "delta==4.0.0"}
            ),
            "locked package",
        ),
    ],
)
def test_graph_structure_fails_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    annotation = tmp_path / "annotation.json"
    document = _document()
    mutation(document)
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError, match=message):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)


@pytest.mark.parametrize(
    ("requirement", "message"),
    [
        ("other>=2.0", "name mismatch"),
        ("bravo>=3.0", "version"),
        ("bravo @ https://example.com/bravo.whl", "URL"),
        ("bravo>=2.0; sys_platform == 'win32'", "inactive|diverges"),
        ("bravo>=2.0; sys_platform == 'linux'", "diverges"),
        ("bravo[other]>=2.0", "selected extras"),
        ("bravo>=2.0; dependency_groups == 'runtime'", "unsupported"),
        ("bravo>=2.0; python_version ~= 'wat'", "unsupported"),
        ("bravo>=2.0; unknown_marker == 'x'", "invalid reviewed"),
    ],
)
def test_requirement_semantics_fail_closed(
    tmp_path: Path,
    requirement: str,
    message: str,
) -> None:
    annotation = tmp_path / "annotation.json"
    document = _document()
    _package(document, "alpha")["dependencies"][0]["requirement"] = requirement
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError, match=message):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)


def test_marker_evaluation_does_not_inherit_host_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = {key: "host-value" for key in _document()["targets"][0]["markerEnvironment"]}
    monkeypatch.setattr(packaging_markers, "default_environment", lambda: hostile)
    validate_python_lock_graph(VALID, repository_root=REPOSITORY_ROOT)


def test_unjustified_extra_and_unsafe_path_fail_closed(tmp_path: Path) -> None:
    annotation = tmp_path / "annotation.json"
    document = _document()
    _package(document, "bravo")["selectedExtras"].append("other")
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError, match="selected extras"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)

    document = _document()
    document["targets"][0]["lock"]["path"] = "../target-linux.lock"
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError, match="unsafe"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)


def test_duplicate_target_lock_authority_fails_closed(tmp_path: Path) -> None:
    annotation = tmp_path / "annotation.json"
    document = _document()
    document["targets"][1]["lock"] = copy.deepcopy(document["targets"][0]["lock"])
    _write(annotation, document)
    with pytest.raises(SupplyChainContractError, match="lock paths must be unique"):
        validate_python_lock_graph(annotation, repository_root=REPOSITORY_ROOT)
