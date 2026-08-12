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


def assert_hidden_residue(directory: Path, maximum: int) -> None:
    entries = list(directory.iterdir())
    assert len(entries) <= maximum
    assert all(path.name.startswith(".search-shard-") for path in entries)


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
    assert {path.name for path in output.iterdir()} == complete
    assert all((output / name).stat().st_nlink == 1 for name in browser_fs.NAMES)


def displaced_publication() -> None:
    parent = Path(tempfile.mkdtemp(prefix="browser-shard-displaced-"))
    output, moved = parent / "output", parent / "moved"
    output.mkdir()
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original = browser_fs.rename_no_overwrite
    links = 0

    def displaced(descriptor: int, source: str, target: str) -> None:
        nonlocal links
        original(descriptor, source, target)
        links += 1
        if links == 2:
            output.rename(moved)
            output.mkdir()
            (output / "foreign").write_text("preserve", encoding="utf-8")

    browser_fs.rename_no_overwrite = displaced
    try:
        expect_failure(
            lambda: browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
        )
    finally:
        browser_fs.rename_no_overwrite = original
        os.close(root)
    assert sorted(path.name for path in output.iterdir()) == ["foreign"]
    assert_hidden_residue(moved, 12)


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
        expect_failure(
            lambda: browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
        )
    finally:
        browser_fs.os.open = original
        os.close(root)
    assert replaced and sorted(path.name for path in output.iterdir()) == ["foreign"]
    assert_hidden_residue(moved, 12)


def receipt_recheck() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-receipt-"))
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
    original = browser_fs.read_opened
    receipt_reads = 0

    def changed(
        descriptor: int, item: dict[str, object], before: os.stat_result
    ) -> bytes:
        nonlocal receipt_reads
        raw = original(descriptor, item, before)
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

    browser_fs.read_opened = changed
    try:
        expect_failure(lambda: browser_fs.read_set(root, output, artifacts))
    finally:
        browser_fs.read_opened = original
        os.close(root)
    assert receipt_reads == 1


def displaced_read() -> None:
    parent = Path(tempfile.mkdtemp(prefix="browser-shard-read-displaced-"))
    output, moved = parent / "output", parent / "moved"
    output.mkdir()
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
    original = browser_fs.read_opened
    reads = 0

    def displaced(
        descriptor: int, item: dict[str, object], before: os.stat_result
    ) -> bytes:
        nonlocal reads
        raw = original(descriptor, item, before)
        reads += 1
        if reads == 2:
            output.rename(moved)
            output.mkdir()
            (output / "foreign").write_text("preserve", encoding="utf-8")
        return raw

    browser_fs.read_opened = displaced
    try:
        expect_failure(lambda: browser_fs.read_set(root, output, artifacts))
    finally:
        browser_fs.read_opened = original
        os.close(root)
    assert sorted(path.name for path in output.iterdir()) == ["foreign"]
    assert {path.name for path in moved.iterdir()} == set(browser_fs.NAMES)


def early_failure_cleanup() -> None:
    for mode in ("hash", "write", "fsync", "fstat", "close"):
        output = Path(tempfile.mkdtemp(prefix=f"browser-shard-{mode}-"))
        artifacts, payload = inventory()
        root = browser_fs.open_root(output)
        original_write = browser_fs.os.write
        original_fsync = browser_fs.os.fsync
        original_fstat = browser_fs.os.fstat
        original_close = browser_fs.os.close
        if mode == "hash":
            artifacts[0]["sha256"] = "0" * 64
        elif mode == "write":
            browser_fs.os.write = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("write")
            )
        elif mode == "fsync":
            browser_fs.os.fsync = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("fsync")
            )
        elif mode == "fstat":
            failed = False

            def fail_once(
                descriptor: int, original: object = original_fstat
            ) -> os.stat_result:
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("fstat")
                return original(descriptor)  # type: ignore[operator]

            browser_fs.os.fstat = fail_once
        elif mode == "close":
            failed = False

            def close_once(descriptor: int, original: object = original_close) -> None:
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("close")
                original(descriptor)  # type: ignore[operator]

            browser_fs.os.close = close_once
        try:
            expect_failure(
                lambda root=root, output=output, artifacts=artifacts, payload=payload: (
                    browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
                )
            )
        finally:
            browser_fs.os.write = original_write
            browser_fs.os.fsync = original_fsync
            browser_fs.os.fstat = original_fstat
            browser_fs.os.close = original_close
            original_close(root)
        assert_hidden_residue(output, 2)


