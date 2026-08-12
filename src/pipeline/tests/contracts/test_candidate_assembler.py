"""Complete synthetic candidate assembly and publication boundary tests."""

from __future__ import annotations

import hashlib
import json
import runpy
import shutil
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

    def observe_write(path: Path, raw: bytes) -> None:
        writes.append(path.name)
        real_write(path, raw)

    def observe_gate(path: Path):  # type: ignore[no-untyped-def]
        gates.append(path)
        return real_gate(path)

    monkeypatch.setattr(assembler, "_write_new", observe_write)
    monkeypatch.setattr(assembler, "validate_candidate_root", observe_gate)
    output = tmp_path / "candidate"
    summary = assemble_candidate_fixture(RECEIPT, output)

    assert writes[-4:] == ["gate-report.json", "gate-report.md", "checksums.txt", "manifest.json"]
    assert len(gates) == 2 and gates[0] != output and gates[1] == output
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


def test_foreign_replacement_is_detected_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "candidate"
    real_rename = assembler._rename_no_overwrite

    def replace(source_parent: int, source: str, output_parent: int, target: str) -> None:
        real_rename(source_parent, source, output_parent, target)
        assembler._thaw(output)
        shutil.rmtree(output)
        output.mkdir()
        (output / "foreign.txt").write_text("preserve foreign bytes\n", encoding="utf-8")

    monkeypatch.setattr(assembler, "_rename_no_overwrite", replace)
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_candidate_fixture(RECEIPT, output)
    assert caught.value.code == "foreign-replacement"
    assert (output / "foreign.txt").read_text(encoding="utf-8") == "preserve foreign bytes\n"
