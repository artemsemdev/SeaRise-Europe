"""Validate reviewed graph authority for flat hash-locked Python environments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from packaging.markers import UndefinedComparison, UndefinedEnvironmentName
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .contracts import SupplyChainContractError, _validate_schema

_LOCK_LINE = re.compile(
    r"(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"==(?P<version>[^\s]+) --hash=sha256:(?P<sha256>[0-9a-f]{64})"
)
_NORMALIZED_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PLATFORMS = {
    "darwin": ("Darwin", "arm64"),
    "linux": ("Linux", "x86_64"),
}


def _read_descriptor(descriptor: int, *, label: str, path: object) -> bytes:
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise SupplyChainContractError(f"{label} must be a regular file: {path}")
    chunks = []
    while chunk := os.read(descriptor, 131_072):
        chunks.append(chunk)
    return b"".join(chunks)


def _read_regular_bytes(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            return _read_descriptor(descriptor, label=label, path=path)
        finally:
            os.close(descriptor)
    except OSError as exc:
        if path.is_symlink():
            raise SupplyChainContractError(f"{label} must not be a symlink: {path}") from exc
        raise SupplyChainContractError(f"{label} could not be read: {path}") from exc


def _load_annotation(path: Path) -> dict[str, Any]:
    data = _read_regular_bytes(path, label="Python graph annotation")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SupplyChainContractError(f"duplicate annotation key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise SupplyChainContractError(f"invalid annotation numeric constant: {value}")

    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise SupplyChainContractError("Python graph annotation must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise SupplyChainContractError("Python graph annotation JSON is malformed") from exc
    if not isinstance(document, dict):
        raise SupplyChainContractError("Python graph annotation root must be an object")
    return document


def _logical_lock_path(value: str) -> PurePosixPath:
    logical = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        raise SupplyChainContractError(f"unsafe Python lock path: {value}")
    return logical


def _read_repository_file(root_descriptor: int, logical: PurePosixPath) -> bytes:
    directory = root_descriptor
    owned_directory = False
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in logical.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            if owned_directory:
                os.close(directory)
            directory, owned_directory = child, True
        file_flags = flags | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(logical.name, file_flags, dir_fd=directory)
        try:
            return _read_descriptor(descriptor, label="Python lock", path=logical)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"Python lock path must exist beneath the repository without symlinks: {logical}"
        ) from exc
    finally:
        if owned_directory:
            os.close(directory)


def _parse_lock(
    data: bytes, path: PurePosixPath, expected_sha256: str
) -> dict[str, tuple[str, str]]:
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SupplyChainContractError(f"Python lock SHA-256 mismatch: {path}")
    if b"\r" in data:
        raise SupplyChainContractError(f"Python lock must not use CRLF: {path}")
    if not data.endswith(b"\n"):
        raise SupplyChainContractError(f"Python lock must end with a newline: {path}")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SupplyChainContractError(f"Python lock must be UTF-8: {path}") from exc

    packages: dict[str, tuple[str, str]] = {}
    order = []
    for number, line in enumerate(lines, 1):
        if not line:
            continue
        if line.startswith("# "):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise SupplyChainContractError(f"Python lock line {number} is not canonical: {path}")
        name = str(canonicalize_name(match["name"]))
        if not _NORMALIZED_NAME.fullmatch(name):
            raise SupplyChainContractError(f"invalid normalized Python name: {name}")
        if name in packages:
            raise SupplyChainContractError(f"duplicate normalized Python name: {name}")
        try:
            Version(match["version"])
        except InvalidVersion as exc:
            raise SupplyChainContractError(f"invalid locked Python version: {name}") from exc
        packages[name] = (match["version"], match["sha256"])
        order.append(name)
    if not packages:
        raise SupplyChainContractError(f"Python lock has no packages: {path}")
    if order != sorted(order):
        raise SupplyChainContractError(f"Python lock packages must be sorted: {path}")
    return packages


def _validate_environment(environment: Mapping[str, str], target_id: str) -> None:
    if environment["platform_python_implementation"] != "CPython":
        raise SupplyChainContractError(f"Python implementation identity mismatch: {target_id}")
    if environment["implementation_version"] != environment["python_full_version"]:
        raise SupplyChainContractError(f"Python version identity mismatch: {target_id}")
    expected = _PLATFORMS[environment["sys_platform"]]
    actual = (environment["platform_system"], environment["platform_machine"])
    if actual != expected:
        raise SupplyChainContractError(f"Python platform identity mismatch: {target_id}")


def _requirement_active(
    requirement: Requirement,
    environments: list[Mapping[str, str]],
    source_extras: set[str],
) -> None:
    if requirement.marker is None:
        return
    results = []
    try:
        for environment in environments:
            contexts = ["", *sorted(source_extras)]
            results.append(
                any(
                    requirement.marker.evaluate({**environment, "extra": extra})
                    for extra in contexts
                )
            )
    except (UndefinedComparison, UndefinedEnvironmentName) as exc:
        raise SupplyChainContractError("unsupported Python requirement marker") from exc
    if len(set(results)) != 1:
        raise SupplyChainContractError("Python requirement marker diverges across targets")
    if not results[0]:
        raise SupplyChainContractError("Python requirement marker is inactive for targets")


def _assert_acyclic(graph: Mapping[str, set[str]]) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(name: str) -> None:
        if name in active:
            raise SupplyChainContractError(f"Python dependency graph contains a cycle: {name}")
        if name in visited:
            return
        active.add(name)
        for dependency in sorted(graph[name]):
            visit(dependency)
        active.remove(name)
        visited.add(name)

    for name in sorted(graph):
        visit(name)


def validate_python_lock_graph(
    annotation_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Validate one annotation as the sole reviewed root and edge authority."""
    document = _load_annotation(annotation_path)
    _validate_schema(document, "python-lock-graph.schema.json")

    targets = document["targets"]
    target_ids = [target["id"] for target in targets]
    if len(target_ids) != len(set(target_ids)) or target_ids != sorted(target_ids):
        raise SupplyChainContractError("Python graph targets must be unique and sorted")
    lock_paths = [target["lock"]["path"] for target in targets]
    if len(lock_paths) != len(set(lock_paths)):
        raise SupplyChainContractError("Python graph target lock paths must be unique")
    environments = []
    target_packages = []
    root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    root_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(repository_root.resolve(strict=True), root_flags)
    except OSError as exc:
        raise SupplyChainContractError("Python graph repository root could not be opened") from exc
    try:
        for target in targets:
            environment = target["markerEnvironment"]
            _validate_environment(environment, target["id"])
            environments.append(environment)
            lock = target["lock"]
            logical = _logical_lock_path(lock["path"])
            data = _read_repository_file(root_descriptor, logical)
            target_packages.append(_parse_lock(data, logical, lock["sha256"]))
    finally:
        os.close(root_descriptor)
    identities = [{name: value[0] for name, value in items.items()} for items in target_packages]
    if any(identity != identities[0] for identity in identities[1:]):
        raise SupplyChainContractError("Python targets must have an identical package/version set")

    packages = document["packages"]
    names = [item["name"] for item in packages]
    if len(names) != len(set(names)):
        raise SupplyChainContractError("Python graph package names must be unique")
    if names != sorted(names):
        raise SupplyChainContractError("Python graph packages must use stable sorted order")
    annotated = {item["name"]: item["version"] for item in packages}
    if annotated != identities[0]:
        raise SupplyChainContractError("Python graph package parity differs from its locks")

    by_name = {item["name"]: item for item in packages}
    graph = {name: set() for name in names}
    incoming_extras = {name: set() for name in names}
    roots = {item["name"] for item in packages if item["root"]}
    if not roots:
        raise SupplyChainContractError("Python dependency graph requires a reviewed root")
    for item in packages:
        extras = item["selectedExtras"]
        if extras != sorted(extras):
            raise SupplyChainContractError("Python selected extras must be sorted")
        dependency_names = [dependency["name"] for dependency in item["dependencies"]]
        if len(dependency_names) != len(set(dependency_names)):
            raise SupplyChainContractError("Python dependency edges must be unique")
        if dependency_names != sorted(dependency_names):
            raise SupplyChainContractError("Python dependencies must use stable sorted order")
        for dependency in item["dependencies"]:
            dependency_name = dependency["name"]
            if dependency_name == item["name"]:
                raise SupplyChainContractError("Python package must not depend on itself")
            if dependency_name not in by_name:
                raise SupplyChainContractError("Python dependency must reference a locked package")
            try:
                requirement = Requirement(dependency["requirement"])
            except InvalidRequirement as exc:
                raise SupplyChainContractError("invalid reviewed Python requirement") from exc
            if requirement.url is not None:
                raise SupplyChainContractError("Python dependency URL requirements are prohibited")
            if canonicalize_name(requirement.name) != dependency_name:
                raise SupplyChainContractError("Python dependency requirement name mismatch")
            if Version(by_name[dependency_name]["version"]) not in requirement.specifier:
                raise SupplyChainContractError(
                    "Python dependency requirement excludes lock version"
                )
            requested_extras = {str(canonicalize_name(extra)) for extra in requirement.extras}
            selected = set(by_name[dependency_name]["selectedExtras"])
            if not requested_extras.issubset(selected):
                raise SupplyChainContractError("Python requirement uses unselected extras")
            _requirement_active(requirement, environments, set(extras))
            graph[item["name"]].add(dependency_name)
            incoming_extras[dependency_name].update(requested_extras)

    for name, item in by_name.items():
        selected = set(item["selectedExtras"])
        if name not in roots and selected != incoming_extras[name]:
            raise SupplyChainContractError("Python selected extras lack incoming authority")
        if name in roots and not incoming_extras[name].issubset(selected):
            raise SupplyChainContractError("Python root selected extras omit incoming authority")
    _assert_acyclic(graph)
    reachable = set(roots)
    pending = list(roots)
    while pending:
        for dependency in graph[pending.pop()]:
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    if reachable != set(names):
        raise SupplyChainContractError("Python dependency graph contains unreachable packages")
    return document
