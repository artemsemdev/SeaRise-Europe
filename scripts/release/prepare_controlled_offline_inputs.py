"""Verify and atomically extract one controlled offline-release input bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PROFILES = ("regional", "full-europe")
_MAX_MEMBERS = 1_000_000
_COPY_BUFFER_BYTES = 1024 * 1024


class InputBundleError(ValueError):
    """The reviewed bundle identity or archive layout is unsafe."""


@dataclass(frozen=True)
class PreparedInputs:
    """Identity and inventory of an atomically prepared input root."""

    archive_sha256: str
    file_count: int
    total_bytes: int
    destination: Path


def prepare_inputs(
    archive: Path,
    destination: Path,
    *,
    profile: str,
    expected_sha256: str,
) -> PreparedInputs:
    """Verify one plain tar and atomically expose its profile-specific input root."""
    if profile not in PROFILES:
        raise InputBundleError("profile must be regional or full-europe")
    if (
        len(expected_sha256) != 64
        or expected_sha256.lower() != expected_sha256
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise InputBundleError("expected SHA-256 must be 64 lowercase hexadecimal characters")
    if not archive.is_file() or archive.is_symlink():
        raise InputBundleError("input bundle must be one regular archive file")
    observed_sha256 = _sha256(archive)
    if observed_sha256 != expected_sha256:
        raise InputBundleError("input bundle SHA-256 does not match the reviewed identity")

    destination = destination.absolute()
    if os.path.lexists(destination):
        raise InputBundleError("input destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent = destination.parent.resolve(strict=True)
    temporary = Path(tempfile.mkdtemp(prefix=".offline-inputs-", dir=parent))
    prefix = PurePosixPath("build-inputs", "offline-release", profile)
    seen: set[str] = set()
    file_count = 0
    total_bytes = 0
    try:
        try:
            with tarfile.open(archive, mode="r:") as package:
                for member_count, member in enumerate(package, start=1):
                    if member_count > _MAX_MEMBERS:
                        raise InputBundleError("input bundle contains too many members")
                    relative = _validated_member_path(member, prefix=prefix)
                    canonical = relative.as_posix()
                    if canonical in seen:
                        raise InputBundleError("input bundle contains a duplicate member")
                    seen.add(canonical)
                    target = temporary.joinpath(*relative.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = package.extractfile(member)
                    if source is None:
                        raise InputBundleError("regular input member has no payload")
                    try:
                        with source, target.open("xb") as output:
                            shutil.copyfileobj(
                                source,
                                output,
                                length=_COPY_BUFFER_BYTES,
                            )
                            output.flush()
                            os.fsync(output.fileno())
                    except OSError as exc:
                        raise InputBundleError(
                            "input member could not be extracted safely"
                        ) from exc
                    file_count += 1
                    total_bytes += member.size
        except InputBundleError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise InputBundleError("input bundle must be an uncompressed POSIX tar") from exc

        required = {
            (prefix / "manifest.json").as_posix(),
            (prefix / "receipts" / "sources.json").as_posix(),
        }
        if not required.issubset(seen):
            raise InputBundleError("input bundle is missing manifest.json or receipts/sources.json")
        os.rename(temporary, destination)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return PreparedInputs(
        archive_sha256=observed_sha256,
        file_count=file_count,
        total_bytes=total_bytes,
        destination=destination,
    )


def _validated_member_path(
    member: tarfile.TarInfo, *, prefix: PurePosixPath
) -> PurePosixPath:
    name = member.name
    if not name or "\\" in name or "\x00" in name:
        raise InputBundleError("input bundle contains a non-canonical member path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InputBundleError("input bundle contains an unsafe member path")
    if path.as_posix() != name.rstrip("/"):
        raise InputBundleError("input bundle contains a non-canonical member path")
    if path != prefix and prefix not in path.parents:
        raise InputBundleError("input bundle contains a member outside the selected profile")
    if not (member.isdir() or member.isreg()):
        raise InputBundleError("input bundle may contain only directories and regular files")
    if member.isreg() and member.size < 0:
        raise InputBundleError("input bundle contains an invalid member size")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_COPY_BUFFER_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and safely prepare reviewed offline-release inputs."
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        result = prepare_inputs(
            args.archive,
            args.destination,
            profile=args.profile,
            expected_sha256=args.expected_sha256,
        )
    except InputBundleError as exc:
        parser.error(str(exc))
    print(
        "prepared reviewed inputs: "
        f"sha256={result.archive_sha256} files={result.file_count} "
        f"bytes={result.total_bytes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
