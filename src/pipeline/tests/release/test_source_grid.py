"""Test the exact COG-cell to AR6 source-location identity sidecar."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np

from searise_pipeline.release.source_grid import validate_source_grid, write_source_grid

from .test_source_fixture import contract, fixture_source


def test_source_grid_maps_every_cog_cell_to_its_source_id(tmp_path: Path) -> None:
    source = fixture_source()
    path = tmp_path / "source-grid.json.gz"
    evidence = write_source_grid(source, path, contract=contract())
    validate_source_grid(path, source, contract=contract())

    with gzip.open(path, "rt", encoding="utf-8") as stream:
        document = json.load(stream)
    ids = np.asarray(document["locationIds"], dtype=np.int64).reshape(46, 76)
    for cog_row in range(46):
        for cog_column in range(76):
            source_row = 46 - 1 - cog_row
            assert ids[source_row, cog_column] == source.location_ids[
                source_row, cog_column
            ]
    assert evidence.cell_count == 3496
