"""Immutable pre-verification evidence finalization for controlled candidates."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import sys
import tempfile
from ctypes import CDLL, c_char_p, c_int, get_errno
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    canonical_provenance_bytes,
    generate_provenance_statement,
    validate_candidate_document,
)

from .candidate_evidence import (
    _MANIFEST,
    _POLICY,
    _RECEIPT,
    _SBOM_PATHS,
    _SIGNATURE_PATHS,
    _open_root,
    _strict_json,
    _validate_sbom_authority,
)
from .contracts import (
    _IGNORED_DEPENDENCY_PARTS,
    REPOSITORY_ROOT,
    SupplyChainContractError,
    _component_for_input,
    _is_dependency_input,
    _role_for_input,
    _validate_real_source_unverified_evidence,
    _validate_schema,
    validate_dependency_inventory,
)

_PROVENANCE = PurePosixPath("provenance.intoto.jsonl")
_ENVELOPE = PurePosixPath("evidence-envelope.json")
_SBOM_ROOT = PurePosixPath("contracts/supply-chain/v1/sboms")
_DEPENDENCY_INVENTORY = PurePosixPath("contracts/supply-chain/v1/dependency-inventory.json")
_RUN_ID = re.compile(r"[1-9][0-9]*")
_TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
_MAX_RUN_ID_BYTES = 20
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_BUNDLE_BYTES = 8 * 1024 * 1024
_MAX_INVENTORY_BYTES = 1024 * 1024
_MAX_POLICY_BYTES = 64 * 1024
_MAX_DEPENDENCY_BYTES = 16 * 1024 * 1024
_MAX_SBOM_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_READ_BYTES = 128 * 1024 * 1024
_MAX_DISCOVERY_ENTRIES = 100_000
_MAX_DEPENDENCY_PATHS = 256
_MAX_QUARANTINE_ENTRIES = 4_096


@dataclass(frozen=True)
class ProductionEvidenceSummary:
    """Evidence identity committed at the durable publication checkpoint."""

    candidate_id: str
    evidence_root: Path
    evidence_sha256: str
    provenance_sha256: str
    sbom_count: int


@dataclass
class _ReadBudget:
    remaining: int = _MAX_TOTAL_READ_BYTES

    def reserve(self, size: int, label: str) -> None:
        if size > self.remaining:
            _fail(f"aggregate input byte limit exceeded while reading {label}")
        self.remaining -= size


@dataclass(frozen=True)
class _TreeRecord:
    kind: str
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int
    sha256: str | None


@dataclass(frozen=True)
class _SourceRecord:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int


def _fail(message: str) -> NoReturn:
    raise SupplyChainContractError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _same(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_mode) == (right.st_dev, right.st_ino, right.st_mode)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _bounded_names(directory: int, *, maximum: int, label: str) -> tuple[str, ...]:
    """Stream at most ``maximum`` descriptor-bound names, then sort that bounded set."""
    names: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(names) >= maximum:
                    _fail(f"{label} entry limit exceeded")
                names.append(entry.name)
        return tuple(sorted(names))
    except SupplyChainContractError:
        raise
    except (MemoryError, OSError, OverflowError) as exc:
        raise SupplyChainContractError(f"could not enumerate bounded {label}") from exc


def _logical(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str):
        _fail(f"{label} path must be a string")
    logical = PurePosixPath(value)
    if (
        not value
        or len(value) > 512
        or "\\" in value
        or logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        _fail(f"{label} path is unsafe")
    return logical


def _read_bounded(
    root: int,
    logical: PurePosixPath,
    label: str,
    *,
    maximum: int,
    budget: _ReadBudget,
) -> bytes:
    _logical(logical.as_posix(), label)
    directory = os.dup(root)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in logical.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            logical.name,
            flags | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory,
        )
        try:
            before = os.fstat(descriptor)
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or not _same_file(before, linked):
                _fail(f"{label} must be a regular file")
            if before.st_size > maximum:
                _fail(f"{label} exceeds its {maximum}-byte limit")
            budget.reserve(before.st_size, label)
            remaining = before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    _fail(f"{label} ended before its declared byte size")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                _fail(f"{label} grew beyond its declared byte size")
            after = os.fstat(descriptor)
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            raw = b"".join(chunks)
            if (
                not _same_file(before, after)
                or not _same_file(after, linked)
                or len(raw) != after.st_size
            ):
                _fail(f"{label} changed while it was read")
            return raw
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"{label} must be an existing bounded regular file without symlinks"
        ) from exc
    finally:
        os.close(directory)


def _read_external(path: Path, label: str, budget: _ReadBudget) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        _fail(f"{label} path must be absolute and canonical")
    root = _open_root(path.parent, f"{label} parent")
    try:
        return _read_bounded(
            root,
            _logical(path.name, label),
            label,
            maximum=_MAX_BUNDLE_BYTES,
            budget=budget,
        )
    finally:
        os.close(root)


def _create_directory(parent: int, name: str, label: str) -> int:
    _logical(name, label)
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not _same(os.fstat(descriptor), linked):
            _fail(f"{label} directory changed during creation")
        return descriptor
    except Exception as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        if isinstance(exc, SupplyChainContractError):
            raise
        if not isinstance(exc, OSError):
            raise
        raise SupplyChainContractError(f"could not create private {label} directory") from exc


def _candidate_snapshot(
    candidate_root: Path,
    destination: Path,
    destination_descriptor: int,
    budget: _ReadBudget,
) -> tuple[Path, Mapping[str, Any], bytes, dict[PurePosixPath, bytes]]:
    descriptor = _open_root(candidate_root, "candidate")
    try:
        manifest_raw = _read_bounded(
            descriptor,
            _MANIFEST,
            "candidate manifest",
            maximum=_MAX_MANIFEST_BYTES,
            budget=budget,
        )
        manifest = _strict_json(manifest_raw, "candidate manifest")
        try:
            validate_candidate_document(manifest)
        except CandidateContractError as exc:
            raise SupplyChainContractError(str(exc)) from exc
        expected = {_MANIFEST: manifest_raw}
        expected[_RECEIPT] = _read_bounded(
            descriptor,
            _RECEIPT,
            "candidate build receipt",
            maximum=_MAX_RECEIPT_BYTES,
            budget=budget,
        )
        for artifact in manifest["artifacts"]:
            if artifact["role"] == "source-receipt":
                logical = _logical(artifact["path"], "candidate source receipt")
                if logical in expected:
                    _fail(f"duplicate candidate snapshot path: {logical}")
                expected[logical] = _read_bounded(
                    descriptor,
                    logical,
                    "candidate source receipt",
                    maximum=_MAX_RECEIPT_BYTES,
                    budget=budget,
                )
        for logical, raw in expected.items():
            _snapshot_fd(destination_descriptor, logical, raw)
    finally:
        os.close(descriptor)
    return destination / _MANIFEST, manifest, manifest_raw, expected


def _source_record(value: os.stat_result) -> _SourceRecord:
    return _SourceRecord(
        device=value.st_dev,
        inode=value.st_ino,
        mode=value.st_mode,
        size=value.st_size,
        modified_ns=value.st_mtime_ns,
        changed_ns=value.st_ctime_ns,
    )


def _discover_source_dependencies(
    root: int,
) -> tuple[tuple[PurePosixPath, ...], Mapping[tuple[str, ...], _SourceRecord]]:
    discovered: list[PurePosixPath] = []
    records: dict[tuple[str, ...], _SourceRecord] = {}
    visited = 0
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )

    def walk(directory: int, prefix: tuple[str, ...]) -> None:
        nonlocal visited
        before = os.fstat(directory)
        if not stat.S_ISDIR(before.st_mode):
            _fail("repository discovery root must remain a directory")
        records[prefix] = _source_record(before)
        names = _bounded_names(
            directory,
            maximum=_MAX_DISCOVERY_ENTRIES - visited,
            label="repository discovery",
        )
        visited += len(names)
        for name in names:
            logical = _logical(PurePosixPath(*prefix, name).as_posix(), "repository discovery")
            if name in _IGNORED_DEPENDENCY_PARTS:
                continue
            try:
                linked = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except OSError as exc:
                raise SupplyChainContractError(
                    f"repository discovery entry changed before inspection: {logical}"
                ) from exc
            child_path = (*prefix, name)
            if stat.S_ISLNK(linked.st_mode):
                _fail(f"repository discovery must not traverse symlinks: {logical}")
            if stat.S_ISDIR(linked.st_mode):
                try:
                    child = os.open(name, directory_flags, dir_fd=directory)
                except OSError as exc:
                    raise SupplyChainContractError(
                        f"repository discovery directory changed while opening: {logical}"
                    ) from exc
                try:
                    if not _same_file(os.fstat(child), linked):
                        _fail(f"repository discovery directory was replaced: {logical}")
                    walk(child, child_path)
                    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if not _same_file(os.fstat(child), current):
                        _fail(f"repository discovery directory changed: {logical}")
                finally:
                    os.close(child)
            elif _is_dependency_input(logical):
                if not stat.S_ISREG(linked.st_mode):
                    _fail(f"dependency input must be a regular file: {logical}")
                discovered.append(logical)
                if len(discovered) > _MAX_DEPENDENCY_PATHS:
                    _fail("repository dependency path limit exceeded")
                records[child_path] = _source_record(linked)
        after = os.fstat(directory)
        if not _same_file(before, after):
            _fail("repository discovery directory changed during enumeration")

    walk(root, ())
    return tuple(sorted(discovered)), records


def _require_current_source_root(
    repository_root: Path,
    held_root: int,
    expected: os.stat_result,
) -> None:
    if not _same_file(expected, os.fstat(held_root)):
        _fail("held repository root changed during finalization")
    current = _open_root(repository_root, "current repository")
    try:
        if not _same(expected, os.fstat(current)):
            _fail("repository root path changed during finalization")
    finally:
        os.close(current)


def _repository_snapshots(
    repository_root: Path,
    destination: Path,
    destination_descriptor: int,
    budget: _ReadBudget,
) -> tuple[
    bytes,
    dict[str, bytes],
    dict[PurePosixPath, bytes],
    Mapping[tuple[str, ...], _TreeRecord],
]:
    descriptor = _open_root(repository_root, "repository")
    try:
        source_identity = os.fstat(descriptor)
        policy = _read_bounded(
            descriptor,
            _POLICY,
            "identity policy",
            maximum=_MAX_POLICY_BYTES,
            budget=budget,
        )
        inventory_raw = _read_bounded(
            descriptor,
            _DEPENDENCY_INVENTORY,
            "dependency inventory",
            maximum=_MAX_INVENTORY_BYTES,
            budget=budget,
        )
        inventory = _strict_json(inventory_raw, "dependency inventory")
        _validate_schema(inventory, "dependency-inventory.schema.json")
        try:
            dependency_records = tuple(
                (component["id"], item["role"], _logical(item["path"], "dependency input"))
                for component in inventory["components"]
                for item in component["inputs"]
            )
        except (KeyError, TypeError) as exc:
            raise SupplyChainContractError("dependency input inventory is malformed") from exc
        for component_id, role, logical in dependency_records:
            if _component_for_input(logical) != component_id or _role_for_input(logical) != role:
                _fail(f"dependency input classification is invalid: {logical}")
        dependency_paths = tuple(record[2] for record in dependency_records)
        if len(dependency_paths) > _MAX_DEPENDENCY_PATHS or len(dependency_paths) != len(
            set(dependency_paths)
        ):
            _fail("dependency input inventory contains an unsafe path count or duplicate")
        discovered, source_baseline = _discover_source_dependencies(descriptor)
        if discovered != tuple(sorted(dependency_paths)):
            missing = sorted(set(discovered) - set(dependency_paths))
            extra = sorted(set(dependency_paths) - set(discovered))
            _fail(f"dependency discovery mismatch; unclassified={missing}, extra={extra}")
        repository_files = {_POLICY: policy, _DEPENDENCY_INVENTORY: inventory_raw}
        recorded_sha256 = {
            _logical(item["path"], "dependency input"): item["sha256"]
            for component in inventory["components"]
            for item in component["inputs"]
        }
        for logical in dependency_paths:
            raw = _read_bounded(
                descriptor,
                logical,
                f"dependency input {logical}",
                maximum=_MAX_DEPENDENCY_BYTES,
                budget=budget,
            )
            if _sha256(raw) != recorded_sha256[logical]:
                _fail(f"dependency input SHA-256 mismatch: {logical}")
            repository_files[logical] = raw
        sboms: dict[str, bytes] = {}
        for logical in _SBOM_PATHS:
            source = _SBOM_ROOT / PurePosixPath(logical).relative_to("sbom")
            raw = _read_bounded(
                descriptor,
                source,
                f"repository {source}",
                maximum=_MAX_SBOM_BYTES,
                budget=budget,
            )
            sboms[logical] = raw
            if source in repository_files:
                _fail(f"repository snapshot path is duplicated: {source}")
            repository_files[source] = raw
        for logical, raw in repository_files.items():
            _snapshot_fd(destination_descriptor, logical, raw)
        baseline = _validate_tree(destination_descriptor, repository_files)
        validate_dependency_inventory(
            destination / _DEPENDENCY_INVENTORY,
            repository_root=destination,
        )
        for logical in _SBOM_PATHS:
            source = _SBOM_ROOT / PurePosixPath(logical).relative_to("sbom")
            _validate_sbom_authority(logical, destination / source, destination)
        _validate_tree(destination_descriptor, repository_files, baseline=baseline)
        current_discovery, current_records = _discover_source_dependencies(descriptor)
        if current_discovery != discovered or current_records != source_baseline:
            _fail("repository dependency discovery changed during finalization")
        _require_current_source_root(repository_root, descriptor, source_identity)
        return policy, sboms, repository_files, baseline
    finally:
        os.close(descriptor)


def _descriptor(path: str, raw: bytes, **fields: object) -> dict[str, object]:
    return {"path": path, "sha256": _sha256(raw), "byteSize": len(raw), **fields}


def _evidence_sha256(files: Mapping[PurePosixPath, bytes]) -> str:
    inventory = [
        _descriptor(logical.as_posix(), files[logical])
        for logical in sorted(files, key=lambda item: item.as_posix())
    ]
    return _sha256(canonical_provenance_bytes({"files": inventory}))


def _envelope(
    manifest: Mapping[str, Any],
    manifest_raw: bytes,
    provenance_raw: bytes,
    policy_raw: bytes,
    bundles: Mapping[str, bytes],
    sboms: Mapping[str, bytes],
) -> dict[str, object]:
    signatures = [
        _descriptor(
            path,
            bundles[path],
            role="signature",
            mediaType="application/vnd.dev.sigstore.bundle+json;version=0.3",
            subjectPath=subject,
            subjectSha256=_sha256(manifest_raw if subject == "manifest.json" else provenance_raw),
        )
        for path, subject in zip(_SIGNATURE_PATHS, ("manifest.json", "provenance.intoto.jsonl"))
    ]
    return {
        "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/real-source-unverified-evidence-envelope.schema.json",
        "schemaVersion": "1.0.0",
        "contractId": "phase-1-real-source-unverified-evidence-v1",
        "candidateId": manifest["candidateId"],
        "dataReleaseId": manifest["dataReleaseId"],
        "dataProvenanceClass": manifest["dataProvenanceClass"],
        "candidateManifest": _descriptor("manifest.json", manifest_raw),
        "identityPolicy": {
            "path": "contracts/supply-chain/v1/identity-policy.json",
            "sha256": _sha256(policy_raw),
        },
        "provenance": _descriptor(
            "provenance.intoto.jsonl",
            provenance_raw,
            role="provenance",
            mediaType="application/vnd.in-toto+json",
            statementType="https://in-toto.io/Statement/v1",
            predicateType="https://slsa.dev/provenance/v1",
        ),
        "signatures": signatures,
        "softwareBillsOfMaterials": [
            _descriptor(
                logical,
                sboms[logical],
                role="software-bill-of-materials",
                mediaType="application/vnd.cyclonedx+json",
                bomFormat="CycloneDX",
                specVersion="1.7",
            )
            for logical in _SBOM_PATHS
        ],
        "verification": {
            "status": "real-source-unverified",
            "fixtureOnly": False,
            "verified": False,
            "policySatisfied": False,
            "productionClaim": False,
            "publicationClaim": False,
            "scientificApproval": False,
            "reason": (
                "Cryptographic verification has not run; no signing, identity, "
                "environment, production, publication, or scientific approval "
                "claim is made."
            ),
        },
    }


def _new_stage(parent: int) -> tuple[str, int, os.stat_result]:
    for _ in range(128):
        name = f".evidence-incomplete-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            continue
        descriptor = os.open(
            name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        try:
            return name, descriptor, os.fstat(descriptor)
        except Exception:
            os.close(descriptor)
            raise
    _fail("could not reserve a private evidence staging directory")


def _snapshot_fd(root: int, logical: PurePosixPath, raw: bytes) -> None:
    _logical(logical.as_posix(), "snapshot")
    directory = os.dup(root)
    directories = [directory]
    flags = (
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for part in logical.parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=directory)
            try:
                linked = os.stat(part, dir_fd=directory, follow_symlinks=False)
                if not _same(os.fstat(child), linked):
                    _fail("evidence staging directory changed while it was opened")
            except Exception:
                os.close(child)
                raise
            directory = child
            directories.append(directory)
        descriptor = os.open(
            logical.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o400,
            dir_fd=directory,
        )
        try:
            view = memoryview(raw)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("evidence write made no progress")
                view = view[count:]
            os.fsync(descriptor)
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            current = os.fstat(descriptor)
            if not _same_file(current, linked) or current.st_size != len(raw):
                _fail("descriptor-bound evidence file changed while it was written")
        finally:
            os.close(descriptor)
        for item in reversed(directories):
            os.fsync(item)
    except OSError as exc:
        raise SupplyChainContractError("could not write descriptor-bound evidence stage") from exc
    finally:
        for item in directories:
            try:
                os.close(item)
            except OSError:
                pass


def _record(value: os.stat_result, kind: str, sha256: str | None = None) -> _TreeRecord:
    return _TreeRecord(
        kind=kind,
        device=value.st_dev,
        inode=value.st_ino,
        mode=value.st_mode,
        links=value.st_nlink,
        size=value.st_size,
        modified_ns=value.st_mtime_ns,
        changed_ns=value.st_ctime_ns,
        sha256=sha256,
    )


def _validate_tree(
    root: int,
    expected: Mapping[PurePosixPath, bytes],
    *,
    baseline: Mapping[tuple[str, ...], _TreeRecord] | None = None,
    allow_root_rename: bool = False,
) -> Mapping[tuple[str, ...], _TreeRecord]:
    expected_files = {tuple(logical.parts): raw for logical, raw in expected.items()}
    if len(expected_files) != len(expected):
        _fail("expected tree contains duplicate logical paths")
    expected_directories = {()}
    for parts in expected_files:
        expected_directories.update(parts[:index] for index in range(1, len(parts)))
    records: dict[tuple[str, ...], _TreeRecord] = {}

    def walk(directory: int, prefix: tuple[str, ...]) -> None:
        current = os.fstat(directory)
        if not stat.S_ISDIR(current.st_mode) or stat.S_IMODE(current.st_mode) != 0o700:
            _fail("evidence tree directories must remain private directories")
        records[prefix] = _record(current, "directory")
        expected_names = {
            parts[len(prefix)]
            for parts in (*expected_directories, *expected_files)
            if len(parts) == len(prefix) + 1 and parts[: len(prefix)] == prefix
        }
        actual_names = set(
            _bounded_names(
                directory,
                maximum=len(expected_names),
                label="evidence tree",
            )
        )
        if actual_names != expected_names:
            _fail("evidence tree contains a foreign or missing entry")
        for name in sorted(expected_names):
            child_path = (*prefix, name)
            linked = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if child_path in expected_directories:
                flags = (
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                child = os.open(name, flags, dir_fd=directory)
                try:
                    if not _same(os.fstat(child), linked):
                        _fail("evidence directory subtree was replaced")
                    walk(child, child_path)
                finally:
                    os.close(child)
                continue
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            child = os.open(name, flags, dir_fd=directory)
            try:
                before = os.fstat(child)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or stat.S_IMODE(before.st_mode) != 0o400
                    or not _same_file(before, linked)
                ):
                    _fail("evidence tree entry is not the expected private regular file")
                raw = expected_files[child_path]
                if before.st_size != len(raw):
                    _fail("evidence tree file size changed before publication")
                chunks: list[bytes] = []
                remaining = len(raw)
                while remaining:
                    chunk = os.read(child, min(1024 * 1024, remaining))
                    if not chunk:
                        _fail("evidence tree file ended before its expected size")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if os.read(child, 1):
                    _fail("evidence tree file exceeds its expected size")
                after = os.fstat(child)
                linked = os.stat(name, dir_fd=directory, follow_symlinks=False)
                digest = _sha256(b"".join(chunks))
                if (
                    not _same_file(before, after)
                    or not _same_file(after, linked)
                    or digest != _sha256(raw)
                ):
                    _fail("evidence tree file identity or SHA-256 changed")
                records[child_path] = _record(after, "file", digest)
            finally:
                os.close(child)

    walk(root, ())
    if baseline is not None:
        comparable = records
        if allow_root_rename and () in records and () in baseline:
            comparable = dict(records)
            current_root = records[()]
            original_root = baseline[()]
            comparable[()] = _TreeRecord(
                kind=current_root.kind,
                device=current_root.device,
                inode=current_root.inode,
                mode=current_root.mode,
                links=current_root.links,
                size=current_root.size,
                modified_ns=original_root.modified_ns,
                changed_ns=original_root.changed_ns,
                sha256=current_root.sha256,
            )
        if comparable != baseline:
            _fail(
                "evidence tree device, inode, mode, link count, size, timestamps, or SHA-256 "
                "changed"
            )
    return records


def _rename_exclusive(parent: int, source: str, destination: str) -> None:
    library = CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = library.renameatx_np
        rename.argtypes = (c_int, c_char_p, c_int, c_char_p, c_int)
        result = rename(parent, source.encode(), parent, destination.encode(), 0x00000004)
    else:
        try:
            rename = library.renameat2
        except AttributeError as exc:
            raise SupplyChainContractError(
                "exclusive immutable evidence publication is unavailable on this platform"
            ) from exc
        rename.argtypes = (c_int, c_char_p, c_int, c_char_p, c_int)
        result = rename(parent, source.encode(), parent, destination.encode(), 1)
    if result != 0:
        error = get_errno()
        if error == 17:
            _fail("output evidence root already exists")
        raise OSError(error, os.strerror(error))


def _require_published_tree(
    parent: int,
    expected_stage: os.stat_result,
    stage_descriptor: int,
    expected_tree: Mapping[PurePosixPath, bytes],
    baseline: Mapping[tuple[str, ...], _TreeRecord],
    output_name: str,
) -> None:
    try:
        published = os.stat(output_name, dir_fd=parent, follow_symlinks=False)
    except OSError as exc:
        raise SupplyChainContractError(
            "published evidence pathname is unavailable at the durable checkpoint"
        ) from exc
    if not _same(expected_stage, published):
        _fail("published evidence directory identity changed at the durable checkpoint")
    _validate_tree(
        stage_descriptor,
        expected_tree,
        baseline=baseline,
        allow_root_rename=True,
    )
    published = os.stat(output_name, dir_fd=parent, follow_symlinks=False)
    if not _same(expected_stage, published):
        _fail("published evidence directory was replaced after tree validation")


def _publish(
    parent: int,
    expected_parent: os.stat_result,
    expected_stage: os.stat_result,
    stage_descriptor: int,
    expected_tree: Mapping[PurePosixPath, bytes],
    baseline: Mapping[tuple[str, ...], _TreeRecord],
    output_parent_path: Path,
    stage: str,
    output_name: str,
) -> None:
    try:
        current_parent = os.stat(output_parent_path, follow_symlinks=False)
        if not _same(expected_parent, current_parent):
            _fail("output evidence parent changed during finalization")
        current_stage = os.stat(stage, dir_fd=parent, follow_symlinks=False)
        if not _same(expected_stage, current_stage) or not _same(
            expected_stage, os.fstat(stage_descriptor)
        ):
            _fail("owned evidence staging directory changed before publication")
        _validate_tree(stage_descriptor, expected_tree, baseline=baseline)
        _rename_exclusive(parent, stage, output_name)
    except OSError as exc:
        raise SupplyChainContractError("could not publish immutable evidence root") from exc
    try:
        _require_published_tree(
            parent,
            expected_stage,
            stage_descriptor,
            expected_tree,
            baseline,
            output_name,
        )
        os.fsync(parent)
        published = os.stat(output_name, dir_fd=parent, follow_symlinks=False)
        if not _same(expected_stage, published):
            _fail("published evidence directory changed after parent fsync")
    except Exception as primary:
        _quarantine_failed_publication(parent, expected_stage, output_name)
        if isinstance(primary, SupplyChainContractError):
            raise
        raise SupplyChainContractError(
            "could not durably publish immutable evidence root"
        ) from primary


def _owned_name(parent: int, expected: os.stat_result, names: tuple[str, ...]) -> str | None:
    owned: list[str] = []
    for name in names:
        try:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if _same_inode(expected, current):
            owned.append(name)
            if len(owned) > 1:
                return None
    return owned[0] if owned else None


def _move_owned_to_residue(parent: int, expected: os.stat_result, output_name: str) -> str | None:
    owned_name = _owned_name(parent, expected, (output_name,))
    if owned_name is None:
        names = _bounded_names(
            parent,
            maximum=_MAX_QUARANTINE_ENTRIES,
            label="publication quarantine",
        )
        owned_name = _owned_name(parent, expected, names)
    if owned_name is None:
        return None
    for _ in range(128):
        residue = f".evidence-incomplete-{secrets.token_hex(16)}"
        try:
            os.stat(residue, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            try:
                _rename_exclusive(parent, owned_name, residue)
            except SupplyChainContractError:
                continue
            moved = os.stat(residue, dir_fd=parent, follow_symlinks=False)
            if not _same_inode(expected, moved):
                try:
                    _rename_exclusive(parent, residue, owned_name)
                    os.fsync(parent)
                except Exception:
                    pass
                return None
            os.fsync(parent)
            return residue
    return None


def _quarantine_failed_publication(parent: int, expected: os.stat_result, output_name: str) -> None:
    cleanup_error: Exception | None = None
    try:
        _move_owned_to_residue(parent, expected, output_name)
    except Exception as exc:
        cleanup_error = exc
    owned_at_output = _owned_name(parent, expected, (output_name,))
    if owned_at_output is not None:
        raise SupplyChainContractError(
            "failed evidence publication could not be quarantined from the final pathname"
        ) from cleanup_error


def _output_parent(output_root: Path) -> int:
    if not output_root.is_absolute() or ".." in output_root.parts or not output_root.name:
        _fail("output evidence root must be absolute and canonical")
    return _open_root(output_root.parent, "output evidence parent")


def _require_absent(parent: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    _fail("output evidence root already exists")


def finalize_production_evidence(
    candidate_root: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    controlled_build_run_id: str,
    manifest_bundle: Path,
    provenance_bundle: Path,
    output_root: Path,
) -> ProductionEvidenceSummary:
    """Commit exact evidence at one durable pathname checkpoint without outcome claims.

    The returned content digest remains authoritative if a same-user actor later
    displaces the pathname; consumers must revalidate the path against that digest.
    """
    if (
        len(controlled_build_run_id.encode("utf-8")) > _MAX_RUN_ID_BYTES
        or _RUN_ID.fullmatch(controlled_build_run_id) is None
    ):
        _fail("controlled build run ID must be one canonical positive integer")
    if output_root.exists() or output_root.is_symlink():
        _fail("output evidence root already exists")
    output_parent = _output_parent(output_root)
    try:
        budget = _ReadBudget(_MAX_TOTAL_READ_BYTES)
        output_parent_identity = os.fstat(output_parent)
        _require_absent(output_parent, output_root.name)
        bundle_raw = {
            _SIGNATURE_PATHS[0]: _read_external(manifest_bundle, "manifest bundle", budget),
            _SIGNATURE_PATHS[1]: _read_external(provenance_bundle, "provenance bundle", budget),
        }
        with tempfile.TemporaryDirectory(
            prefix="searise-production-evidence-", dir=_TEMP_ROOT
        ) as temp:
            root = Path(temp)
            candidate_snapshot = root / "candidate"
            repository_snapshot = root / "repository"
            snapshot_parent = _open_root(root, "private snapshot")
            try:
                candidate_descriptor = _create_directory(
                    snapshot_parent, "candidate", "candidate snapshot"
                )
            except Exception:
                os.close(snapshot_parent)
                raise
            try:
                repository_descriptor = _create_directory(
                    snapshot_parent, "repository", "repository snapshot"
                )
            except Exception:
                os.close(candidate_descriptor)
                os.close(snapshot_parent)
                raise
            try:
                manifest_path, manifest, manifest_raw, candidate_files = _candidate_snapshot(
                    candidate_root,
                    candidate_snapshot,
                    candidate_descriptor,
                    budget,
                )
                candidate_baseline = _validate_tree(candidate_descriptor, candidate_files)
                (
                    policy_raw,
                    sboms,
                    repository_files,
                    repository_baseline,
                ) = _repository_snapshots(
                    repository_root,
                    repository_snapshot,
                    repository_descriptor,
                    budget,
                )
                provenance_raw = canonical_provenance_bytes(
                    generate_provenance_statement(
                        manifest_path,
                        candidate_snapshot / _RECEIPT,
                        trusted_invocation_uri=(
                            "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/"
                            f"{controlled_build_run_id}/attempts/1"
                        ),
                    )
                )
                _validate_tree(
                    candidate_descriptor,
                    candidate_files,
                    baseline=candidate_baseline,
                )
                _validate_tree(
                    repository_descriptor,
                    repository_files,
                    baseline=repository_baseline,
                )
                envelope_raw = canonical_provenance_bytes(
                    _envelope(
                        manifest,
                        manifest_raw,
                        provenance_raw,
                        policy_raw,
                        bundle_raw,
                        sboms,
                    )
                )
                _validate_real_source_unverified_evidence(
                    envelope_raw,
                    manifest_raw,
                    provenance_raw,
                    policy_raw,
                    bundle_raw,
                    sboms,
                )
            finally:
                os.close(candidate_descriptor)
                os.close(repository_descriptor)
                os.close(snapshot_parent)
            stage_files = {
                _PROVENANCE: provenance_raw,
                **{PurePosixPath(logical): raw for logical, raw in bundle_raw.items()},
                **{PurePosixPath(logical): raw for logical, raw in sboms.items()},
                _ENVELOPE: envelope_raw,
            }
            evidence_sha256 = _evidence_sha256(stage_files)
            stage_name, stage_descriptor, stage_identity = _new_stage(output_parent)
            try:
                for logical, raw in stage_files.items():
                    _snapshot_fd(stage_descriptor, logical, raw)
                os.fsync(stage_descriptor)
                stage_baseline = _validate_tree(stage_descriptor, stage_files)
                _publish(
                    output_parent,
                    output_parent_identity,
                    stage_identity,
                    stage_descriptor,
                    stage_files,
                    stage_baseline,
                    output_root.parent,
                    stage_name,
                    output_root.name,
                )
                try:
                    _require_published_tree(
                        output_parent,
                        stage_identity,
                        stage_descriptor,
                        stage_files,
                        stage_baseline,
                        output_root.name,
                    )
                except Exception as primary:
                    _quarantine_failed_publication(
                        output_parent,
                        stage_identity,
                        output_root.name,
                    )
                    if isinstance(primary, SupplyChainContractError):
                        raise
                    raise SupplyChainContractError(
                        "published evidence changed before the durable result checkpoint"
                    ) from primary
            finally:
                os.close(stage_descriptor)
    finally:
        os.close(output_parent)
    return ProductionEvidenceSummary(
        candidate_id=str(manifest["candidateId"]),
        evidence_root=output_root,
        evidence_sha256=evidence_sha256,
        provenance_sha256=_sha256(provenance_raw),
        sbom_count=len(_SBOM_PATHS),
    )