def foreign_cleanup_race() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-foreign-cleanup-"))
    root = browser_fs.open_root(output)
    owned = os.open("owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
    os.write(owned, b"owned")
    expected = os.fstat(owned)
    os.close(owned)
    os.unlink("owned", dir_fd=root)
    foreign = os.open("owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
    os.write(foreign, b"foreign")
    os.close(foreign)
    assert not browser_fs.remove_owned(root, "owned", expected)
    assert (output / "owned").read_bytes() == b"foreign"
    os.close(root)


def foreign_restore_collision() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-foreign-collision-"))
    root = browser_fs.open_root(output)
    original_owned = os.open(
        "owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root
    )
    expected = os.fstat(original_owned)
    os.close(original_owned)
    os.unlink("owned", dir_fd=root)
    foreign = os.open("owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
    os.write(foreign, b"foreign")
    os.close(foreign)
    original = browser_fs.exchange
    exchanges = 0

    def collide(descriptor: int, left: str, right: str) -> None:
        nonlocal exchanges
        original(descriptor, left, right)
        exchanges += 1
        if exchanges == 1:
            os.unlink(left, dir_fd=descriptor)
            blocker = os.open(
                left, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=descriptor
            )
            os.write(blocker, b"blocker")
            os.close(blocker)

    browser_fs.exchange = collide
    try:
        assert not browser_fs.remove_owned(root, "owned", expected)
    finally:
        browser_fs.exchange = original
        os.close(root)
    assert (output / "owned").read_bytes() == b"foreign"
    assert any(
        path.read_bytes() == b"blocker"
        for path in output.iterdir()
        if path.name != "owned"
    )


def replacement_after_placeholder_stat() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-placeholder-race-"))
    root = browser_fs.open_root(output)
    owned = os.open("owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
    expected = os.fstat(owned)
    os.close(owned)
    original = browser_fs.os.stat
    swapped = False
    owned_stats = 0

    def swap_after_stat(
        path: object, *args: object, **kwargs: object
    ) -> os.stat_result:
        nonlocal swapped
        nonlocal owned_stats
        result = original(path, *args, **kwargs)
        if path == "owned":
            owned_stats += 1
        if path == "owned" and owned_stats == 2 and not swapped:
            swapped = True
            os.unlink("owned", dir_fd=root)
            foreign = os.open(
                "owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root
            )
            os.write(foreign, b"foreign")
            os.close(foreign)
        return result

    browser_fs.os.stat = swap_after_stat
    try:
        assert not browser_fs.remove_owned(root, "owned", expected)
    finally:
        browser_fs.os.stat = original
        os.close(root)
    assert swapped and (output / "owned").read_bytes() == b"foreign"


def replacement_restore_collision() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-restore-collision-"))
    root = browser_fs.open_root(output)
    owned = os.open("owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
    expected = os.fstat(owned)
    os.close(owned)
    original_stat = browser_fs.os.stat
    original_rename = browser_fs.rename_no_overwrite
    owned_stats = 0
    isolated_move = False

    def swap_after_stat(
        path: object, *args: object, **kwargs: object
    ) -> os.stat_result:
        nonlocal owned_stats
        result = original_stat(path, *args, **kwargs)
        if path == "owned":
            owned_stats += 1
            if owned_stats == 2:
                os.unlink("owned", dir_fd=root)
                foreign = os.open(
                    "owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root
                )
                os.write(foreign, b"foreign")
                os.close(foreign)
        return result

    def collide(descriptor: int, source: str, target: str) -> None:
        nonlocal isolated_move
        original_rename(descriptor, source, target)
        if source == "owned" and target.startswith(".search-shard-placeholder-"):
            isolated_move = True
            blocker = os.open(
                "owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root
            )
            os.write(blocker, b"blocker")
            os.close(blocker)

    browser_fs.os.stat = swap_after_stat
    browser_fs.rename_no_overwrite = collide
    try:
        assert not browser_fs.remove_owned(root, "owned", expected)
    finally:
        browser_fs.os.stat = original_stat
        browser_fs.rename_no_overwrite = original_rename
        os.close(root)
    assert isolated_move and (output / "owned").read_bytes() == b"blocker"
    assert any(
        path.read_bytes() == b"foreign"
        for path in output.iterdir()
        if path.name != "owned"
    )


def final_identity_pass() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-final-pass-"))
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original = browser_fs.read_opened
    changed = False

    def mutate(
        descriptor: int, item: dict[str, object], before: os.stat_result
    ) -> bytes:
        nonlocal changed
        raw = original(descriptor, item, before)
        if not changed and item["name"] == browser_fs.NAMES[0]:
            changed = True
            writer = os.open(str(item["name"]), os.O_WRONLY, dir_fd=root)
            os.write(writer, b"FAIL")
            os.fsync(writer)
            os.close(writer)
        return raw

    browser_fs.read_opened = mutate
    try:
        expect_failure(
            lambda: browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
        )
    finally:
        browser_fs.read_opened = original
        os.close(root)
    assert changed
    assert_hidden_residue(output, 12)


def final_link_replacement() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-final-link-"))
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original = browser_fs.rename_no_overwrite
    replaced = False

    def replace_after_link(descriptor: int, source: str, target: str) -> None:
        nonlocal replaced
        original(descriptor, source, target)
        if not replaced and target == browser_fs.NAMES[0]:
            replaced = True
            os.unlink(browser_fs.NAMES[0], dir_fd=root)
            foreign = os.open(
                browser_fs.NAMES[0],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=root,
            )
            os.write(foreign, b"foreign")
            os.close(foreign)

    browser_fs.rename_no_overwrite = replace_after_link
    try:
        expect_failure(
            lambda: browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
        )
    finally:
        browser_fs.rename_no_overwrite = original
        os.close(root)
    assert replaced and (output / browser_fs.NAMES[0]).read_bytes() == b"foreign"
    assert all(
        path.name == browser_fs.NAMES[0] or path.name.startswith(".search-shard-")
        for path in output.iterdir()
    )


publication_phases()
displaced_publication()
replacement_before_staging()
receipt_recheck()
displaced_read()
early_failure_cleanup()
foreign_cleanup_race()
foreign_restore_collision()
replacement_after_placeholder_stat()
replacement_restore_collision()
final_identity_pass()
final_link_replacement()
print("browser shard filesystem adversarial checks passed")
