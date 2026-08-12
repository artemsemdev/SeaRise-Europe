"""Complete synthetic candidate assembly and publication boundary tests."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import stat
from pathlib import Path
from typing import Any, Callable

import pytest

import searise_pipeline.candidate_completeness.assembler as assembler
from searise_pipeline.candidate_completeness import (
    CandidateAssemblyError,
    assemble_candidate_fixture,
    validate_candidate_root,
)

ROOT = Path(__file__).resolve().parents[4]
RECEIPT = ROOT / "contracts/candidate-completeness/v2/fixtures/assembly/complete-synthetic.json"
main = runpy.run_path(str(ROOT / "scripts/release/assemble_candidate_fixture.py"))["main"]


def _load() -> dict[str, Any]:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _write_receipt(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "assembly-receipt.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _entry(document: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    return next(item for item in document["inputs"] if item["artifactId"] == artifact_id)


def _rehash(document: dict[str, Any], entry: dict[str, Any]) -> None:
    raw = assembler._payload_bytes(document["fixtureId"], entry)
    entry["payloadSha256"] = hashlib.sha256(raw).hexdigest()


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _private_wrappers(root: Path) -> list[Path]:
    wrappers = sorted(root.glob(".candidate-assembly-*"))
    assert all(path.is_dir() and path.stat().st_mode & 0o777 == 0o700 for path in wrappers)
    return wrappers


def _fails(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    document = _load()
    mutation(document)
    output = tmp_path / "candidate"
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(_write_receipt(tmp_path, document), output)
    assert caught.value.code == code
    assert not output.exists()


def test_complete_fixture_writes_manifest_last_and_runs_byte_gate_three_times(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writes: list[str] = []
    gates: list[Path] = []
    real_write = assembler._write_new
    real_gate = assembler.validate_candidate_root

    def observe_write(
        root: int, path: str, raw: bytes, ownership: assembler._StageOwnership
    ) -> None:
        writes.append(Path(path).name)
        real_write(root, path, raw, ownership)

    def observe_gate(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        gates.append(root)
        return real_gate(root, **kwargs)

    monkeypatch.setattr(assembler, "_write_new", observe_write)
    monkeypatch.setattr(assembler, "validate_candidate_root", observe_gate)
    output = tmp_path / "candidate"
    summary = assemble_candidate_fixture(RECEIPT, output)

    assert writes[-4:] == ["gate-report.json", "gate-report.md", "checksums.txt", "manifest.json"]
    assert len(gates) == 3 and gates[0] == gates[1] == gates[2]
    assert summary.artifact_count == 54
    assert summary.manifest_sha256 == _load()["expectedManifestSha256"]
    assert (summary.production, summary.publication) == (False, False)
    assert len(_bytes(output)) == 55
    assert validate_candidate_root(output).manifest_sha256 == summary.manifest_sha256
    assert all((path.stat().st_mode & 0o222) == 0 for path in output.rglob("*"))
    assert output.stat().st_mode & 0o222 == 0
    wrappers = _private_wrappers(tmp_path)
    assert len(wrappers) == 1
    assert list(wrappers[0].iterdir()) == []

    cli_output = tmp_path / "candidate-cli"
    assert main(["--receipt", str(RECEIPT), "--output", str(cli_output)]) == 0
    assert "production and publication not claimed" in capsys.readouterr().out
    wrappers = _private_wrappers(tmp_path)
    assert len(wrappers) == 2
    assert all(list(wrapper.iterdir()) == [] for wrapper in wrappers)


def test_missing_layer_fails_before_staging(tmp_path: Path) -> None:
    _fails(
        tmp_path,
        lambda document: document["inputs"].pop(32),
        "assembly-inputs",
    )


def test_bad_input_hash_fails_before_staging(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["inputs"][0]["payloadSha256"] = "0" * 64

    _fails(tmp_path, mutate, "assembly-input-hash")


def test_bad_stac_link_fails_closed(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        item = _entry(document, "stac-item-ssp1-26-2030")
        item["stacAssets"]["visual"] = "layers/ssp5-85/2100.pmtiles"
        _rehash(document, item)

    _fails(tmp_path, mutate, "stac-link")


def test_invalid_fixture_rights_fail_closed(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["rights"]["redistribution"] = "denied"

    _fails(tmp_path, mutate, "fixture-rights")


def test_grid_drift_fails_closed(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        item = _entry(document, "projection-ssp2-45-2050-cog")
        item["gridId"] = "0" * 64
        _rehash(document, item)

    _fails(tmp_path, mutate, "grid-drift")


def test_projection_parity_mismatch_fails_closed(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        item = _entry(document, "projection-ssp5-85-2100-pmtiles")
        item["parityId"] = "ssp1-26-2030"
        _rehash(document, item)

    _fails(tmp_path, mutate, "parity-mismatch")


def test_failed_exclusive_rename_leaves_no_partial_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "candidate"

    def fail(*_args: object) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(assembler, "_rename_no_overwrite", fail)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, output)
    assert caught.value.code == "assembly-publication"
    assert not output.exists()
    assert len(_private_wrappers(tmp_path)) <= 1


def test_publication_collision_preserves_foreign_target_without_failed_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "candidate"
    real_rename = assembler._rename_no_overwrite
    collided = False

    def collide(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal collided
        if source == "candidate" and target == "candidate" and parent != destination:
            collided = True
            os.mkdir(target, 0o700, dir_fd=destination)
            foreign_parent = os.open(
                target, assembler._directory_flags(), dir_fd=destination
            )
            try:
                foreign = os.open(
                    "keep.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=foreign_parent,
                )
                os.write(foreign, b"foreign")
                os.close(foreign)
            finally:
                os.close(foreign_parent)
        real_rename(parent, source, destination, target)

    monkeypatch.setattr(assembler, "_rename_no_overwrite", collide)
    with pytest.raises(CandidateAssemblyError, match="could not be promoted"):
        assemble_candidate_fixture(RECEIPT, output)
    assert collided
    assert (output / "keep.txt").read_bytes() == b"foreign"
    assert not (output / "manifest.json").exists()
    assert len(_private_wrappers(tmp_path)) == 1


def test_rebuilds_are_byte_identical(tmp_path: Path) -> None:
    first = assemble_candidate_fixture(RECEIPT, tmp_path / "candidate-a")
    second = assemble_candidate_fixture(RECEIPT, tmp_path / "candidate-b")

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.artifact_bytes == second.artifact_bytes
    assert _bytes(first.output_directory) == _bytes(second.output_directory)


def test_staging_parent_rename_cannot_redirect_held_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, output = tmp_path / "parent", tmp_path / "parent" / "candidate"
    parent.mkdir()
    moved = tmp_path / "parent-moved"
    real_sync = assembler._fsync_tree

    def rename_parent(
        root: int, paths: object, ownership: assembler._StageOwnership
    ) -> None:
        real_sync(root, paths, ownership)  # type: ignore[arg-type]
        parent.rename(moved)
        parent.mkdir()
        (parent / "foreign.txt").write_text("unchanged\n", encoding="utf-8")

    monkeypatch.setattr(assembler, "_fsync_tree", rename_parent)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, output)
    assert (parent / "foreign.txt").read_text(encoding="utf-8") == "unchanged\n"
    assert len(_private_wrappers(moved)) == 1


def test_post_promotion_failure_rolls_back_only_owned_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, unrelated = tmp_path / "candidate", tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep\n", encoding="utf-8")
    real_gate, calls = assembler.validate_candidate_root, 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "injected")
        return real_gate(root, **kwargs)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    with pytest.raises(
        CandidateAssemblyError, match="independent candidate byte gate failed"
    ) as caught:
        assemble_candidate_fixture(RECEIPT, output)
    assert caught.value.code == "foreign-replacement"
    assert not output.exists()
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert len(_private_wrappers(tmp_path)) == 1


def test_post_promotion_rollback_avoids_foreign_staging_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "candidate"
    real_gate, calls = assembler.validate_candidate_root, 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            temporary = next(tmp_path.glob(".candidate-assembly-*"))
            foreign = temporary / "candidate"
            foreign.mkdir()
            (foreign / "keep.txt").write_text("keep\n", encoding="utf-8")
            raise assembler.CandidateContractError("candidate-changed", "injected")
        return real_gate(root, **kwargs)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    with pytest.raises(
        CandidateAssemblyError, match="independent candidate byte gate failed"
    ) as caught:
        assemble_candidate_fixture(RECEIPT, output)
    assert caught.value.code == "foreign-replacement"
    assert not output.exists()
    residues = list(tmp_path.glob(".candidate-assembly-*"))
    assert len(residues) == 1
    assert (residues[0] / "candidate/keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_rename_parent_syncs_source_before_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    source_fd = os.open(source, assembler._directory_flags())
    destination_fd = os.open(destination, assembler._directory_flags())
    observed: list[int] = []
    try:
        monkeypatch.setattr(assembler, "_sync_directory", lambda fd: observed.append(fd))
        assembler._sync_rename_parents(source_fd, destination_fd)
    finally:
        os.close(source_fd)
        os.close(destination_fd)
    assert observed == [source_fd, destination_fd]


def test_oversized_template_fails_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = tmp_path / "template.json"
    template.write_bytes(b"x" * (assembler._MAX_TEMPLATE_BYTES + 1))
    monkeypatch.setattr(assembler, "_TEMPLATE", template)
    with pytest.raises(CandidateAssemblyError, match="assembly-template"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")


def test_fifo_receipt_is_rejected_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "receipt"
    os.mkfifo(fifo)
    real_open, opened = assembler.os.open, False

    def observe(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal opened
        if path == fifo:
            opened = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(assembler.os, "open", observe)
    with pytest.raises(CandidateAssemblyError, match="bounded regular file"):
        assemble_candidate_fixture(fifo, tmp_path / "candidate")
    assert not opened


def test_predictable_directory_and_file_names_are_never_created_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_mkdir, real_open = assembler.os.mkdir, assembler.os.open
    predictable_creates: list[str] = []

    def replace_mkdir(name: object, *args: object, **kwargs: object) -> None:
        real_mkdir(name, *args, **kwargs)
        if name == "config":
            predictable_creates.append(str(name))
            directory = kwargs["dir_fd"]
            os.rename("config", "owned-config", src_dir_fd=directory, dst_dir_fd=directory)
            real_mkdir("config", 0o700, dir_fd=directory)

    def replace_open(name: object, flags: int, *args: object, **kwargs: object) -> int:
        if name == "scenarios.json" and flags & os.O_CREAT:
            predictable_creates.append(str(name))
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(assembler.os, "mkdir", replace_mkdir)
    monkeypatch.setattr(assembler.os, "open", replace_open)
    summary = assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert summary.artifact_count == 54
    assert predictable_creates == []


def test_private_directory_swap_before_create_returns_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_create = assembler._mkdir_exclusive
    calls = 0

    def swap(parent: int, name: str, mode: int) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        created = real_create(parent, name, mode)
        if calls == 2:
            os.rename(name, f"{name}-owned", src_dir_fd=parent, dst_dir_fd=parent)
            os.mkdir(name, 0o700, dir_fd=parent)
            foreign_parent = os.open(name, assembler._directory_flags(), dir_fd=parent)
            try:
                foreign = os.open(
                    "foreign.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=foreign_parent,
                )
                os.close(foreign)
            finally:
                os.close(foreign_parent)
        return created

    monkeypatch.setattr(assembler, "_mkdir_exclusive", swap)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    wrapper = _private_wrappers(tmp_path)[0]
    assert next(wrapper.rglob("foreign.txt")).read_bytes() == b""
    assert not (tmp_path / "candidate").exists()


def test_directory_promotion_swap_preserves_foreign_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = assembler._rename_no_overwrite
    injected = False

    def swap(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal injected
        real_rename(parent, source, destination, target)
        if target == "candidate" and source.startswith(".candidate-directory-"):
            injected = True
            os.rename(target, "candidate-owned", src_dir_fd=destination, dst_dir_fd=destination)
            os.mkdir(target, 0o700, dir_fd=destination)
            foreign_parent = os.open(
                target, assembler._directory_flags(), dir_fd=destination
            )
            try:
                foreign = os.open(
                    "keep.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=foreign_parent,
                )
                os.write(foreign, b"foreign")
                os.close(foreign)
            finally:
                os.close(foreign_parent)

    monkeypatch.setattr(assembler, "_rename_no_overwrite", swap)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    wrapper = _private_wrappers(tmp_path)[0]
    assert next(wrapper.rglob("keep.txt")).read_bytes() == b"foreign"
    assert next(wrapper.rglob("candidate-owned")).is_dir()
    assert not (tmp_path / "candidate").exists()


def test_file_promotion_swap_preserves_foreign_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = assembler._rename_no_overwrite
    injected = False

    def swap(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal injected
        real_rename(parent, source, destination, target)
        if target == "scenarios.json" and source.startswith(".candidate-file-"):
            injected = True
            os.rename(
                target,
                "scenarios-owned.json",
                src_dir_fd=destination,
                dst_dir_fd=destination,
            )
            foreign = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination,
            )
            os.write(foreign, b"foreign")
            os.close(foreign)

    monkeypatch.setattr(assembler, "_rename_no_overwrite", swap)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    wrapper = _private_wrappers(tmp_path)[0]
    assert next(wrapper.rglob("scenarios.json")).read_bytes() == b"foreign"
    assert next(wrapper.rglob("scenarios-owned.json")).is_file()
    assert not (tmp_path / "candidate").exists()


def test_cleanup_swap_restores_foreign_file_without_unlinking_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    root = os.open(stage, assembler._directory_flags())
    ownership = assembler._StageOwnership(
        root=assembler._directory_identity(os.fstat(root)), directories={}, files={}
    )
    assembler._write_new(root, "payload.bin", b"owned", ownership)
    real_rename, injected = assembler._rename_no_overwrite, False

    def swap(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal injected
        if source == "payload.bin" and target.startswith(".candidate-owned-") and not injected:
            injected = True
            real_rename(parent, source, parent, "owned-moved")
            foreign = os.open(
                source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
            )
            try:
                os.write(foreign, b"foreign")
            finally:
                os.close(foreign)
        real_rename(parent, source, destination, target)

    monkeypatch.setattr(assembler, "_rename_no_overwrite", swap)
    try:
        assembler._remove_owned_stage(root, ownership)
    finally:
        os.close(root)
    assert injected
    assert (stage / "payload.bin").read_bytes() == b"foreign"
    assert (stage / "owned-moved").read_bytes() == b"owned"


def test_partial_stage_initialization_failure_leaves_no_owned_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_create = assembler._create_owned_directory

    def fail(parent: int, name: str, mode: int = 0o755):  # type: ignore[no-untyped-def]
        if name == "candidate":
            raise OSError("injected candidate open failure")
        return real_create(parent, name, mode)

    monkeypatch.setattr(assembler, "_create_owned_directory", fail)
    with pytest.raises(CandidateAssemblyError, match="could not be promoted"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert len(_private_wrappers(tmp_path)) == 1


def test_rollback_quarantine_swap_preserves_foreign_without_public_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root
    real_rename = assembler._rename_no_overwrite
    gate_calls = 0
    rollback_swapped = False

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "injected")
        return real_gate(root, **kwargs)

    def swap(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal rollback_swapped
        real_rename(parent, source, destination, target)
        if target.startswith(".candidate-rollback-"):
            rollback_swapped = True
            os.rename(
                target,
                f"{target}-owned",
                src_dir_fd=destination,
                dst_dir_fd=destination,
            )
            os.mkdir(target, 0o700, dir_fd=destination)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    monkeypatch.setattr(assembler, "_rename_no_overwrite", swap)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert rollback_swapped
    assert not (tmp_path / "candidate").exists()
    wrapper = _private_wrappers(tmp_path)[0]
    assert len(list(wrapper.glob(".candidate-rollback-*"))) == 2


def test_rollback_exchange_collision_exhaustion_reports_public_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root
    gate_calls = collisions = 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "injected")
        return real_gate(root, **kwargs)

    def collide(_left: int, _source: str, _right: int, _target: str) -> None:
        nonlocal collisions
        collisions += 1
        raise FileExistsError("injected exchange collision")

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    monkeypatch.setattr(assembler, "_rename_exchange", collide)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.cleanup_error is not None
    assert caught.value.cleanup_error.startswith("assembly-rollback:")
    assert collisions == 1024
    assert (tmp_path / "candidate/manifest.json").is_file()
    assert list(tmp_path.glob(".candidate-rollback-*")) == []


def test_transient_rollback_permission_error_is_retried_without_public_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root
    real_exchange = assembler._rename_exchange
    gate_calls = rollback_calls = 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "primary failure")
        return real_gate(root, **kwargs)

    def transient(left: int, source: str, right: int, target: str) -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        if rollback_calls == 1:
            raise PermissionError("transient rollback denial")
        real_exchange(left, source, right, target)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    monkeypatch.setattr(assembler, "_rename_exchange", transient)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.code == "foreign-replacement"
    assert caught.value.cleanup_error is None
    assert rollback_calls == 2
    assert not (tmp_path / "candidate").exists()


def test_persistent_rollback_failure_preserves_primary_error_and_reports_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root
    gate_calls = 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "primary failure")
        return real_gate(root, **kwargs)

    def deny(_left: int, _source: str, _right: int, _target: str) -> None:
        raise PermissionError("persistent rollback denial")

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    monkeypatch.setattr(assembler, "_rename_exchange", deny)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.code == "foreign-replacement"
    assert caught.value.cleanup_error is not None
    assert caught.value.cleanup_error.startswith("assembly-rollback:")
    assert "cleanup failure: assembly-rollback:" in str(caught.value)
    assert (tmp_path / "candidate/manifest.json").is_file()
    assert list(tmp_path.glob(".candidate-rollback-*")) == []


def test_rollback_slot_reservation_denial_reports_explicit_public_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root
    real_reserve = assembler._reserve_owned_directory
    gate_calls = 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "primary failure")
        return real_gate(root, **kwargs)

    def deny(parent: int, prefix: str, mode: int):  # type: ignore[no-untyped-def]
        if prefix == ".candidate-rollback-":
            raise PermissionError("rollback slot reservation denied")
        return real_reserve(parent, prefix, mode)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    monkeypatch.setattr(assembler, "_reserve_owned_directory", deny)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.code == "foreign-replacement"
    assert caught.value.cleanup_error is not None
    assert caught.value.cleanup_error.startswith("assembly-rollback:")
    assert "slot reservation failed" in caught.value.cleanup_error
    assert (tmp_path / "candidate/manifest.json").is_file()
    assert list(tmp_path.glob(".candidate-rollback-*")) == []


def test_rollback_slot_post_mkdir_binding_failure_quarantines_exact_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root
    real_open = assembler.os.open
    gate_calls = 0

    def fail_final(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "primary failure")
        return real_gate(root, **kwargs)

    def fail_binding(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if isinstance(path, str) and path.startswith(".candidate-rollback-"):
            raise PermissionError("rollback slot binding denied after mkdir")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    monkeypatch.setattr(assembler.os, "open", fail_binding)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.code == "foreign-replacement"
    assert caught.value.cleanup_error is not None
    assert caught.value.cleanup_error.startswith("assembly-rollback:")
    assert "slot reservation failed" in caught.value.cleanup_error
    assert (tmp_path / "candidate/manifest.json").is_file()
    assert list(tmp_path.glob(".candidate-rollback-*")) == []
    quarantines = list(tmp_path.glob(".candidate-owned-*"))
    assert len(quarantines) == 1 and quarantines[0].is_dir()
    assert list(quarantines[0].iterdir()) == []


def test_post_promotion_fchmod_failure_moves_candidate_away_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = assembler._rename_no_overwrite
    real_fchmod = assembler.os.fchmod
    promoted = False

    def observe_promotion(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal promoted
        real_rename(parent, source, destination, target)
        if source == "candidate" and target == "candidate" and parent != destination:
            promoted = True

    def deny_after_promotion(descriptor: int, mode: int) -> None:
        if promoted:
            raise PermissionError("persistent post-promotion fchmod denial")
        real_fchmod(descriptor, mode)

    monkeypatch.setattr(assembler, "_rename_no_overwrite", observe_promotion)
    monkeypatch.setattr(assembler.os, "fchmod", deny_after_promotion)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.code == "assembly-publication"
    assert caught.value.cleanup_error is not None
    assert not (tmp_path / "candidate").exists()
    assert len(list(tmp_path.glob(".candidate-rollback-*"))) == 1


def test_post_promotion_fsync_failure_moves_candidate_away_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = assembler._rename_no_overwrite
    real_fsync = assembler.os.fsync
    promoted = False

    def observe_promotion(parent: int, source: str, destination: int, target: str) -> None:
        nonlocal promoted
        real_rename(parent, source, destination, target)
        if source == "candidate" and target == "candidate" and parent != destination:
            promoted = True

    def deny_after_promotion(descriptor: int) -> None:
        if promoted:
            raise PermissionError("persistent post-promotion fsync denial")
        real_fsync(descriptor)

    monkeypatch.setattr(assembler, "_rename_no_overwrite", observe_promotion)
    monkeypatch.setattr(assembler.os, "fsync", deny_after_promotion)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert caught.value.code == "assembly-publication"
    assert caught.value.cleanup_error is not None
    assert not (tmp_path / "candidate").exists()
    assert len(list(tmp_path.glob(".candidate-rollback-*"))) == 1


def test_output_requires_absolute_symlink_free_owner_controlled_parent(
    tmp_path: Path,
) -> None:
    with pytest.raises(CandidateAssemblyError, match="absolute path"):
        assemble_candidate_fixture(RECEIPT, Path("relative-candidate"))

    shared = tmp_path / "shared"
    shared.mkdir(mode=0o700)
    shared.chmod(0o770)
    with pytest.raises(CandidateAssemblyError, match="owner-controlled"):
        assemble_candidate_fixture(RECEIPT, shared / "candidate")

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(CandidateAssemblyError, match="could not be promoted"):
        assemble_candidate_fixture(RECEIPT, linked / "candidate")
    assert stat.S_ISLNK(linked.lstat().st_mode)


def test_mkdir_first_stat_hook_cannot_reenter_assembler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_identity = assembler._entry_identity
    reentrant_codes: list[str] = []

    def inspect(parent: int, name: str):  # type: ignore[no-untyped-def]
        if name.startswith(".candidate-assembly-") and not reentrant_codes:
            with pytest.raises(CandidateAssemblyError) as caught:
                assemble_candidate_fixture(RECEIPT, tmp_path / "nested")
            reentrant_codes.append(caught.value.code)
        return real_identity(parent, name)

    monkeypatch.setattr(assembler, "_entry_identity", inspect)
    summary = assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert summary.artifact_count == 54
    assert reentrant_codes == ["assembly-reentrant"]


def test_pre_freeze_writer_hook_must_close_writer_and_cannot_reenter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_freeze = assembler._freeze
    reentrant_codes: list[str] = []

    def pre_freeze(
        root: int, paths: object, ownership: assembler._StageOwnership
    ) -> None:
        writer = os.open("checksums.txt", os.O_RDWR, dir_fd=root)
        try:
            with pytest.raises(CandidateAssemblyError) as caught:
                assemble_candidate_fixture(RECEIPT, tmp_path / "nested")
            reentrant_codes.append(caught.value.code)
        finally:
            os.close(writer)
        real_freeze(root, paths, ownership)  # type: ignore[arg-type]

    monkeypatch.setattr(assembler, "_freeze", pre_freeze)
    summary = assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert summary.artifact_count == 54
    assert reentrant_codes == ["assembly-reentrant"]
    assert validate_candidate_root(summary.output_directory).artifact_count == 54


def test_every_mode_change_is_fsynced_before_the_next_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_chmod, real_fsync = assembler.os.fchmod, assembler.os.fsync
    events: list[tuple[str, int]] = []

    def chmod(descriptor: int, mode: int) -> None:
        events.append(("chmod", os.fstat(descriptor).st_ino))
        real_chmod(descriptor, mode)

    def fsync(descriptor: int) -> None:
        events.append(("fsync", os.fstat(descriptor).st_ino))
        real_fsync(descriptor)

    monkeypatch.setattr(assembler.os, "fchmod", chmod)
    monkeypatch.setattr(assembler.os, "fsync", fsync)
    assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    for index, event in enumerate(events):
        if event[0] == "chmod":
            assert events[index + 1] == ("fsync", event[1])


def test_cleanup_syncs_parent_and_leaves_no_owned_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = assembler._rename_no_overwrite
    real_sync = assembler._sync_directory
    synced: list[int] = []

    def fail_promotion(parent: int, source: str, destination: int, target: str) -> None:
        if source == "candidate" and target == "candidate":
            raise OSError("injected promotion failure")
        real_rename(parent, source, destination, target)

    def sync(descriptor: int) -> None:
        synced.append(os.fstat(descriptor).st_ino)
        real_sync(descriptor)

    parent_inode = tmp_path.stat().st_ino
    monkeypatch.setattr(assembler, "_rename_no_overwrite", fail_promotion)
    monkeypatch.setattr(assembler, "_sync_directory", sync)
    with pytest.raises(CandidateAssemblyError, match="assembly-publication"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert parent_inode in synced
    assert len(_private_wrappers(tmp_path)) == 1


def test_transient_post_validation_mutation_is_detected_and_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_commit = assembler._commit_matches
    calls = 0

    def mutate(parent_path: Path, parent: int, name: str, stage: int) -> bool:
        nonlocal calls
        calls += 1
        result = real_commit(parent_path, parent, name, stage)
        if calls == 2:
            descriptor = os.open("checksums.txt", os.O_RDONLY, dir_fd=stage)
            os.fchmod(descriptor, 0o600)
            os.close(descriptor)
            descriptor = os.open("checksums.txt", os.O_RDWR, dir_fd=stage)
            original = os.pread(descriptor, 1, 0)
            os.pwrite(descriptor, b"X", 0)
            os.fsync(descriptor)
            os.pwrite(descriptor, original, 0)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o444)
            os.fsync(descriptor)
            os.close(descriptor)
        return result

    monkeypatch.setattr(assembler, "_commit_matches", mutate)
    with pytest.raises(CandidateAssemblyError, match="final publication boundary"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert len(_private_wrappers(tmp_path)) == 1


def test_transient_mutation_during_final_authority_pass_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler.validate_candidate_root

    def mutate(root: int, **kwargs: object):  # type: ignore[no-untyped-def]
        authority = kwargs.get("final_root_authority")
        if authority is not None:
            def changed() -> int:
                descriptor = authority()  # type: ignore[operator]
                mode_descriptor = os.open("checksums.txt", os.O_RDONLY, dir_fd=descriptor)
                os.fchmod(mode_descriptor, 0o600)
                os.close(mode_descriptor)
                file_descriptor = os.open("checksums.txt", os.O_RDWR, dir_fd=descriptor)
                original = os.pread(file_descriptor, 1, 0)
                os.pwrite(file_descriptor, b"X", 0)
                os.fsync(file_descriptor)
                os.pwrite(file_descriptor, original, 0)
                os.fsync(file_descriptor)
                os.fchmod(file_descriptor, 0o444)
                os.fsync(file_descriptor)
                os.close(file_descriptor)
                return descriptor

            kwargs["final_root_authority"] = changed
        return real_gate(root, **kwargs)

    monkeypatch.setattr(assembler, "validate_candidate_root", mutate)
    with pytest.raises(CandidateAssemblyError, match="independent candidate byte gate failed"):
        assemble_candidate_fixture(RECEIPT, tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()
    assert len(_private_wrappers(tmp_path)) == 1


def test_success_is_point_in_time_not_a_pathname_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler._final_publication_gate
    displaced = tmp_path / "candidate-after-linearization"

    def move_after_linearization(
        parent_path: Path,
        parent: int,
        output_name: str,
        stage: int,
        expected: assembler.CandidateByteSummary,
    ) -> assembler.CandidateByteSummary:
        sealed = real_gate(parent_path, parent, output_name, stage, expected)
        os.rename(output_name, displaced.name, src_dir_fd=parent, dst_dir_fd=parent)
        return sealed

    monkeypatch.setattr(assembler, "_final_publication_gate", move_after_linearization)
    output = tmp_path / "candidate"
    summary = assemble_candidate_fixture(RECEIPT, output)
    assert summary.artifact_count == 54
    assert not output.exists()
    assert validate_candidate_root(displaced).manifest_sha256 == summary.manifest_sha256


def test_post_commit_staging_cleanup_failure_does_not_hide_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleanup_called = False

    def fail_cleanup(*_args: object) -> None:
        nonlocal cleanup_called
        cleanup_called = True
        raise OSError("injected post-commit staging cleanup failure")

    monkeypatch.setattr(assembler, "_cleanup_staging", fail_cleanup)
    output = tmp_path / "candidate"
    summary = assemble_candidate_fixture(RECEIPT, output)
    assert cleanup_called
    assert summary.output_directory == output
    assert validate_candidate_root(output).manifest_sha256 == summary.manifest_sha256


def test_post_commit_descriptor_close_failure_does_not_hide_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_gate = assembler._final_publication_gate
    real_close = assembler.os.close
    committed = close_failed = False

    def observe_commit(*args: object, **kwargs: object) -> assembler.CandidateByteSummary:
        nonlocal committed
        result = real_gate(*args, **kwargs)  # type: ignore[arg-type]
        committed = True
        return result

    def fail_first_close(descriptor: int) -> None:
        nonlocal close_failed
        if committed and not close_failed:
            close_failed = True
            raise OSError("injected post-commit descriptor close failure")
        real_close(descriptor)

    monkeypatch.setattr(assembler, "_final_publication_gate", observe_commit)
    monkeypatch.setattr(assembler.os, "close", fail_first_close)
    output = tmp_path / "candidate"
    summary = assemble_candidate_fixture(RECEIPT, output)
    assert close_failed
    assert summary.output_directory == output
    assert validate_candidate_root(output).manifest_sha256 == summary.manifest_sha256
