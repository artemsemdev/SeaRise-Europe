"""Validate immutable v1 dependency authority from its reviewed Git tree."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import SupplyChainContractError, validate_dependency_inventory
from .static_profile import _HISTORICAL_EVIDENCE, load_static_target_profile_contract


def _git(repository_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise SupplyChainContractError("Git is required for historical v1 validation") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SupplyChainContractError(f"historical v1 Git authority is unavailable: {detail}")
    return completed.stdout


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
    root = repository_root.joinpath(*subtree.parts)
    retained: dict[PurePosixPath, tuple[bytes, bool]] = {}
    try:
        candidates = tuple(root.rglob("*"))
    except OSError as exc:
        raise SupplyChainContractError("retained Phase 1 subtree cannot be read") from exc
    for candidate in candidates:
        relative = PurePosixPath(candidate.relative_to(repository_root).as_posix())
        if candidate.is_symlink():
            raise SupplyChainContractError(
                f"retained Phase 1 subtree must not use symlinks: {relative}"
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
    validator_authority = historical["validatorAuthority"]
    validator_path = _safe_path(validator_authority["path"])
    validator_bytes = repository_root.joinpath(*validator_path.parts).read_bytes()
    if hashlib.sha256(validator_bytes).hexdigest() != validator_authority["sha256"]:
        raise SupplyChainContractError("historical v1 validator semantics changed")
    inventory_path = _safe_path(inventory_descriptor["path"])
    inventory_bytes = (repository_root / inventory_path).read_bytes()
    if hashlib.sha256(inventory_bytes).hexdigest() != inventory_descriptor["sha256"]:
        raise SupplyChainContractError("historical v1 inventory bytes changed")
    try:
        inventory = json.loads(inventory_bytes)
        inputs = [
            _safe_path(item["path"])
            for component in inventory["components"]
            for item in component["inputs"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise SupplyChainContractError("historical v1 inventory structure is malformed") from exc
    subtree = _safe_path(historical["path"])
    outside_inputs = {path for path in inputs if subtree not in path.parents}

    commit = git_authority["commit"]
    actual_tree = _git(repository_root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if actual_tree != git_authority["tree"]:
        raise SupplyChainContractError("historical v1 Git tree does not match its authority")
    actual_subtree = _git(
        repository_root,
        "rev-parse",
        f"{commit}:{subtree.as_posix()}",
    ).decode().strip()
    if actual_subtree != git_authority["phase1ContractsTree"]:
        raise SupplyChainContractError("historical Phase 1 contracts tree does not match")
    archive = _git(
        repository_root,
        "archive",
        "--format=tar",
        commit,
        "--",
        subtree.as_posix(),
        *(path.as_posix() for path in sorted(outside_inputs)),
    )

    with tempfile.TemporaryDirectory(prefix="searise-v1-authority-") as temporary:
        root = Path(temporary).resolve()
        extracted: dict[PurePosixPath, bytes] = {}
        archived_modes: dict[PurePosixPath, bool] = {}
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                for member in bundle:
                    logical = _safe_path(member.name.removesuffix("/"))
                    if member.isdir():
                        continue
                    is_v1_contract = logical == subtree or subtree in logical.parents
                    if (not is_v1_contract and logical not in outside_inputs) or not member.isreg():
                        raise SupplyChainContractError(
                            f"historical v1 archive contains an unexpected entry: {member.name}"
                        )
                    source = bundle.extractfile(member)
                    if source is None:
                        raise SupplyChainContractError(
                            f"historical v1 archive entry cannot be read: {member.name}"
                        )
                    target = root.joinpath(*logical.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    content = source.read()
                    target.write_bytes(content)
                    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
                    extracted[logical] = content
                    archived_modes[logical] = bool(member.mode & 0o111)
        except (tarfile.TarError, OSError) as exc:
            raise SupplyChainContractError("historical v1 Git archive is invalid") from exc
        expected = {inventory_path, *inputs}
        if not expected <= extracted.keys():
            missing = sorted(path.as_posix() for path in expected - extracted.keys())
            raise SupplyChainContractError(
                f"historical v1 Git archive is incomplete: {missing}"
            )
        archived_v1 = {
            path: (content, archived_modes[path])
            for path, content in extracted.items()
            if path == subtree or subtree in path.parents
        }
        retained_v1 = _retained_v1_files(repository_root, subtree)
        if retained_v1.keys() != archived_v1.keys():
            added = sorted(path.as_posix() for path in retained_v1.keys() - archived_v1.keys())
            deleted = sorted(path.as_posix() for path in archived_v1.keys() - retained_v1.keys())
            raise SupplyChainContractError(
                f"retained Phase 1 subtree path drift; added={added}, deleted={deleted}"
            )
        changed = sorted(
            path.as_posix()
            for path in retained_v1
            if retained_v1[path] != archived_v1[path]
        )
        if changed:
            raise SupplyChainContractError(
                f"retained Phase 1 subtree bytes changed: {changed}"
            )
        archived_inventory = root.joinpath(*inventory_path.parts)
        if archived_inventory.read_bytes() != inventory_bytes:
            raise SupplyChainContractError(
                "historical v1 inventory differs from its Git authority"
            )
        yield root, archived_inventory


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
        return validate_dependency_inventory(
            inventory_path,
            repository_root=historical_root,
            contract_root=historical_root / "contracts/supply-chain/v1",
        )
