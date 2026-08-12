"""Complete synthetic candidate assembly and publication boundary tests."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
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
RECEIPT = ROOT / "contracts/candidate-completeness/v1/fixtures/assembly/complete-synthetic.json"
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


def test_complete_fixture_writes_manifest_last_and_runs_byte_gate_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    writes: list[str] = []
    gates: list[Path] = []
    real_write = assembler._write_new
    real_gate = assembler.validate_candidate_root

    def observe_write(root: int, path: str, raw: bytes) -> None:
        writes.append(Path(path).name)
        real_write(root, path, raw)

    def observe_gate(root: int):  # type: ignore[no-untyped-def]
        gates.append(root)
        return real_gate(root)

    monkeypatch.setattr(assembler, "_write_new", observe_write)
    monkeypatch.setattr(assembler, "validate_candidate_root", observe_gate)
    output = tmp_path / "candidate"
    summary = assemble_candidate_fixture(RECEIPT, output)

    assert writes[-4:] == ["gate-report.json", "gate-report.md", "checksums.txt", "manifest.json"]
    assert len(gates) == 2 and gates[0] == gates[1]
    assert summary.artifact_count == 53
    assert summary.manifest_sha256 == _load()["expectedManifestSha256"]
    assert (summary.production, summary.publication) == (False, False)
    assert len(_bytes(output)) == 54
    assert validate_candidate_root(output).manifest_sha256 == summary.manifest_sha256
    assert all((path.stat().st_mode & 0o222) == 0 for path in output.rglob("*"))
    assert output.stat().st_mode & 0o222 == 0

    cli_output = tmp_path / "candidate-cli"
    assert main(["--receipt", str(RECEIPT), "--output", str(cli_output)]) == 0
    assert "production and publication not claimed" in capsys.readouterr().out


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
    assert not list(tmp_path.glob(".candidate-assembly-*"))


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

    def rename_parent(root: int, paths: object) -> None:
        real_sync(root, paths)  # type: ignore[arg-type]
        parent.rename(moved)
        parent.mkdir()
        (parent / "foreign.txt").write_text("unchanged\n", encoding="utf-8")

    monkeypatch.setattr(assembler, "_fsync_tree", rename_parent)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, output)
    assert (parent / "foreign.txt").read_text(encoding="utf-8") == "unchanged\n"
    assert not list(moved.glob(".candidate-assembly-*"))


def test_post_promotion_failure_rolls_back_only_owned_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, unrelated = tmp_path / "candidate", tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep\n", encoding="utf-8")
    real_gate, calls = assembler.validate_candidate_root, 0

    def fail_final(root: int):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise assembler.CandidateContractError("candidate-changed", "injected")
        return real_gate(root)

    monkeypatch.setattr(assembler, "validate_candidate_root", fail_final)
    with pytest.raises(CandidateAssemblyError, match="foreign-replacement"):
        assemble_candidate_fixture(RECEIPT, output)
    assert not output.exists()
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert not list(tmp_path.glob(".candidate-assembly-*"))


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
