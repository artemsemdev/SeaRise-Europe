"""Test the exact COG-cell to AR6 source-location identity sidecar."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.release.source_grid import validate_source_grid, write_source_grid
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import contract, fixture_source

REPO_ROOT = Path(__file__).parents[4]
COMMITTED_BROWSER_GRID = (
    REPO_ROOT
    / "contracts/release/v2/fixtures/browser-release"
    / "searise-europe-v1.0.0-20260810-c096aeab4e09"
    / "analysis/source-grid.json.gz"
)


def _read_document(path: Path) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _write_document(path: Path, document: dict[str, object]) -> None:
    encoded = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            stream.write(encoded)


def test_source_grid_maps_every_cog_cell_to_its_source_id(tmp_path: Path) -> None:
    source = fixture_source()
    path = tmp_path / "source-grid.json.gz"
    evidence = write_source_grid(source, path, contract=contract())
    validate_source_grid(path, source, contract=contract())

    document = _read_document(path)
    ids = np.asarray(document["locationIds"], dtype=np.int64).reshape(46, 76)
    for cog_row in range(46):
        for cog_column in range(76):
            source_row = 46 - 1 - cog_row
            assert ids[source_row, cog_column] == source.location_ids[source_row, cog_column]
    assert evidence.cell_count == 3496


def test_committed_browser_grid_is_the_exact_authoritative_writer_output(
    tmp_path: Path,
) -> None:
    source = fixture_source()
    generated = tmp_path / "source-grid.json.gz"
    write_source_grid(source, generated, contract=contract())

    assert COMMITTED_BROWSER_GRID.read_bytes() == generated.read_bytes()
    emitted = _read_document(COMMITTED_BROWSER_GRID)["locationIds"]
    assert emitted == source.location_ids.ravel().tolist()


@pytest.mark.parametrize("tamper", ["string", "float", "boolean", "swapped"])
def test_source_grid_rejects_non_exact_location_ids(tmp_path: Path, tamper: str) -> None:
    source = fixture_source()
    path = tmp_path / f"source-grid-{tamper}.json.gz"
    write_source_grid(source, path, contract=contract())
    document = _read_document(path)
    ids = document["locationIds"]
    assert isinstance(ids, list)
    if tamper == "string":
        ids[0] = str(ids[0])
    elif tamper == "float":
        ids[0] = float(ids[0])
    elif tamper == "boolean":
        ids[0] = True
    else:
        other = next(index for index, value in enumerate(ids) if value != ids[0])
        ids[0], ids[other] = ids[other], ids[0]
    _write_document(path, document)

    message = "exact integer list" if tamper != "swapped" else "differs"
    with pytest.raises(ScienceContractError, match=message):
        validate_source_grid(path, source, contract=contract())


@pytest.mark.parametrize(
    "tamper",
    [
        "missing-mapping",
        "malformed-mapping",
        "extra-key",
        "boolean-schema-version",
        "float-width",
        "float-height",
    ],
)
def test_source_grid_rejects_mapping_header_tampering(tmp_path: Path, tamper: str) -> None:
    source = fixture_source()
    path = tmp_path / f"source-grid-{tamper}.json.gz"
    write_source_grid(source, path, contract=contract())
    document = _read_document(path)
    if tamper == "missing-mapping":
        document.pop("cogCellMapping")
    elif tamper == "malformed-mapping":
        document["cogCellMapping"] = {"sourceRow": "cogRow"}
    elif tamper == "extra-key":
        document["unexpected"] = "not-canonical"
    elif tamper == "boolean-schema-version":
        document["schemaVersion"] = True
    elif tamper == "float-width":
        document["width"] = 76.0
    else:
        document["height"] = 46.0
    _write_document(path, document)

    with pytest.raises(ScienceContractError, match="metadata differs"):
        validate_source_grid(path, source, contract=contract())
