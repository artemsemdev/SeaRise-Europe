"""Validate immutable v1 dependency authority from its reviewed Git tree."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import SupplyChainContractError
from .static_profile import _HISTORICAL_EVIDENCE, load_static_target_profile_contract

_HISTORICAL_VALIDATOR_RUNTIME_PATH = PurePosixPath(
    "src/pipeline/searise_pipeline/supply_chain/contracts.py"
)


def _safe_path(value: str) -> PurePosixPath:
    logical = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or logical.is_absolute()
        or value != logical.as_posix()
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        raise SupplyChainContractError(f"unsafe historical v1 path: {value}")
    return logical


def _retained_v1_files(
    repository_root: Path,
    subtree: PurePosixPath,
) -> dict[PurePosixPath, tuple[bytes, bool]]:
    resolved_repository_root = repository_root.resolve(strict=True)
    root = _strict_repository_path(
        resolved_repository_root,
        subtree,
        description="retained Phase 1 subtree",
    )
    retained: dict[PurePosixPath, tuple[bytes, bool]] = {}
    try:
        candidates = tuple(root.rglob("*"))
    except OSError as exc:
        raise SupplyChainContractError("retained Phase 1 subtree cannot be read") from exc
    for candidate in candidates:
        relative = PurePosixPath(candidate.relative_to(resolved_repository_root).as_posix())
        candidate = _strict_repository_path(
            resolved_repository_root,
            relative,
            description="retained Phase 1 subtree",
        )
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise SupplyChainContractError(
                f"retained Phase 1 subtree entry must be a regular file: {relative}"
            )
        retained[relative] = (
            candidate.read_bytes(),
            bool(candidate.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)),
        )
    return retained


def _strict_repository_path(
    repository_root: Path,
    logical: PurePosixPath,
    *,
    description: str,
) -> Path:
    """Resolve an existing path beneath the repository without following symlinks."""
    try:
        root = repository_root.resolve(strict=True)
        if not root.is_dir():
            raise SupplyChainContractError("repository root must be a directory")
        current = root
        for part in logical.parts:
            current = current / part
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise SupplyChainContractError(
                    f"{description} must not use symlinks: {logical}"
                )
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except SupplyChainContractError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SupplyChainContractError(f"{description} cannot be resolved safely") from exc
    return resolved


def _git_object_oid(kind: str, content: bytes) -> str:
    header = f"{kind} {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _git_file_mode(path: Path) -> str:
    return "100755" if path.stat().st_mode & 0o111 else "100644"


def _retained_tree_oid(
    retained: dict[PurePosixPath, tuple[bytes, bool]],
    subtree: PurePosixPath,
) -> str:
    root: dict[str, Any] = {}
    for path, entry in retained.items():
        try:
            relative = path.relative_to(subtree)
        except ValueError as exc:
            raise SupplyChainContractError(
                f"retained Phase 1 path escapes its subtree: {path}"
            ) from exc
        cursor = root
        for part in relative.parts[:-1]:
            child = cursor.setdefault(part, {})
            if not isinstance(child, dict):
                raise SupplyChainContractError("retained Phase 1 tree has a path collision")
            cursor = child
        if not relative.parts or relative.name in cursor:
            raise SupplyChainContractError("retained Phase 1 tree has a path collision")
        cursor[relative.name] = entry

    def tree_oid(node: dict[str, Any]) -> str:
        entries: list[tuple[bytes, bool, bytes, str]] = []
        for name, value in node.items():
            encoded_name = name.encode("utf-8")
            if isinstance(value, dict):
                oid = tree_oid(value)
                entries.append((encoded_name, True, b"40000", oid))
            else:
                content, executable = value
                mode = b"100755" if executable else b"100644"
                entries.append((encoded_name, False, mode, _git_object_oid("blob", content)))
        entries.sort(key=lambda entry: entry[0] + (b"/" if entry[1] else b""))
        content = b"".join(
            mode + b" " + name + b"\0" + bytes.fromhex(oid)
            for name, _directory, mode, oid in entries
        )
        return _git_object_oid("tree", content)

    return tree_oid(root)


def _copy_materialized_file(
    root: Path,
    logical: PurePosixPath,
    content: bytes,
    executable: bool,
) -> Path:
    target = root.joinpath(*logical.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(0o755 if executable else 0o644)
    return target


@contextmanager
def materialize_historical_dependency_authority(
    profile_path: Path,
    *,
    repository_root: Path,
) -> Iterator[tuple[Path, Path]]:
    """Yield the v1 authority exactly as recorded by the v2 transition profile."""
    profile = load_static_target_profile_contract(profile_path, repository_root=repository_root)
    historical = profile["historicalEvidence"]
    if historical != _HISTORICAL_EVIDENCE:
        raise SupplyChainContractError("historical Phase 1 authority drifted")
    inventory_descriptor = historical["dependencyInventory"]
    git_authority = historical["gitAuthority"]
    mode_authority = historical["modeAuthority"]
    validator_authority = historical["validatorAuthority"]
    validator_snapshot_path = _safe_path(validator_authority["path"])
    inventory_path = _safe_path(inventory_descriptor["path"])
    subtree = _safe_path(historical["path"])
    _strict_repository_path(
        repository_root,
        subtree,
        description="retained Phase 1 subtree",
    )
    inventory_location = _strict_repository_path(
        repository_root,
        inventory_path,
        description="historical v1 inventory",
    )
    inventory_bytes = inventory_location.read_bytes()
    if hashlib.sha256(inventory_bytes).hexdigest() != inventory_descriptor["sha256"]:
        raise SupplyChainContractError("historical v1 inventory bytes changed")
    try:
        inventory = json.loads(inventory_bytes)
        input_descriptors = [
            (_safe_path(item["path"]), item["sha256"])
            for component in inventory["components"]
            for item in component["inputs"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise SupplyChainContractError("historical v1 inventory structure is malformed") from exc
    outside_inputs = {
        path for path, _sha256 in input_descriptors if subtree not in path.parents
    }
    expected_mode_paths = {
        *(path.as_posix() for path in outside_inputs),
        validator_snapshot_path.as_posix(),
    }
    if set(mode_authority) != expected_mode_paths:
        missing = sorted(expected_mode_paths - set(mode_authority))
        extra = sorted(set(mode_authority) - expected_mode_paths)
        raise SupplyChainContractError(
            f"historical v1 mode authority is incomplete: missing={missing}, extra={extra}"
        )
    retained_v1 = _retained_v1_files(repository_root, subtree)
    if _retained_tree_oid(retained_v1, subtree) != git_authority["phase1ContractsTree"]:
        raise SupplyChainContractError("historical Phase 1 contracts tree does not match")
    validator_location = _strict_repository_path(
        repository_root,
        validator_snapshot_path,
        description="historical v1 validator snapshot",
    )
    if not validator_location.is_file():
        raise SupplyChainContractError("historical v1 validator snapshot must be a regular file")
    validator_mode = mode_authority[validator_snapshot_path.as_posix()]
    if _git_file_mode(validator_location) != validator_mode:
        raise SupplyChainContractError("historical v1 validator snapshot mode changed")
    validator_bytes = validator_location.read_bytes()
    if hashlib.sha256(validator_bytes).hexdigest() != validator_authority["sha256"]:
        raise SupplyChainContractError("historical v1 validator binding changed")
    if _git_object_oid("blob", validator_bytes) != validator_authority["gitBlob"]:
        raise SupplyChainContractError("historical v1 validator Git blob does not match")

    with tempfile.TemporaryDirectory(prefix="searise-v1-authority-") as temporary:
        root = Path(temporary).resolve()
        for logical, (content, executable) in retained_v1.items():
            _copy_materialized_file(root, logical, content, executable)
        for logical, expected_sha256 in input_descriptors:
            if logical == subtree or subtree in logical.parents:
                continue
            source = _strict_repository_path(
                repository_root,
                logical,
                description="historical v1 dependency input",
            )
            if not source.is_file():
                raise SupplyChainContractError(
                    f"historical v1 dependency input must be a regular file: {logical}"
                )
            expected_mode = mode_authority[logical.as_posix()]
            if _git_file_mode(source) != expected_mode:
                raise SupplyChainContractError(
                    f"historical v1 dependency input mode changed: {logical}"
                )
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected_sha256:
                raise SupplyChainContractError(
                    f"dependency input SHA-256 mismatch: {logical}"
                )
            _copy_materialized_file(root, logical, content, expected_mode == "100755")
        _copy_materialized_file(
            root,
            _HISTORICAL_VALIDATOR_RUNTIME_PATH,
            validator_bytes,
            validator_mode == "100755",
        )
        yield root, root.joinpath(*inventory_path.parts)


def validate_historical_dependency_inventory(
    profile_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Validate v1 against its immutable Git authority, never the current tree."""
    with materialize_historical_dependency_authority(
        profile_path,
        repository_root=repository_root,
    ) as (historical_root, inventory_path):
        authority = _HISTORICAL_EVIDENCE["validatorAuthority"]
        validator_path = historical_root / _HISTORICAL_VALIDATOR_RUNTIME_PATH
        validator_bytes = validator_path.read_bytes()
        if hashlib.sha256(validator_bytes).hexdigest() != authority["sha256"]:
            raise SupplyChainContractError("historical v1 validator binding changed")
        spec = importlib.util.spec_from_file_location(
            "_searise_historical_v1_contracts",
            validator_path,
        )
        if spec is None or spec.loader is None:
            raise SupplyChainContractError("historical v1 validator cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            validator = module.validate_dependency_inventory
            return validator(inventory_path, repository_root=historical_root)
        except Exception as exc:
            historical_error = getattr(module, "SupplyChainContractError", ())
            if historical_error and isinstance(exc, historical_error):
                raise SupplyChainContractError(str(exc)) from exc
            raise SupplyChainContractError("historical v1 validator execution failed") from exc
