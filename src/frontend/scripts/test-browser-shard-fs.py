"""Adversarial checks for descriptor-relative browser shard filesystem operations."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import stat
import tempfile
from pathlib import Path

HELPER = Path(__file__).with_name("browser-shard-fs.py")
SPEC = importlib.util.spec_from_file_location("browser_shard_fs", HELPER)
assert SPEC is not None and SPEC.loader is not None
browser_fs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(browser_fs)


def inventory() -> tuple[list[dict[str, object]], bytes]:
    values = (b"core", b"coastal", b'{"complete":true}')
    artifacts = [
        {"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        for name, raw in zip(browser_fs.NAMES, values)
    ]
    return artifacts, b"".join(values)


def expect_failure(action: object) -> None:
    try:
        action()  # type: ignore[operator]
    except (OSError, browser_fs.ShardFsError):
        return
    raise AssertionError("adversarial browser shard operation did not fail")


def publication_phases() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-fsync-"))
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original = browser_fs.os.fsync
    phases: list[set[str]] = []

    def observed(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            phases.append(set(os.listdir(descriptor)))
        original(descriptor)

    browser_fs.os.fsync = observed
    try:
        browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
    finally:
        browser_fs.os.fsync = original
        os.close(root)
    shards = set(browser_fs.NAMES[:2])
    complete = set(browser_fs.NAMES)
    assert any(shards <= phase and browser_fs.NAMES[2] not in phase for phase in phases)
    assert any(complete <= phase for phase in phases)


def displaced_publication() -> None:
    parent = Path(tempfile.mkdtemp(prefix="browser-shard-displaced-"))
    output, moved = parent / "output", parent / "moved"
    output.mkdir()
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original = browser_fs.os.link
    links = 0

    def displaced(*args: object, **kwargs: object) -> None:
        nonlocal links
        original(*args, **kwargs)
        links += 1
        if links == 2:
            output.rename(moved)
            output.mkdir()
            (output / "foreign").write_text("preserve", encoding="utf-8")

    browser_fs.os.link = displaced
    try:
        expect_failure(lambda: browser_fs.publish(root, output, artifacts, io.BytesIO(payload)))
    finally:
        browser_fs.os.link = original
        os.close(root)
    assert sorted(path.name for path in output.iterdir()) == ["foreign"]
    assert list(moved.iterdir()) == []


def replacement_before_staging() -> None:
    parent = Path(tempfile.mkdtemp(prefix="browser-shard-replaced-"))
    output, moved = parent / "output", parent / "moved"
    output.mkdir()
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original = browser_fs.os.open
    replaced = False

    def displaced(name: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal replaced
        if not replaced and kwargs.get("dir_fd") == root and flags & os.O_CREAT:
            replaced = True
            output.rename(moved)
            output.mkdir()
            (output / "foreign").write_text("preserve", encoding="utf-8")
        return original(name, flags, *args, **kwargs)

    browser_fs.os.open = displaced
    try:
        expect_failure(lambda: browser_fs.publish(root, output, artifacts, io.BytesIO(payload)))
    finally:
        browser_fs.os.open = original
        os.close(root)
    assert replaced and sorted(path.name for path in output.iterdir()) == ["foreign"]
    assert list(moved.iterdir()) == []


def receipt_recheck() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-receipt-"))
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
    original = browser_fs.read_file
    receipt_reads = 0

    def changed(descriptor: int, item: dict[str, object]) -> bytes:
        nonlocal receipt_reads
        raw = original(descriptor, item)
        if item["name"] == browser_fs.NAMES[2]:
            receipt_reads += 1
            if receipt_reads == 1:
                replacement = os.open(item["name"], os.O_WRONLY, dir_fd=descriptor)
                try:
                    os.write(replacement, b"X" * int(item["size"]))
                    os.fsync(replacement)
                finally:
                    os.close(replacement)
        return raw

    browser_fs.read_file = changed
    try:
        expect_failure(lambda: browser_fs.read_set(root, output, artifacts))
    finally:
        browser_fs.read_file = original
        os.close(root)
    assert receipt_reads == 1


def displaced_read() -> None:
    parent = Path(tempfile.mkdtemp(prefix="browser-shard-read-displaced-"))
    output, moved = parent / "output", parent / "moved"
    output.mkdir()
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
    original = browser_fs.read_file
    reads = 0

    def displaced(descriptor: int, item: dict[str, object]) -> bytes:
        nonlocal reads
        raw = original(descriptor, item)
        reads += 1
        if reads == 2:
            output.rename(moved)
            output.mkdir()
            (output / "foreign").write_text("preserve", encoding="utf-8")
        return raw

    browser_fs.read_file = displaced
    try:
        expect_failure(lambda: browser_fs.read_set(root, output, artifacts))
    finally:
        browser_fs.read_file = original
        os.close(root)
    assert sorted(path.name for path in output.iterdir()) == ["foreign"]
    assert {path.name for path in moved.iterdir()} == set(browser_fs.NAMES)


publication_phases()
displaced_publication()
replacement_before_staging()
receipt_recheck()
displaced_read()
print("browser shard filesystem adversarial checks passed")
