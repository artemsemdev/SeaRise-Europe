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
from .static_profile import validate_static_target_profile


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


@contextmanager
def materialize_historical_dependency_authority(
    profile_path: Path,
    *,
    repository_root: Path,
) -> Iterator[tuple[Path, Path]]:
    """Yield the v1 authority exactly as recorded by the v2 transition profile."""
    profile = validate_static_target_profile(profile_path, repository_root=repository_root)
    historical = profile["historicalEvidence"]
    inventory_descriptor = historical["dependencyInventory"]
    git_authority = historical["gitAuthority"]
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
    requested = {inventory_path, *inputs}

    commit = git_authority["commit"]
    actual_tree = _git(repository_root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if actual_tree != git_authority["tree"]:
        raise SupplyChainContractError("historical v1 Git tree does not match its authority")
    archive = _git(
        repository_root,
        "archive",
        "--format=tar",
        commit,
        "--",
        *(path.as_posix() for path in sorted(requested)),
    )

    with tempfile.TemporaryDirectory(prefix="searise-v1-authority-") as temporary:
        root = Path(temporary).resolve()
        extracted: set[PurePosixPath] = set()
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
                for member in bundle:
                    logical = _safe_path(member.name.removesuffix("/"))
                    if member.isdir():
                        continue
                    if logical not in requested or not member.isreg():
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
                    target.write_bytes(source.read())
                    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
                    extracted.add(logical)
        except (tarfile.TarError, OSError) as exc:
            raise SupplyChainContractError("historical v1 Git archive is invalid") from exc
        if extracted != requested:
            missing = sorted(path.as_posix() for path in requested - extracted)
            raise SupplyChainContractError(
                f"historical v1 Git archive is incomplete: {missing}"
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
        )
