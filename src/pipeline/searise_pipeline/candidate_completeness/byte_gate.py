"""Descriptor-bound byte validation for one assembled Phase 1 candidate."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn

from .validator import CandidateContractError, load_candidate_bytes, validate_candidate_document

_MANIFEST = PurePosixPath("manifest.json")
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_READ_SIZE = 1024 * 1024
_IDENTITY_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


@dataclass(frozen=True)
class CandidateByteSummary:
    """Stable result of validating every declared candidate byte."""

    candidate_id: str
    data_release_id: str
    artifact_count: int
    artifact_bytes: int
    manifest_sha256: str
    production: bool = False
    publication: bool = False


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return tuple(int(getattr(value, field)) for field in _IDENTITY_FIELDS)


def _open_root(path: Path) -> int:
    if ".." in path.parts:
        _fail("candidate-root", "candidate root must not contain parent traversal")
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, flags)
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise CandidateContractError(
            "candidate-root", "candidate root must be an existing directory without symlinks"
        ) from exc


def _logical(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        _fail("candidate-path", "artifact path must be one canonical relative POSIX path")
    logical = PurePosixPath(value)
    if (
        logical.is_absolute()
        or logical.as_posix() != value
        or any(part in ("", ".", "..") for part in logical.parts)
    ):
        _fail("candidate-path", f"artifact path escapes or is not canonical: {value}")
    return logical


def _expected_tree(paths: set[PurePosixPath]) -> dict[PurePosixPath, dict[str, str]]:
    tree: dict[PurePosixPath, dict[str, str]] = {PurePosixPath(): {}}
    for logical in sorted(paths, key=lambda item: item.as_posix()):
        parent = PurePosixPath()
        for part in logical.parts[:-1]:
            previous = tree.setdefault(parent, {}).setdefault(part, "directory")
            if previous != "directory":
                _fail("candidate-files", f"artifact path collides with a file: {logical}")
            parent /= part
            tree.setdefault(parent, {})
        previous = tree[parent].setdefault(logical.name, "file")
        if previous != "file":
            _fail("candidate-files", f"artifact path collides with a directory: {logical}")
    return tree


def _open_directory(root: int, logical: PurePosixPath) -> int:
    descriptor = os.dup(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in logical.parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _inspect_tree(
    root: int, tree: Mapping[PurePosixPath, Mapping[str, str]]
) -> dict[PurePosixPath, tuple[int, ...]]:
    identities: dict[PurePosixPath, tuple[int, ...]] = {PurePosixPath(): _identity(os.fstat(root))}
    try:
        for parent, expected in sorted(tree.items(), key=lambda item: item[0].as_posix()):
            directory = _open_directory(root, parent)
            try:
                actual = set(os.listdir(directory))
                if actual != set(expected):
                    missing = sorted(set(expected) - actual)
                    extra = sorted(actual - set(expected))
                    _fail(
                        "candidate-files",
                        f"candidate tree differs at {parent or '.'}: "
                        f"missing={missing}, extra={extra}",
                    )
                for name, kind in expected.items():
                    metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    mode = metadata.st_mode
                    if (kind == "file" and not stat.S_ISREG(mode)) or (
                        kind == "directory" and not stat.S_ISDIR(mode)
                    ):
                        _fail(
                            "candidate-files",
                            f"candidate entry has the wrong type: {parent / name}",
                        )
                    identities[parent / name] = _identity(metadata)
            finally:
                os.close(directory)
    except CandidateContractError:
        raise
    except OSError as exc:
        raise CandidateContractError(
            "candidate-files",
            "candidate tree must contain only stable regular files and directories",
        ) from exc
    return identities


def _read_file(
    root: int,
    logical: PurePosixPath,
    *,
    expected_size: int | None,
    expected_sha256: str | None,
    expected_content: bytes | None = None,
    capture_limit: int | None = None,
) -> tuple[bytes | None, str, int]:
    directory = _open_directory(root, logical.parent)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(logical.name, flags, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or _identity(before) != _identity(linked)
            ):
                _fail("artifact-bytes", f"artifact is not one stable regular file: {logical}")
            if expected_size is not None and before.st_size != expected_size:
                _fail("artifact-bytes", f"artifact byte size differs: {logical}")
            if capture_limit is not None and before.st_size > capture_limit:
                _fail("manifest-bytes", "candidate manifest exceeds the validation limit")
            digest = hashlib.sha256()
            chunks: list[bytes] | None = [] if capture_limit is not None else None
            offset = 0
            while offset < before.st_size:
                chunk = os.read(descriptor, min(_READ_SIZE, before.st_size - offset))
                if not chunk:
                    _fail("artifact-bytes", f"artifact ended before its declared size: {logical}")
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
                if (
                    expected_content is not None
                    and chunk != expected_content[offset : offset + len(chunk)]
                ):
                    _fail("checksum-file", "checksums.txt does not match the manifest subjects")
                offset += len(chunk)
            if os.read(descriptor, 1):
                _fail("artifact-bytes", f"artifact exceeds its declared size: {logical}")
            after = os.fstat(descriptor)
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            if _identity(before) != _identity(after) or _identity(after) != _identity(linked):
                _fail("candidate-changed", f"artifact changed while it was read: {logical}")
            observed = digest.hexdigest()
            if expected_sha256 is not None and observed != expected_sha256:
                _fail("artifact-bytes", f"artifact SHA-256 differs: {logical}")
            return (b"".join(chunks) if chunks is not None else None), observed, before.st_size
        finally:
            os.close(descriptor)
    except CandidateContractError:
        raise
    except OSError as exc:
        raise CandidateContractError(
            "artifact-bytes", f"artifact cannot be opened safely: {logical}"
        ) from exc
    finally:
        os.close(directory)


def _checksum_bytes(candidate: Mapping[str, Any]) -> bytes:
    subjects = candidate["checksumInventory"]["subjects"]
    return "".join(f"{item['sha256']}  {item['path']}\n" for item in subjects).encode("utf-8")


def validate_candidate_root(candidate_root: Path) -> CandidateByteSummary:
    """Validate exact candidate bytes without writing, repairing, or approving them."""
    root = _open_root(candidate_root)
    try:
        manifest_raw, manifest_sha256, _ = _read_file(
            root,
            _MANIFEST,
            expected_size=None,
            expected_sha256=None,
            capture_limit=_MAX_MANIFEST_BYTES,
        )
        if manifest_raw is None:  # Defensive: capture_limit always requests captured bytes.
            _fail("manifest-bytes", "candidate manifest bytes were not captured")
        candidate = load_candidate_bytes(manifest_raw)
        summary = validate_candidate_document(candidate)
        artifacts = candidate["artifacts"]
        logical_artifacts = {_logical(item["path"]): item for item in artifacts}
        if len(logical_artifacts) != summary.artifact_count or _MANIFEST in logical_artifacts:
            _fail("candidate-files", "manifest and artifact paths must be distinct and exact")
        expected_paths = set(logical_artifacts) | {_MANIFEST}
        tree = _expected_tree(expected_paths)
        baseline = _inspect_tree(root, tree)
        checksum_content = _checksum_bytes(candidate)
        artifact_bytes = 0
        for logical, artifact in logical_artifacts.items():
            expected_content = (
                checksum_content if logical == PurePosixPath("checksums.txt") else None
            )
            if expected_content is not None and len(expected_content) != artifact["byteSize"]:
                _fail("checksum-file", "checksums.txt byte size differs from canonical subjects")
            _, _, byte_size = _read_file(
                root,
                logical,
                expected_size=artifact["byteSize"],
                expected_sha256=artifact["sha256"],
                expected_content=expected_content,
            )
            artifact_bytes += byte_size
        final_manifest, final_sha256, _ = _read_file(
            root,
            _MANIFEST,
            expected_size=len(manifest_raw),
            expected_sha256=manifest_sha256,
            capture_limit=_MAX_MANIFEST_BYTES,
        )
        if final_manifest != manifest_raw or final_sha256 != manifest_sha256:
            _fail("candidate-changed", "candidate manifest changed during validation")
        if _inspect_tree(root, tree) != baseline:
            _fail("candidate-changed", "candidate tree changed during validation")
        reopened = _open_root(candidate_root)
        try:
            if _identity(os.fstat(reopened)) != _identity(os.fstat(root)):
                _fail("candidate-changed", "candidate root changed during validation")
        finally:
            os.close(reopened)
        return CandidateByteSummary(
            candidate_id=summary.candidate_id,
            data_release_id=summary.data_release_id,
            artifact_count=summary.artifact_count,
            artifact_bytes=artifact_bytes,
            manifest_sha256=manifest_sha256,
        )
    finally:
        os.close(root)
