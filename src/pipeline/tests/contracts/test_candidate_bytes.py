"""Adversarial tests for the assembled candidate byte gate."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import runpy
from pathlib import Path
from typing import Any

import pytest

import searise_pipeline.candidate_completeness.byte_gate as byte_gate
from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    validate_candidate_root,
)

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "contracts/candidate-completeness/v1/fixtures/valid/engineering-candidate.json"
main = runpy.run_path(str(ROOT / "scripts/release/validate_candidate_bytes.py"))["main"]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_bytes(candidate: dict[str, Any]) -> bytes:
    return (json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write_manifest(root: Path, candidate: dict[str, Any]) -> None:
    (root / "manifest.json").write_bytes(_manifest_bytes(candidate))


def _candidate(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, bytes]]:
    root = tmp_path / "candidate"
    candidate = copy.deepcopy(_load(FIXTURE))
    contents: dict[str, bytes] = {}
    for artifact in candidate["artifacts"]:
        if artifact["role"] == "checksums":
            continue
        raw = f"phase-1 fixture bytes: {artifact['artifactId']}\n".encode()
        artifact.update(byteSize=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        contents[artifact["path"]] = raw
    candidate["checksumInventory"]["subjects"] = sorted(
        (
            {"path": item["path"], "sha256": item["sha256"]}
            for item in candidate["artifacts"]
            if item["role"] != "checksums"
        ),
        key=lambda item: item["path"],
    )
    checksums = "".join(
        f"{item['sha256']}  {item['path']}\n" for item in candidate["checksumInventory"]["subjects"]
    ).encode()
    checksum_artifact = next(item for item in candidate["artifacts"] if item["role"] == "checksums")
    checksum_artifact.update(byteSize=len(checksums), sha256=hashlib.sha256(checksums).hexdigest())
    contents[checksum_artifact["path"]] = checksums
    for logical, raw in contents.items():
        target = root / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    _write_manifest(root, candidate)
    return root, candidate, contents


def _artifact(candidate: dict[str, Any], role: str) -> dict[str, Any]:
    return next(item for item in candidate["artifacts"] if item["role"] == role)


def test_exact_53_artifact_candidate_validates_without_write_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, candidate, contents = _candidate(tmp_path)
    real_open = byte_gate.os.open

    def read_only_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(byte_gate.os, "open", read_only_open)
    summary = validate_candidate_root(root)
    assert summary.candidate_id == candidate["candidateId"]
    assert summary.artifact_count == 53
    assert summary.artifact_bytes == sum(map(len, contents.values()))
    assert (
        summary.manifest_sha256 == hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    )
    assert (summary.production, summary.publication) == (False, False)
    assert main(["--candidate-root", str(root)]) == 0
    output = capsys.readouterr().out
    assert "53 artifacts" in output
    assert "production and publication not claimed" in output


@pytest.mark.parametrize("mutation", ["missing", "extra-file", "extra-directory"])
def test_candidate_tree_requires_exact_files_and_no_extras(tmp_path: Path, mutation: str) -> None:
    root, candidate, _ = _candidate(tmp_path)
    target = root / candidate["artifacts"][0]["path"]
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra-file":
        (root / "untracked.bin").write_bytes(b"untracked")
    else:
        (root / "empty-extra-directory").mkdir()
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "candidate-files"


@pytest.mark.parametrize("field", ["byteSize", "sha256"])
def test_declared_size_and_sha256_bind_exact_artifact_bytes(tmp_path: Path, field: str) -> None:
    root, candidate, _ = _candidate(tmp_path)
    artifact = candidate["artifacts"][0]
    artifact[field] = artifact[field] + 1 if field == "byteSize" else "0" * 64
    if field == "sha256":
        subject = next(
            item
            for item in candidate["checksumInventory"]["subjects"]
            if item["path"] == artifact["path"]
        )
        subject["sha256"] = artifact["sha256"]
    _write_manifest(root, candidate)
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "artifact-bytes"


@pytest.mark.parametrize("field,value", [("role", "checksums"), ("mediaType", "text/plain")])
def test_roles_and_media_types_remain_exact_inventory_authority(
    tmp_path: Path, field: str, value: str
) -> None:
    root, candidate, _ = _candidate(tmp_path)
    candidate["artifacts"][0][field] = value
    _write_manifest(root, candidate)
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code in {"artifact-inventory", "candidate-schema"}


def test_checksums_file_is_replayed_from_manifest_subjects(tmp_path: Path) -> None:
    root, candidate, _ = _candidate(tmp_path)
    artifact = _artifact(candidate, "checksums")
    path = root / artifact["path"]
    changed = path.read_bytes().replace(b"  config/", b" *config/", 1)
    path.write_bytes(changed)
    artifact.update(byteSize=len(changed), sha256=hashlib.sha256(changed).hexdigest())
    _write_manifest(root, candidate)
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "checksum-file"


def test_intermediate_symlink_cannot_escape_candidate_root(tmp_path: Path) -> None:
    root, _, _ = _candidate(tmp_path / "assembled")
    outside = tmp_path / "outside-config"
    (root / "config").replace(outside)
    (root / "config").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "candidate-files"


def test_artifact_hard_link_is_rejected_as_externally_mutable(tmp_path: Path) -> None:
    root, candidate, _ = _candidate(tmp_path)
    target = root / candidate["artifacts"][0]["path"]
    os.link(target, tmp_path / "external-link.bin")
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "artifact-bytes"


def test_file_replacement_during_streaming_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, candidate, _ = _candidate(tmp_path)
    target = root / candidate["artifacts"][0]["path"]
    target_inode = target.stat().st_ino
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(target.read_bytes())
    real_read = byte_gate.os.read
    replaced = False

    def swap_after_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        raw = real_read(descriptor, count)
        if not replaced and os.fstat(descriptor).st_ino == target_inode:
            replacement.replace(target)
            replaced = True
        return raw

    monkeypatch.setattr(byte_gate.os, "read", swap_after_read)
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "candidate-changed"


def test_failure_never_repairs_or_rewrites_candidate(tmp_path: Path) -> None:
    root, candidate, _ = _candidate(tmp_path)
    target = root / candidate["artifacts"][0]["path"]
    target.write_bytes(b"X" * target.stat().st_size)
    before = {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode)
        for path in root.rglob("*")
        if path.is_file()
    }
    with pytest.raises(CandidateContractError):
        validate_candidate_root(root)
    after = {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_manifest_must_be_present_only_after_all_53_artifacts(tmp_path: Path) -> None:
    root, candidate, _ = _candidate(tmp_path)
    manifest = root / "manifest.json"
    manifest.unlink()
    with pytest.raises(CandidateContractError) as caught:
        validate_candidate_root(root)
    assert caught.value.code == "artifact-bytes"
    _write_manifest(root, candidate)
    assert validate_candidate_root(root).artifact_count == 53
