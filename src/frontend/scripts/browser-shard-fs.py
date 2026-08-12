"""Descriptor-relative publication and loading for browser search artifacts."""

from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import BinaryIO, NoReturn

NAMES = (
    "europe-core.codepoint-trie.json.br",
    "europe-coastal.codepoint-trie.json.br",
    "settlement-browser-search-shards.receipt.json",
)
READ_SIZE = 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
REPORT_PARTIAL_PREFIX = ".worker-performance-report-"
REPORT_QUARANTINE_PREFIX = ".worker-performance-quarantine-"


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


def inode(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


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


def safe_filename(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and Path(value).name == value
        and "/" not in value
        and "\\" not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


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
    command = value["command"]
    artifacts = value["artifacts"]
    if command not in {"publish", "read", "publish-report"} or not isinstance(
        artifacts, list
    ):
        fail("browser shard helper command or inventory differs")
    names = [item.get("name") if isinstance(item, dict) else None for item in artifacts]
    if command in {"publish", "read"} and names != list(NAMES):
        fail("browser shard helper command or inventory differs")
    if command == "publish-report" and (
        len(artifacts) != 1 or not safe_filename(names[0])
    ):
        fail("performance report helper inventory differs")
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
    if command == "publish-report" and int(artifacts[0]["size"]) > MAX_REPORT_BYTES:
        fail("performance report exceeds its byte limit")
    return str(command), artifacts


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
    for attempt in range(3):
        try:
            rename_no_overwrite(root, name, retained)
            break
        except FileNotFoundError:
            return True
        except OSError:
            if attempt == 2:
                raise
    moved = os.stat(retained, dir_fd=root, follow_symlinks=False)
    return node(moved) == node(expected) and stat.S_ISREG(moved.st_mode)


def unlink_owned_report(root: int, name: str, expected: os.stat_result) -> bool:
    """Quarantine before unlinking so a racing replacement is never deleted."""
    for _ in range(32):
        retained = f"{REPORT_QUARANTINE_PREFIX}{secrets.token_hex(16)}"
        try:
            rename_no_overwrite(root, name, retained)
        except FileExistsError:
            continue
        except FileNotFoundError:
            return False
        except OSError:
            return False
        break
    else:
        return False
    moved = os.stat(retained, dir_fd=root, follow_symlinks=False)
    if inode(moved) == inode(expected) and stat.S_ISREG(moved.st_mode):
        try:
            os.unlink(retained, dir_fd=root)
        except OSError:
            return False
        return True
    try:
        rename_no_overwrite(root, retained, name)
    except OSError:
        return False
    return False


def descriptor_has_exact_bytes(descriptor: int, content: bytes) -> bool:
    if os.fstat(descriptor).st_size != len(content):
        return False
    offset = 0
    while offset < len(content):
        expected = content[offset : offset + READ_SIZE]
        actual = os.pread(descriptor, len(expected), offset)
        if actual != expected:
            return False
        offset += len(actual)
    return os.pread(descriptor, 1, len(content)) == b""


def close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def create_report_partial(root: int) -> tuple[int, str]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for _ in range(32):
        name = f"{REPORT_PARTIAL_PREFIX}{secrets.token_hex(16)}.partial"
        try:
            return os.open(name, flags, 0o600, dir_fd=root), name
        except FileExistsError:
            continue
    fail("performance report partial allocation failed")


def publish_report(
    root: int, output: Path, item: dict[str, object], content: bytes
) -> None:
    """Durably publish one exact read-only report without overwriting a path."""
    final = str(item["name"])
    descriptor = -1
    partial: str | None = None
    owned: os.stat_result | None = None
    promoted = False
    directory_changed = False
    try:
        try:
            os.stat(final, dir_fd=root, follow_symlinks=False)
            fail("performance report exists; overwrite is refused")
        except FileNotFoundError:
            pass
        descriptor, partial = create_report_partial(root)
        directory_changed = True
        try:
            owned = os.fstat(descriptor)
        except OSError:
            owned = os.fstat(descriptor)
            raise
        if not stat.S_ISREG(owned.st_mode) or owned.st_nlink != 1:
            fail("performance report partial is not an owned single-link regular file")
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                fail("performance report write made no progress")
            remaining = remaining[written:]
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (
            inode(after) != inode(owned)
            or not stat.S_ISREG(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o400
            or after.st_nlink != 1
            or not descriptor_has_exact_bytes(descriptor, content)
        ):
            fail("performance report partial changed during publication")
        owned = after
        if not same_root(output, root):
            fail("performance report output directory changed before promotion")
        if inode(os.stat(partial, dir_fd=root, follow_symlinks=False)) != inode(owned):
            fail("performance report partial ownership changed before promotion")
        try:
            os.link(
                partial,
                final,
                src_dir_fd=root,
                dst_dir_fd=root,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise ShardFsError(
                "performance report exists; overwrite is refused"
            ) from error
        promoted = True
        directory_changed = True
        if inode(os.stat(final, dir_fd=root, follow_symlinks=False)) != inode(owned):
            fail("performance report promotion ownership changed")
        if not descriptor_has_exact_bytes(descriptor, content):
            fail("performance report promoted bytes changed")
        if not unlink_owned_report(root, partial, owned):
            fail("performance report partial cleanup failed after promotion")
        partial = None
        if os.fstat(descriptor).st_nlink != 1:
            fail("performance report final link count is invalid")
        os.fsync(root)
        directory_changed = False
        if (
            not same_root(output, root)
            or inode(os.stat(final, dir_fd=root, follow_symlinks=False)) != inode(owned)
            or not descriptor_has_exact_bytes(descriptor, content)
        ):
            fail("performance report changed before its linearization point")
    except BaseException as primary:
        cleanup_error: BaseException | None = None
        if promoted and owned is not None:
            try:
                removed = unlink_owned_report(root, final, owned)
                directory_changed = removed or directory_changed
                if not removed:
                    cleanup_error = ShardFsError(
                        "performance report rollback encountered a foreign inode"
                    )
            except OSError as error:
                cleanup_error = error
        if partial is not None and owned is not None:
            try:
                removed = unlink_owned_report(root, partial, owned)
                directory_changed = removed or directory_changed
                if not removed:
                    cleanup_error = cleanup_error or ShardFsError(
                        "performance report partial cleanup encountered a foreign inode"
                    )
            except OSError as error:
                cleanup_error = cleanup_error or error
        if directory_changed:
            try:
                os.fsync(root)
            except OSError:
                pass
        if cleanup_error is not None:
            primary.__context__ = cleanup_error
        raise
    finally:
        if descriptor >= 0:
            close_quietly(descriptor)


def close_all(
    opened: list[tuple[dict[str, object], int, os.stat_result]],
    primary: BaseException | None,
) -> None:
    close_error = None
    for _, descriptor, _ in reversed(opened):
        try:
            os.close(descriptor)
        except OSError as error:
            close_error = close_error or error
    if primary is None and close_error is not None:
        raise close_error


def coherent_read(
    root: int,
    output: Path,
    artifacts: list[dict[str, object]],
    *,
    receipt_first: bool,
    names: tuple[str, str, str] = NAMES,
) -> list[bytes]:
    inventory = [dict(item, name=name) for item, name in zip(artifacts, names)]
    opened: list[tuple[dict[str, object], int, os.stat_result]] = []
    primary = None
    try:
        for item in inventory:
            descriptor, before = open_file(root, item)
            opened.append((item, descriptor, before))
        receipt = (
            read_opened(opened[2][1], inventory[2], opened[2][2])
            if receipt_first
            else None
        )
        shards = [
            read_opened(opened[index][1], inventory[index], opened[index][2])
            for index in range(2)
        ]
        final_receipt = read_opened(opened[2][1], inventory[2], opened[2][2])
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
    except BaseException as error:
        primary = error
        raise
    finally:
        close_all(opened, primary)


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
        coherent_read(
            root,
            output,
            artifacts,
            receipt_first=False,
            names=(NAMES[0], NAMES[1], temporary),
        )
        rename_no_overwrite(root, temporary, final)
        promoted.append((final, metadata))
        os.fsync(root)
    except BaseException as primary:
        cleanup_error = None
        for final, metadata in reversed(promoted):
            try:
                if not remove_owned(root, final, metadata):
                    cleanup_error = cleanup_error or ShardFsError(
                        "browser shard rollback encountered a foreign inode"
                    )
            except OSError as error:
                cleanup_error = cleanup_error or error
        for temporary, _, metadata in staged:
            try:
                if not remove_owned(root, temporary, metadata):
                    cleanup_error = cleanup_error or ShardFsError(
                        "browser shard staging cleanup encountered a foreign inode"
                    )
            except OSError as error:
                cleanup_error = cleanup_error or error
        try:
            os.fsync(root)
        except OSError as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            primary.__context__ = cleanup_error
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
    completed = False
    try:
        lock = (
            fcntl.LOCK_EX if command in {"publish", "publish-report"} else fcntl.LOCK_SH
        )
        fcntl.flock(root, lock | fcntl.LOCK_NB)
        if command == "publish":
            publish(root, output, artifacts, sys.stdin.buffer)
        elif command == "publish-report":
            content = read_exact(
                sys.stdin.buffer, int(artifacts[0]["size"]), str(artifacts[0]["sha256"])
            )
            if sys.stdin.buffer.read(1):
                fail("performance report helper payload has trailing bytes")
            publish_report(root, output, artifacts[0], content)
        else:
            sys.stdout.buffer.write(read_set(root, output, artifacts))
        completed = True
        return 0
    finally:
        try:
            os.close(root)
        except OSError:
            if not completed:
                raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ShardFsError) as error:
        print(f"browser shard filesystem error: {error}", file=sys.stderr)
        raise SystemExit(1)
