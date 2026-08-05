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


def _candidate(root: Path) -> None:
    data = root / "analysis/value.bin"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"science")
    _write(
        root / "manifest.json",
        {
            "releaseId": "candidate-v1",
            "releaseContractId": "ar6-europe-regional-release-v1",
            "artifacts": [
                {
                    "path": "analysis/value.bin",
                    "byteSize": data.stat().st_size,
                    "sha256": _sha(data),
                }
            ],
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
    checksums = [
        f"{_sha(path)}  {path.relative_to(root).as_posix()}"
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]
    (root / "checksums.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")


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
