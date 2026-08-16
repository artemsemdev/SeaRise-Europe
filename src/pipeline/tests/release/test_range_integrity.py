"""Test deterministic browser range-integrity indexes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from searise_pipeline.release import RangeObject, write_range_integrity_index
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09"
PAYLOAD_ROOT = REPO_ROOT / "contracts/release/v1/fixtures/release" / RELEASE_ID
COMMITTED_INDEX = (
    REPO_ROOT
    / "contracts/release/v2/fixtures/browser-release"
    / RELEASE_ID
    / "analysis/cog-range-integrity.json"
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity(path: Path, artifact_id: str) -> RangeObject:
    payload = path.read_bytes()
    return RangeObject(
        artifact_id=artifact_id,
        path=path.name,
        byte_size=len(payload),
        sha256=_sha256(payload),
    )


def test_range_integrity_is_deterministic_and_covers_every_byte(tmp_path: Path) -> None:
    first_source = tmp_path / "first.tif"
    second_source = tmp_path / "second.tif"
    first_source.write_bytes(b"a" * 65_537)
    second_source.write_bytes(b"b" * 7)
    objects = [_identity(second_source, "second"), _identity(first_source, "first")]

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    evidence = write_range_integrity_index(
        tmp_path,
        first,
        data_release_id="release",
        objects=objects,
    )
    write_range_integrity_index(
        tmp_path,
        second,
        data_release_id="release",
        objects=reversed(objects),
    )

    assert first.read_bytes() == second.read_bytes()
    assert evidence.object_count == 2
    assert evidence.chunk_count == 3
    document = json.loads(first.read_text(encoding="utf-8"))
    assert [record["artifactId"] for record in document["artifacts"]] == [
        "first",
        "second",
    ]
    assert document["artifacts"][0]["chunks"][-1]["endExclusive"] == 65_537


def test_range_integrity_rejects_identity_mismatch_and_duplicates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.tif"
    source.write_bytes(b"sealed")
    identity = _identity(source, "projection")

    with pytest.raises(ScienceContractError, match="differs"):
        write_range_integrity_index(
            tmp_path,
            tmp_path / "bad.json",
            data_release_id="release",
            objects=[RangeObject(**{**identity.__dict__, "sha256": "0" * 64})],
        )
    with pytest.raises(ScienceContractError, match="unique"):
        write_range_integrity_index(
            tmp_path,
            tmp_path / "duplicate.json",
            data_release_id="release",
            objects=[identity, identity],
        )


def test_committed_range_index_is_the_exact_production_writer_output(
    tmp_path: Path,
) -> None:
    manifest = json.loads((PAYLOAD_ROOT / "manifest.json").read_text(encoding="utf-8"))
    cogs = [
        RangeObject(
            artifact_id=item["artifactId"],
            path=item["path"],
            byte_size=item["byteSize"],
            sha256=item["sha256"],
        )
        for item in manifest["artifacts"]
        if item["role"] == "projection-analysis-cog"
    ]
    generated = tmp_path / "cog-range-integrity.json"
    write_range_integrity_index(
        PAYLOAD_ROOT,
        generated,
        data_release_id=RELEASE_ID,
        artifact_path="analysis/cog-range-integrity.json",
        objects=cogs,
    )

    assert COMMITTED_INDEX.read_bytes() == generated.read_bytes()
