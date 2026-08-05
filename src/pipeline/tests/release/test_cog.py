"""Test deterministic and exact analysis COG output."""

from __future__ import annotations

from pathlib import Path

import rasterio

from searise_pipeline.release.cog import validate_analysis_cog, write_analysis_cog

from .test_source_fixture import contract, synthetic_source


def test_analysis_cog_is_byte_deterministic_and_exact(tmp_path: Path) -> None:
    layer = synthetic_source().layers[4]
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"

    first_evidence = write_analysis_cog(layer, first, contract=contract())
    second_evidence = write_analysis_cog(layer, second, contract=contract())
    validate_analysis_cog(first, layer, contract=contract())

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
    assert first_evidence.valid_cells == 3495
    assert first_evidence.nodata_cells == 1
    with rasterio.open(first) as dataset:
        assert dataset.tags(ns="IMAGE_STRUCTURE") == {
            "COMPRESSION": "DEFLATE",
            "INTERLEAVE": "PIXEL",
            "LAYOUT": "COG",
            "PREDICTOR": "2",
        }
        assert dataset.tags()["SCENARIO"] == layer.scenario
        assert dataset.tags()["HORIZON"] == str(layer.horizon)
