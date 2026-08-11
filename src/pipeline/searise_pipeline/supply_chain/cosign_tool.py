"""Validate the reviewed Cosign signer binary and its official checksum evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn

from .contracts import SupplyChainContractError, _validate_schema

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE_ROOT = "https://github.com/sigstore/cosign/releases"
_VERSION = "3.0.6"
_EXECUTABLE_NAME = "cosign-linux-amd64"
_CHECKSUM_NAME = "cosign_checksums.txt"
_EXECUTABLE_URL = f"{_RELEASE_ROOT}/download/v{_VERSION}/{_EXECUTABLE_NAME}"
_CHECKSUM_URL = f"{_RELEASE_ROOT}/download/v{_VERSION}/{_CHECKSUM_NAME}"


@dataclass(frozen=True)
class CosignToolSummary:
    version: str
    platform: str
    tool_lock_sha256: str
    executable_sha256: str
    executable_byte_size: int


def _fail(message: str) -> NoReturn:
    raise SupplyChainContractError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(document: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise SupplyChainContractError("Cosign tool lock is not canonical JSON") from exc


def _strict_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > 16_384:
        _fail("Cosign tool lock exceeds its bounded contract size")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document = dict(pairs)
        if len(document) != len(pairs):
            raise ValueError("duplicate object key")
        return document

    def reject_constant(value: str) -> NoReturn:
        raise ValueError(f"non-standard JSON constant: {value}")

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
        json.dumps(document, ensure_ascii=False).encode("utf-8")
    except (RecursionError, UnicodeDecodeError, UnicodeEncodeError, ValueError) as exc:
        raise SupplyChainContractError("Cosign tool lock must be strict UTF-8 JSON") from exc
    if not isinstance(document, dict):
        _fail("Cosign tool lock JSON root must be an object")
    return document


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read(
    path: Path,
    label: str,
    *,
    expected_byte_size: int | None = None,
    maximum_byte_size: int | None = None,
) -> bytes:
    if ".." in path.parts:
        _fail(f"{label} path must not contain parent traversal")
    absolute = path.absolute()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(absolute.anchor, directory_flags)
    try:
        for part in absolute.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(absolute.name, file_flags, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            linked = os.stat(absolute.name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(linked):
                _fail(f"{label} must be one regular file without symlinks")
            if expected_byte_size is not None and before.st_size != expected_byte_size:
                _fail(f"{label} byte size differs from the reviewed release asset")
            if maximum_byte_size is not None and before.st_size > maximum_byte_size:
                _fail(f"{label} exceeds its bounded contract size")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    _fail(f"{label} changed while it was read")
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            linked = os.stat(absolute.name, dir_fd=directory, follow_symlinks=False)
            raw = b"".join(chunks)
            if (
                _identity(before) != _identity(after)
                or _identity(after) != _identity(linked)
                or len(raw) != after.st_size
            ):
                _fail(f"{label} changed while it was read")
            return raw
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"{label} must be one regular file without symlinks"
        ) from exc
    finally:
        os.close(directory)


def parse_cosign_tool_lock(raw: bytes) -> Mapping[str, Any]:
    """Parse canonical lock bytes and enforce the reviewed upstream identity."""
    lock = _strict_json(raw)
    _validate_schema(lock, "cosign-tool-lock.schema.json")
    if raw != _canonical(lock):
        _fail("Cosign tool lock must be canonical JSON")
    executable, checksums = lock["executable"], lock["checksumEvidence"]
    expected = {
        "contractId": "phase-1-cosign-linux-amd64-v1",
        "tool": "cosign",
        "version": _VERSION,
        "platform": "linux-amd64",
        "releaseUrl": f"{_RELEASE_ROOT}/tag/v{_VERSION}",
    }
    if any(lock[field] != value for field, value in expected.items()):
        _fail("Cosign tool lock identity differs from the reviewed Linux AMD64 release")
    if (executable["name"], executable["url"]) != (_EXECUTABLE_NAME, _EXECUTABLE_URL):
        _fail("Cosign executable asset identity differs from the reviewed release")
    if (checksums["name"], checksums["url"]) != (_CHECKSUM_NAME, _CHECKSUM_URL):
        _fail("Cosign checksum asset identity differs from the reviewed release")
    expected_entry = f"{executable['sha256']}  {_EXECUTABLE_NAME}"
    if checksums["entry"] != expected_entry:
        _fail("Cosign checksum evidence entry does not bind the executable digest")
    return lock


def validate_cosign_tool_lock(
    lock_path: Path,
    *,
    trusted_lock_sha256: str,
    executable_path: Path | None = None,
    checksum_path: Path | None = None,
) -> CosignToolSummary:
    """Validate a trusted lock and, when supplied, both exact upstream asset bytes."""
    if _SHA256.fullmatch(trusted_lock_sha256) is None:
        _fail("trusted Cosign tool-lock SHA-256 must be one lowercase digest")
    if (executable_path is None) != (checksum_path is None):
        _fail("Cosign executable and checksum evidence must be validated together")
    lock_raw = _read(lock_path, "Cosign tool lock", maximum_byte_size=16_384)
    if _sha256(lock_raw) != trusted_lock_sha256:
        _fail("Cosign tool lock does not match the independently reviewed SHA-256")
    lock = parse_cosign_tool_lock(lock_raw)
    executable = lock["executable"]
    if executable_path is not None and checksum_path is not None:
        checksums = lock["checksumEvidence"]
        checksum_raw = _read(
            checksum_path,
            "Cosign checksum evidence",
            expected_byte_size=int(checksums["byteSize"]),
        )
        if (_sha256(checksum_raw), len(checksum_raw)) != (
            checksums["sha256"],
            checksums["byteSize"],
        ):
            _fail("Cosign checksum evidence bytes differ from the reviewed release asset")
        try:
            lines = checksum_raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise SupplyChainContractError("Cosign checksum evidence must be UTF-8") from exc
        if lines.count(checksums["entry"]) != 1:
            _fail("Cosign checksum evidence must contain its exact executable entry once")
        executable_raw = _read(
            executable_path,
            "Cosign executable",
            expected_byte_size=int(executable["byteSize"]),
        )
        if (_sha256(executable_raw), len(executable_raw)) != (
            executable["sha256"],
            executable["byteSize"],
        ):
            _fail("Cosign executable bytes differ from the reviewed official checksum")
    return CosignToolSummary(
        version=str(lock["version"]),
        platform=str(lock["platform"]),
        tool_lock_sha256=_sha256(lock_raw),
        executable_sha256=str(executable["sha256"]),
        executable_byte_size=int(executable["byteSize"]),
    )
