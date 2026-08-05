"""Test deterministic and exact analysis COG output."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import rasterio

from searise_pipeline.release.cog import validate_analysis_cog, write_analysis_cog
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import contract, fixture_source


def test_analysis_cog_is_byte_deterministic_and_exact(tmp_path: Path) -> None:
    layer = fixture_source().layers[4]
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"

    first_evidence = write_analysis_cog(layer, first, contract=contract())
    second_evidence = write_analysis_cog(layer, second, contract=contract())
    validate_analysis_cog(first, layer, contract=contract())

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
    assert first_evidence.valid_cells == 3054
    assert first_evidence.nodata_cells == 442
    with rasterio.open(first) as dataset:
        assert dataset.tags(ns="IMAGE_STRUCTURE") == {
            "COMPRESSION": "DEFLATE",
            "INTERLEAVE": "PIXEL",
            "LAYOUT": "COG",
            "PREDICTOR": "2",
        }
        assert dataset.tags()["SCENARIO"] == layer.scenario
        assert dataset.tags()["HORIZON"] == str(layer.horizon)
        assert dataset.tags()["SOURCE_MEMBER_SHA256"] == layer.member_sha256
        assert dataset.tags()["METHOD_VERSION"] == "ar6-regional-projection-v1"
        assert dataset.overviews(1) == [2, 4, 8, 19, 38]


def test_analysis_cog_rejects_an_all_nodata_layer(tmp_path: Path) -> None:
    layer = fixture_source().layers[0]
    nodata = np.full(layer.lower_mm.shape, -32768, dtype=np.int16)
    empty = replace(layer, lower_mm=nodata, central_mm=nodata, upper_mm=nodata)

    with pytest.raises(ScienceContractError, match="entirely nodata"):
        write_analysis_cog(empty, tmp_path / "empty.tif", contract=contract())
