#!/usr/bin/env python3
"""Verify and safely extract one Phase 1 production-input archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_MEMBERS = 100
MAX_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024


class ProductionInputError(ValueError):
    """The reviewed production-input archive is unsafe or unbound."""


@dataclass(frozen=True)
class PreparedProductionInputs:
    archive_sha256: str
    file_count: int
    total_bytes: int
    destination: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(member: tarfile.TarInfo) -> PurePosixPath:
    name = member.name
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in {"", ".", ".."} for part in path.parts)
        or not member.isreg()
        or member.size <= 0
        or member.size > MAX_MEMBER_BYTES
    ):
        raise ProductionInputError("production input archive has an unsafe member")
    return path


def _authority(raw: bytes) -> dict[str, dict[str, object]]:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionInputError("input authority is not valid JSON") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"schemaVersion", "bundleType", "candidateInputCount", "files"}
        or document["schemaVersion"] != 1
        or document["bundleType"] != "phase-1-production-inputs"
        or document["candidateInputCount"] != 51
        or not isinstance(document["files"], list)
    ):
        raise ProductionInputError("input authority contract differs")
    by_path: dict[str, dict[str, object]] = {}
    for item in document["files"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "byteSize", "sha256", "mode"}
            or not isinstance(item["path"], str)
            or item["path"] in by_path
            or not isinstance(item["byteSize"], int)
            or item["byteSize"] <= 0
            or item["mode"] not in {"0444", "0555"}
            or not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or any(value not in "0123456789abcdef" for value in item["sha256"])
        ):
            raise ProductionInputError("input authority file inventory differs")
        by_path[item["path"]] = item
    if len([path for path in by_path if path.startswith("candidate-inputs/")]) != 51:
        raise ProductionInputError("input authority candidate inventory differs")
    return by_path


def prepare_inputs(
    archive: Path, destination: Path, *, expected_sha256: str
) -> PreparedProductionInputs:
    if (
        len(expected_sha256) != 64
        or expected_sha256.lower() != expected_sha256
        or any(value not in "0123456789abcdef" for value in expected_sha256)
        or not archive.is_file()
        or archive.is_symlink()
    ):
        raise ProductionInputError("archive or expected SHA-256 is invalid")
    observed_archive_sha = _sha256(archive)
    if observed_archive_sha != expected_sha256:
        raise ProductionInputError("production input archive SHA-256 differs")
    if os.path.lexists(destination):
        raise ProductionInputError("production input destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent = destination.parent.resolve(strict=True)
    temporary = Path(tempfile.mkdtemp(prefix=".phase-1-inputs-", dir=parent))
    extracted: dict[str, tuple[int, str]] = {}
    total = 0
    try:
        try:
            with tarfile.open(archive, mode="r:") as package:
                members = package.getmembers()
                if not members or len(members) > MAX_MEMBERS:
                    raise ProductionInputError("production input member count is invalid")
                if [item.name for item in members] != sorted(item.name for item in members):
                    raise ProductionInputError("production input members are not sorted")
                if len({item.name for item in members}) != len(members):
                    raise ProductionInputError("production input members are duplicated")
                authority_member = next(
                    (item for item in members if item.name == "input-authority.json"), None
                )
                if authority_member is None:
                    raise ProductionInputError("production input authority is missing")
                authority_stream = package.extractfile(authority_member)
                if authority_stream is None:
                    raise ProductionInputError("production input authority has no payload")
                expected = _authority(authority_stream.read())
                for member in members:
                    logical = _path(member)
                    if logical.as_posix() == "input-authority.json":
                        continue
                    record = expected.get(logical.as_posix())
                    stream = package.extractfile(member)
                    if record is None or stream is None:
                        raise ProductionInputError("archive and input authority inventories differ")
                    raw = stream.read()
                    if len(raw) != record["byteSize"] or _digest(raw) != record["sha256"]:
                        raise ProductionInputError("production input bytes differ from authority")
                    total += len(raw)
                    if total > MAX_TOTAL_BYTES:
                        raise ProductionInputError("production inputs exceed the total size limit")
                    target = temporary.joinpath(*logical.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as output:
                        output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                    target.chmod(0o555 if record["mode"] == "0555" else 0o444)
                    extracted[logical.as_posix()] = (len(raw), _digest(raw))
        except ProductionInputError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise ProductionInputError("production input archive cannot be read") from exc
        if set(extracted) != set(expected):
            raise ProductionInputError("production input authority has unretained files")
        os.rename(temporary, destination)
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return PreparedProductionInputs(
        observed_archive_sha, len(extracted), total, destination
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    result = prepare_inputs(
        args.archive, args.destination, expected_sha256=args.expected_sha256
    )
    print(
        json.dumps(
            {
                "archiveSha256": result.archive_sha256,
                "fileCount": result.file_count,
                "totalBytes": result.total_bytes,
                "destination": str(result.destination),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
