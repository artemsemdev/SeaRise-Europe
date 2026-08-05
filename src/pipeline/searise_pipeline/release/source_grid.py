"""Deterministic source-node identity mapping for exact browser reports."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .model import RegionalReleaseSource


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceGridEvidence:
    """Identity of the non-value row/column to source-location mapping."""

    path: str
    byte_size: int
    sha256: str
    cell_count: int


def write_source_grid(
    source: RegionalReleaseSource,
    path: Path,
    *,
    contract: Mapping[str, Any],
) -> SourceGridEvidence:
    """Write all native-grid location IDs with the COG row transform declared."""
    grid = contract["grid"]
    document = {
        "schemaVersion": 1,
        "releaseContractId": contract["releaseContractId"],
        "sourceArchiveSha256": source.archive_sha256,
        "width": grid["width"],
        "height": grid["height"],
        "storageOrder": "south-to-north-row-major",
        "cogCellMapping": {
            "sourceRow": "height - 1 - cogRow",
            "sourceColumn": "cogColumn",
        },
        "locationIds": source.location_ids.ravel().tolist(),
    }
    encoded = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as stream:
            stream.write(encoded)
    os.replace(temporary_path, path)
    validate_source_grid(path, source, contract=contract)
    return SourceGridEvidence(
        path="analysis/source-grid.json.gz",
        byte_size=path.stat().st_size,
        sha256=_sha256(path),
        cell_count=source.location_ids.size,
    )


def validate_source_grid(
    path: Path,
    source: RegionalReleaseSource,
    *,
    contract: Mapping[str, Any],
) -> None:
    """Prove row/column-to-ID identity for every native grid cell."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read source-grid identity mapping: {exc}") from exc
    expected_header = {
        "schemaVersion": 1,
        "releaseContractId": contract["releaseContractId"],
        "sourceArchiveSha256": source.archive_sha256,
        "width": contract["grid"]["width"],
        "height": contract["grid"]["height"],
        "storageOrder": "south-to-north-row-major",
        "cogCellMapping": {
            "sourceRow": "height - 1 - cogRow",
            "sourceColumn": "cogColumn",
        },
    }
    if any(document.get(key) != value for key, value in expected_header.items()):
        raise ScienceContractError("Source-grid identity metadata differs from the contract")
    ids = np.asarray(document.get("locationIds"), dtype=np.int64)
    if not np.array_equal(ids, source.location_ids.ravel()):
        raise ScienceContractError("Source-grid identity mapping differs from all source cells")
