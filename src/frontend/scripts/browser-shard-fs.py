"""Descriptor-relative publication and loading for one browser shard set."""

from __future__ import annotations

import ctypes
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
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            fail("browser shard output root must be owner-controlled")
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


def open_file(root: int, item: dict[str, object]) -> tuple[int, os.stat_result]:
    name, size = str(item["name"]), int(item["size"])
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
        return descriptor, before
    except Exception:
        os.close(descriptor)
        raise


def read_opened(
    descriptor: int, item: dict[str, object], before: os.stat_result
) -> bytes:
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    size = int(item["size"])
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(READ_SIZE, size - offset), offset)
        if not chunk:
            fail("browser shard helper payload ended early")
        chunks.append(chunk)
        digest.update(chunk)
        offset += len(chunk)
    if digest.hexdigest() != item["sha256"]:
        fail("browser shard helper payload hash differs")
    if identity(os.fstat(descriptor)) != identity(before):
        fail("browser shard set changed while read")
    return b"".join(chunks)


def assert_opened(
    root: int, item: dict[str, object], descriptor: int, before: os.stat_result
) -> None:
    after = os.fstat(descriptor)
    linked = os.stat(str(item["name"]), dir_fd=root, follow_symlinks=False)
    if identity(before) != identity(after) or identity(after) != identity(linked):
        fail("browser shard set changed before its linearization point")


def rename_no_overwrite(root: int, source: str, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename, flag = libc.renameatx_np, 4
    elif sys.platform.startswith("linux"):
        rename, flag = libc.renameat2, 1
    else:
        fail("exclusive browser shard quarantine is unsupported")
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    if rename(root, os.fsencode(source), root, os.fsencode(target), flag) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), source)


def remove_owned(root: int, name: str, expected: os.stat_result) -> bool:
    """Atomically quarantine one pathname without ever restoring it publicly."""
    retained = f".search-shard-quarantine-{secrets.token_hex(16)}"
    try:
        rename_no_overwrite(root, name, retained)
    except FileNotFoundError:
        return True
    moved = os.stat(retained, dir_fd=root, follow_symlinks=False)
    return node(moved) == node(expected) and stat.S_ISREG(moved.st_mode)


def close_all(opened: list[tuple[dict[str, object], int, os.stat_result]]) -> None:
    primary = None
    for _, descriptor, _ in reversed(opened):
        try:
            os.close(descriptor)
        except OSError as error:
            primary = primary or error
    if primary is not None:
        raise primary


def coherent_read(
    root: int, output: Path, artifacts: list[dict[str, object]], *, receipt_first: bool
) -> list[bytes]:
    opened: list[tuple[dict[str, object], int, os.stat_result]] = []
    try:
        for item in artifacts:
            descriptor, before = open_file(root, item)
            opened.append((item, descriptor, before))
        receipt = (
            read_opened(opened[2][1], artifacts[2], opened[2][2])
            if receipt_first
            else None
        )
        shards = [
            read_opened(opened[index][1], artifacts[index], opened[index][2])
            for index in range(2)
        ]
        final_receipt = read_opened(opened[2][1], artifacts[2], opened[2][2])
        if receipt is not None and receipt != final_receipt:
            fail("browser shard receipt changed before consumer handoff")
        for item, descriptor, before in opened:
            assert_opened(root, item, descriptor, before)
        if not same_root(output, root):
            fail(
                "browser shard output directory changed before its linearization point"
            )
        for item, descriptor, before in opened:
            assert_opened(root, item, descriptor, before)
        return [*shards, final_receipt]
    finally:
        close_all(opened)


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
        for item in artifacts:
            final = str(item["name"])
            temporary = f".search-shard-{secrets.token_hex(16)}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o600, dir_fd=root)
            try:
                try:
                    metadata = os.fstat(descriptor)
                except BaseException:
                    metadata = os.fstat(descriptor)
                    staged.append((temporary, final, metadata))
                    raise
                staged.append((temporary, final, metadata))
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    fail(
                        "staged browser shard is not an owned single-link regular file"
                    )
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
                staged[-1] = (temporary, final, metadata)
            finally:
                os.close(descriptor)
        if stream.read(1):
            fail("browser shard helper payload has trailing bytes")
        for temporary, final, metadata in staged[:2]:
            rename_no_overwrite(root, temporary, final)
            promoted.append((final, metadata))
        os.fsync(root)
        temporary, final, metadata = staged[2]
        rename_no_overwrite(root, temporary, final)
        promoted.append((final, metadata))
        os.fsync(root)
        coherent_read(root, output, artifacts, receipt_first=False)
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


def read_set(root: int, output: Path, artifacts: list[dict[str, object]]) -> bytes:
    shards = coherent_read(root, output, artifacts, receipt_first=True)[:2]
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
