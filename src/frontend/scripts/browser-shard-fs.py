"""Descriptor-relative publication and loading for one browser shard set."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import BinaryIO, NoReturn

NAMES = (
    "europe-core.minisearch.json.br",
    "europe-coastal.minisearch.json.br",
    "settlement-browser-search-shards.receipt.json",
)
READ_SIZE = 1024 * 1024


class ShardFsError(ValueError):
    pass


def fail(message: str) -> NoReturn:
    raise ShardFsError(message)


def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail("browser shard helper header has duplicate keys")
        result[key] = value
    return result


def identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def node(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode


def open_root(path: Path) -> int:
    if os.name != "posix" or ".." in path.parts:
        fail("browser shard filesystem helper requires a canonical POSIX path")
    absolute = path.absolute()
    if sys.platform == "darwin" and absolute.parts[1:2] in (("var",), ("tmp",)):
        absolute = Path("/private").joinpath(*absolute.parts[1:])
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def header(stream: BinaryIO) -> tuple[str, list[dict[str, object]]]:
    raw = stream.readline(64 * 1024)
    if not raw.endswith(b"\n") or len(raw) >= 64 * 1024:
        fail("browser shard helper header is missing or oversized")
    try:
        value = json.loads(raw, object_pairs_hook=strict_object)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ShardFsError("browser shard helper header is invalid") from exc
    if not isinstance(value, dict) or set(value) != {"artifacts", "command"}:
        fail("browser shard helper header fields differ")
    artifacts = value["artifacts"]
    if (
        value["command"] not in {"publish", "read"}
        or not isinstance(artifacts, list)
        or [item.get("name") if isinstance(item, dict) else None for item in artifacts]
        != list(NAMES)
    ):
        fail("browser shard helper command or inventory differs")
    for item in artifacts:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "sha256", "size"}
            or not isinstance(item["size"], int)
            or isinstance(item["size"], bool)
            or item["size"] < 1
            or not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or set(item["sha256"]) - set("0123456789abcdef")
        ):
            fail("browser shard helper artifact identity differs")
    return str(value["command"]), artifacts


def read_exact(stream: BinaryIO, size: int, expected_sha256: str) -> bytes:
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = stream.read(min(READ_SIZE, remaining))
        if not chunk:
            fail("browser shard helper payload ended early")
        chunks.append(chunk)
        digest.update(chunk)
        remaining -= len(chunk)
    if digest.hexdigest() != expected_sha256:
        fail("browser shard helper payload hash differs")
    return b"".join(chunks)


def read_file(root: int, item: dict[str, object]) -> bytes:
    name, size, expected = str(item["name"]), int(item["size"]), str(item["sha256"])
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(name, flags, dir_fd=root)
    try:
        before = os.fstat(descriptor)
        linked = os.stat(name, dir_fd=root, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != size
            or identity(before) != identity(linked)
        ):
            fail("browser shard set contains an unsafe file")
        with os.fdopen(os.dup(descriptor), "rb", closefd=True) as stream:
            raw = read_exact(stream, size, expected)
        after = os.fstat(descriptor)
        linked = os.stat(name, dir_fd=root, follow_symlinks=False)
        if identity(before) != identity(after) or identity(after) != identity(linked):
            fail("browser shard set changed while read")
        return raw
    finally:
        os.close(descriptor)


def remove_owned(root: int, name: str, expected: os.stat_result) -> bool:
    try:
        current = os.stat(name, dir_fd=root, follow_symlinks=False)
        if node(current) != node(expected):
            return False
        os.unlink(name, dir_fd=root)
        return True
    except FileNotFoundError:
        return True


def publish(
    root: int, output: Path, artifacts: list[dict[str, object]], stream: BinaryIO
) -> None:
    staged: list[tuple[str, str, os.stat_result]] = []
    promoted: list[tuple[str, os.stat_result]] = []
    try:
        for item in artifacts:
            final = str(item["name"])
            try:
                os.stat(final, dir_fd=root, follow_symlinks=False)
                fail("browser shard output exists; overwrite is refused")
            except FileNotFoundError:
                pass
            temporary = f".search-shard-{secrets.token_hex(16)}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o600, dir_fd=root)
            try:
                digest = hashlib.sha256()
                remaining = int(item["size"])
                while remaining:
                    chunk = stream.read(min(READ_SIZE, remaining))
                    if not chunk:
                        fail("browser shard helper payload ended early")
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(descriptor, view)
                        if written < 1:
                            fail("browser shard helper write made no progress")
                        view = view[written:]
                    remaining -= len(chunk)
                if digest.hexdigest() != item["sha256"]:
                    fail("browser shard helper payload hash differs")
                os.fsync(descriptor)
                metadata = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            staged.append((temporary, final, metadata))
        if stream.read(1):
            fail("browser shard helper payload has trailing bytes")
        for temporary, final, metadata in staged[:2]:
            os.link(temporary, final, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
            promoted.append((final, metadata))
        for temporary, _, metadata in staged[:2]:
            if not remove_owned(root, temporary, metadata):
                fail("foreign staged browser shard was preserved")
        os.fsync(root)
        temporary, final, metadata = staged[2]
        os.link(temporary, final, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
        promoted.append((final, metadata))
        if not remove_owned(root, temporary, metadata):
            fail("foreign staged browser shard was preserved")
        os.fsync(root)
        for item in artifacts:
            read_file(root, item)
        if not same_root(output, root):
            fail("browser shard output directory changed during publication")
    except Exception:
        for final, metadata in reversed(promoted):
            remove_owned(root, final, metadata)
        for temporary, _, metadata in staged:
            remove_owned(root, temporary, metadata)
        os.fsync(root)
        raise


def same_root(path: Path, root: int) -> bool:
    reopened = open_root(path)
    try:
        return node(os.fstat(reopened)) == node(os.fstat(root))
    finally:
        os.close(reopened)


def read_set(
    root: int, output: Path, artifacts: list[dict[str, object]]
) -> bytes:
    receipt = read_file(root, artifacts[2])
    shards = [read_file(root, item) for item in artifacts[:2]]
    if read_file(root, artifacts[2]) != receipt or not same_root(output, root):
        fail("browser shard set changed before consumer handoff")
    return b"".join(shards)


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: browser-shard-fs.py OUTPUT_DIRECTORY")
    command, artifacts = header(sys.stdin.buffer)
    output = Path(sys.argv[1])
    root = open_root(output)
    try:
        if command == "publish":
            publish(root, output, artifacts, sys.stdin.buffer)
        else:
            sys.stdout.buffer.write(read_set(root, output, artifacts))
        return 0
    finally:
        os.close(root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ShardFsError) as error:
        print(f"browser shard filesystem error: {error}", file=sys.stderr)
        raise SystemExit(1)
