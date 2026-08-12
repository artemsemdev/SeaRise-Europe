"""Adversarial checks for descriptor-relative browser shard filesystem operations."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
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


def report_inventory() -> tuple[dict[str, object], bytes]:
    payload = b'{"report":"exact"}\n'
    return {
        "name": "worker-performance.json",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }, payload


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
        assert_hidden_residue(output, 1)


def foreign_cleanup_race() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-foreign-cleanup-"))
    root = browser_fs.open_root(output)
    owned = os.open("owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root)
    os.write(owned, b"owned")
    expected = os.fstat(owned)
    os.close(owned)
    original_rename = browser_fs.rename_no_overwrite
    replaced = False

    def replace_before_quarantine(descriptor: int, source: str, target: str) -> None:
        nonlocal replaced
        if source == "owned" and not replaced:
            replaced = True
            os.rename("owned", "attacker-held-owned", src_dir_fd=root, dst_dir_fd=root)
            foreign = os.open(
                "owned", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=root
            )
            os.write(foreign, b"foreign")
            os.close(foreign)
        original_rename(descriptor, source, target)

    browser_fs.rename_no_overwrite = replace_before_quarantine
    try:
        assert not browser_fs.remove_owned(root, "owned", expected)
    finally:
        browser_fs.rename_no_overwrite = original_rename
        os.close(root)
    assert replaced and not (output / "owned").exists()
    assert (output / "attacker-held-owned").read_bytes() == b"owned"
    assert any(path.read_bytes() == b"foreign" for path in output.iterdir())


def existing_outputs_do_not_stage_on_retry() -> None:
    artifacts, payload = inventory()
    for existing in browser_fs.NAMES:
        output = Path(tempfile.mkdtemp(prefix="browser-shard-existing-"))
        (output / existing).write_bytes(b"foreign")
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        for _ in range(3):
            root = browser_fs.open_root(output)
            try:
                expect_failure(
                    lambda root=root, output=output: browser_fs.publish(
                        root, output, artifacts, io.BytesIO(payload)
                    )
                )
            finally:
                os.close(root)
            assert {path.name: path.read_bytes() for path in output.iterdir()} == before


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
    assert_hidden_residue(output, 3)


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
    assert replaced and not any((output / name).exists() for name in browser_fs.NAMES)
    assert all(path.name.startswith(".search-shard-") for path in output.iterdir())
    assert any(path.read_bytes() == b"foreign" for path in output.iterdir())


def rollback_retries_and_preserves_primary() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-rollback-retry-"))
    artifacts, payload = inventory()
    root = browser_fs.open_root(output)
    original_read = browser_fs.coherent_read
    original_rename = browser_fs.rename_no_overwrite
    failed = False

    def primary_failure(*_args: object, **_kwargs: object) -> list[bytes]:
        raise browser_fs.ShardFsError("primary validation failure")

    def fail_first_quarantine(descriptor: int, source: str, target: str) -> None:
        nonlocal failed
        if target.startswith(".search-shard-quarantine-") and not failed:
            failed = True
            raise PermissionError("transient quarantine failure")
        original_rename(descriptor, source, target)

    browser_fs.coherent_read = primary_failure
    browser_fs.rename_no_overwrite = fail_first_quarantine
    try:
        try:
            browser_fs.publish(root, output, artifacts, io.BytesIO(payload))
        except browser_fs.ShardFsError as error:
            assert str(error) == "primary validation failure"
        else:
            raise AssertionError("primary publication failure was lost")
    finally:
        browser_fs.coherent_read = original_read
        browser_fs.rename_no_overwrite = original_rename
        os.close(root)
    assert failed and not any((output / name).exists() for name in browser_fs.NAMES)
    assert_hidden_residue(output, 3)


def final_root_close_is_cleanup_only() -> None:
    output = Path(tempfile.mkdtemp(prefix="browser-shard-final-close-"))
    artifacts, payload = inventory()
    raw = (
        json.dumps(
            {"artifacts": artifacts, "command": "publish"},
            separators=(",", ":"),
        ).encode()
        + b"\n"
        + payload
    )
    root = browser_fs.open_root(output)
    original_open_root = browser_fs.open_root
    original_close = browser_fs.os.close
    original_argv, original_stdin = sys.argv, sys.stdin
    calls = 0

    def open_for_main(path: Path) -> int:
        nonlocal calls
        calls += 1
        return root if calls == 1 else original_open_root(path)

    def fail_final_close(descriptor: int) -> None:
        if descriptor == root:
            raise OSError("injected final root close")
        original_close(descriptor)

    browser_fs.open_root = open_for_main
    browser_fs.os.close = fail_final_close
    sys.argv = [str(HELPER), str(output)]
    sys.stdin = type("Input", (), {"buffer": io.BytesIO(raw)})()
    try:
        assert browser_fs.main() == 0
    finally:
        browser_fs.open_root = original_open_root
        browser_fs.os.close = original_close
        sys.argv, sys.stdin = original_argv, original_stdin
        original_close(root)
    assert {path.name for path in output.iterdir()} == set(browser_fs.NAMES)


def report_publication_is_exact_and_read_only() -> None:
    output = Path(tempfile.mkdtemp(prefix="worker-report-exact-"))
    item, payload = report_inventory()
    root = browser_fs.open_root(output)
    try:
        browser_fs.publish_report(root, output, item, payload)
    finally:
        os.close(root)
    report = output / str(item["name"])
    assert report.read_bytes() == payload
    assert stat.S_IMODE(report.stat().st_mode) == 0o400
    assert report.stat().st_nlink == 1
    assert [path.name for path in output.iterdir()] == [item["name"]]


def report_short_write_and_no_overwrite() -> None:
    output = Path(tempfile.mkdtemp(prefix="worker-report-short-write-"))
    item, payload = report_inventory()
    root = browser_fs.open_root(output)
    original_write = browser_fs.os.write

    def short_write(descriptor: int, content: object) -> int:
        return original_write(descriptor, content[:1])  # type: ignore[index]

    browser_fs.os.write = short_write
    try:
        browser_fs.publish_report(root, output, item, payload)
    finally:
        browser_fs.os.write = original_write
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    try:
        for _ in range(2):
            expect_failure(
                lambda root=root, output=output, item=item, payload=payload: (
                    browser_fs.publish_report(root, output, item, payload)
                )
            )
            assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    finally:
        os.close(root)


def report_write_and_fsync_failures_clean_owned_paths() -> None:
    for mode in ("write", "fsync"):
        output = Path(tempfile.mkdtemp(prefix=f"worker-report-{mode}-"))
        item, payload = report_inventory()
        root = browser_fs.open_root(output)
        original_write = browser_fs.os.write
        original_fsync = browser_fs.os.fsync
        if mode == "write":
            browser_fs.os.write = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected report write failure")
            )
        else:
            browser_fs.os.fsync = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected report fsync failure")
            )
        try:
            expect_failure(
                lambda root=root, output=output, item=item, payload=payload: (
                    browser_fs.publish_report(root, output, item, payload)
                )
            )
        finally:
            browser_fs.os.write = original_write
            browser_fs.os.fsync = original_fsync
            os.close(root)
        assert list(output.iterdir()) == []


def displaced_report_publication_preserves_new_parent() -> None:
    parent = Path(tempfile.mkdtemp(prefix="worker-report-displaced-"))
    output, moved = parent / "output", parent / "moved"
    output.mkdir()
    item, payload = report_inventory()
    root = browser_fs.open_root(output)
    original_link = browser_fs.os.link
    displaced = False

    def displace_after_link(*args: object, **kwargs: object) -> None:
        nonlocal displaced
        original_link(*args, **kwargs)
        if not displaced:
            displaced = True
            output.rename(moved)
            output.mkdir()
            (output / "foreign").write_bytes(b"preserve")

    browser_fs.os.link = displace_after_link
    try:
        expect_failure(lambda: browser_fs.publish_report(root, output, item, payload))
    finally:
        browser_fs.os.link = original_link
        os.close(root)
    assert displaced
    assert {path.name: path.read_bytes() for path in output.iterdir()} == {
        "foreign": b"preserve"
    }
    assert list(moved.iterdir()) == []


def final_report_close_is_cleanup_only() -> None:
    output = Path(tempfile.mkdtemp(prefix="worker-report-final-close-"))
    item, payload = report_inventory()
    raw = (
        json.dumps(
            {"artifacts": [item], "command": "publish-report"},
            separators=(",", ":"),
        ).encode()
        + b"\n"
        + payload
    )
    root = browser_fs.open_root(output)
    original_open_root = browser_fs.open_root
    original_close = browser_fs.os.close
    original_argv, original_stdin = sys.argv, sys.stdin
    calls = 0
    close_failure_observed = False

    def open_for_main(path: Path) -> int:
        nonlocal calls
        calls += 1
        return root if calls == 1 else original_open_root(path)

    def fail_regular_close(descriptor: int) -> None:
        nonlocal close_failure_observed
        regular = stat.S_ISREG(os.fstat(descriptor).st_mode)
        original_close(descriptor)
        if regular:
            close_failure_observed = True
            raise OSError("injected final report close failure")

    browser_fs.open_root = open_for_main
    browser_fs.os.close = fail_regular_close
    sys.argv = [str(HELPER), str(output)]
    sys.stdin = type("Input", (), {"buffer": io.BytesIO(raw)})()
    try:
        assert browser_fs.main() == 0
    finally:
        browser_fs.open_root = original_open_root
        browser_fs.os.close = original_close
        sys.argv, sys.stdin = original_argv, original_stdin
    assert close_failure_observed
    assert (output / str(item["name"])).read_bytes() == payload


publication_phases()
displaced_publication()
replacement_before_staging()
receipt_recheck()
displaced_read()
early_failure_cleanup()
foreign_cleanup_race()
existing_outputs_do_not_stage_on_retry()
final_identity_pass()
final_link_replacement()
rollback_retries_and_preserves_primary()
final_root_close_is_cleanup_only()
report_publication_is_exact_and_read_only()
report_short_write_and_no_overwrite()
report_write_and_fsync_failures_clean_owned_paths()
displaced_report_publication_preserves_new_parent()
final_report_close_is_cleanup_only()
print("browser shard filesystem adversarial checks passed")
