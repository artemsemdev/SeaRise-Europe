"""Deterministic, range-only SHA-256 identity indexes for analysis COGs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from searise_pipeline.science.contracts import ScienceContractError

CHUNK_SIZE = 65_536


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class RangeObject:
    """One immutable object whose ranges must be independently verifiable."""

    artifact_id: str
    path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class RangeIntegrityEvidence:
    """Identity of one deterministic browser range-integrity index."""

    path: str
    byte_size: int
    sha256: str
    object_count: int
    chunk_count: int


def write_range_integrity_index(
    release_root: Path,
    output_path: Path,
    *,
    data_release_id: str,
    objects: Iterable[RangeObject],
    artifact_path: str | None = None,
) -> RangeIntegrityEvidence:
    """Seal fixed 64 KiB chunks without requiring a browser full-object hash."""
    records: list[dict[str, object]] = []
    chunk_count = 0
    ordered = sorted(objects, key=lambda item: item.artifact_id)
    if not ordered or len({item.artifact_id for item in ordered}) != len(ordered):
        raise ScienceContractError("Range integrity requires unique COG artifact IDs")
    for item in ordered:
        source = (release_root / item.path).resolve()
        if release_root.resolve() not in source.parents or not source.is_file():
            raise ScienceContractError("Range integrity source is missing or unsafe")
        if source.stat().st_size != item.byte_size or _sha256_file(source) != item.sha256:
            raise ScienceContractError("Range integrity source differs from its artifact identity")
        chunks: list[dict[str, object]] = []
        with source.open("rb") as stream:
            start = 0
            while payload := stream.read(CHUNK_SIZE):
                chunks.append(
                    {
                        "start": start,
                        "endExclusive": start + len(payload),
                        "sha256": _sha256_bytes(payload),
                    }
                )
                start += len(payload)
        chunk_count += len(chunks)
        records.append(
            {
                "artifactId": item.artifact_id,
                "path": item.path,
                "byteSize": item.byte_size,
                "sha256": item.sha256,
                "chunks": chunks,
            }
        )
    document = {
        "schemaVersion": 1,
        "dataReleaseId": data_release_id,
        "algorithm": "sha256",
        "chunkSize": CHUNK_SIZE,
        "artifacts": records,
    }
    encoded = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    evidence_path = (
        artifact_path
        if artifact_path is not None
        else output_path.relative_to(release_root).as_posix()
    )
    return RangeIntegrityEvidence(
        path=evidence_path,
        byte_size=len(encoded),
        sha256=_sha256_bytes(encoded),
        object_count=len(records),
        chunk_count=chunk_count,
    )
