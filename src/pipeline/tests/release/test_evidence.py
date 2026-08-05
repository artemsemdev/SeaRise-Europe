"""Mutation tests for the immutable candidate seal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from searise_pipeline.release.evidence import candidate_binding
from searise_pipeline.science import ScienceContractError


def _write(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal(root: Path) -> None:
    checksum_path = root / "checksums.txt"
    checksums = [
        f"{_sha(path)}  {path.relative_to(root).as_posix()}"
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path != checksum_path
    ]
    checksum_path.write_text("\n".join(checksums) + "\n", encoding="utf-8")


def _candidate(root: Path) -> None:
    artifacts = []
    for index in range(31):
        relative = "analysis/value.bin" if index == 0 else f"analysis/value-{index:02d}.bin"
        data = root / relative
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_bytes(f"science-{index}\n".encode())
        artifacts.append(
            {
                "path": relative,
                "byteSize": data.stat().st_size,
                "sha256": _sha(data),
            }
        )
    _write(
        root / "manifest.json",
        {
            "releaseId": "candidate-v1",
            "releaseContractId": "ar6-europe-regional-release-v1",
            "artifacts": artifacts,
        },
    )
    _write(
        root / "build-receipt.json",
        {
            "releaseId": "candidate-v1",
            "sourceRevision": "a" * 40,
            "environmentIdentity": {"buildRunId": "test"},
        },
    )
    _write(root / "build-evidence.json", {"releaseId": "candidate-v1", "checks": {"x": True}})
    _write(root / "source-receipt.json", {"releaseContractSha256": "b" * 64})
    _write(root / "gate.json", {"automatedValidation": "pending"})
    _write(root / "statistics.json", {"layers": 9})
    _seal(root)


@pytest.mark.parametrize(
    ("relative", "replacement"),
    [
        ("build-evidence.json", {"releaseId": "candidate-v1", "checks": {"x": False}}),
        ("gate.json", {"automatedValidation": "passed"}),
        ("statistics.json", {"layers": 0}),
    ],
)
def test_candidate_seal_rejects_authoritative_file_tamper(
    tmp_path: Path, relative: str, replacement: object
) -> None:
    _candidate(tmp_path)
    candidate_binding(tmp_path)
    _write(tmp_path / relative, replacement)

    with pytest.raises(ScienceContractError, match="checksum inventory"):
        candidate_binding(tmp_path)


def test_candidate_seal_rejects_artifact_byte_tamper(tmp_path: Path) -> None:
    _candidate(tmp_path)
    (tmp_path / "analysis/value.bin").write_bytes(b"changed")

    with pytest.raises(ScienceContractError, match="artifact bytes"):
        candidate_binding(tmp_path)


def test_candidate_seal_rejects_unsafe_artifact_path(tmp_path: Path) -> None:
    _candidate(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../outside.bin"
    _write(tmp_path / "manifest.json", manifest)

    with pytest.raises(ScienceContractError, match="unsafe artifact path"):
        candidate_binding(tmp_path)


@pytest.mark.parametrize("relative", ["gate.json", "statistics.json"])
def test_candidate_seal_rejects_deleted_authoritative_file_after_reseal(
    tmp_path: Path,
    relative: str,
) -> None:
    _candidate(tmp_path)
    (tmp_path / relative).unlink()
    _seal(tmp_path)

    with pytest.raises(ScienceContractError, match="file inventory"):
        candidate_binding(tmp_path)


def test_candidate_seal_rejects_unexpected_file_after_reseal(tmp_path: Path) -> None:
    _candidate(tmp_path)
    _write(tmp_path / "unexpected.json", {"trusted": False})
    _seal(tmp_path)

    with pytest.raises(ScienceContractError, match="file inventory"):
        candidate_binding(tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_candidate_seal_rejects_inexact_checksum_lines(
    tmp_path: Path,
    mutation: str,
) -> None:
    _candidate(tmp_path)
    checksum_path = tmp_path / "checksums.txt"
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    if mutation == "missing":
        lines.pop()
    else:
        lines.append(f"{'0' * 64}  unexpected.json")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ScienceContractError, match="checksum inventory"):
        candidate_binding(tmp_path)


def test_candidate_seal_rejects_nested_checksum_inventory(tmp_path: Path) -> None:
    _candidate(tmp_path)
    nested = tmp_path / "nested/checksums.txt"
    nested.parent.mkdir()
    nested.write_text("not authoritative\n", encoding="utf-8")
    _seal(tmp_path)

    with pytest.raises(ScienceContractError, match="file inventory"):
        candidate_binding(tmp_path)


def test_candidate_seal_rejects_symlinked_files(tmp_path: Path) -> None:
    _candidate(tmp_path)
    gate = tmp_path / "gate.json"
    target = tmp_path / "gate-target.json"
    gate.replace(target)
    gate.symlink_to(target.name)
    _seal(tmp_path)

    with pytest.raises(ScienceContractError, match="symlink"):
        candidate_binding(tmp_path)
