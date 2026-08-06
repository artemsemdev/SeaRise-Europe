"""Test deterministic and exact analysis COG output."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from searise_pipeline.release.cog import validate_analysis_cog, write_analysis_cog
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import contract, fixture_source


def _write_tampered_cog(layer, path: Path, tamper: str) -> None:
    release = contract()
    grid = release["grid"]
    values = release["values"]
    specification = release["artifacts"]["cog"]
    bands = np.stack(
        [
            np.flipud(layer.lower_mm),
            np.flipud(layer.central_mm),
            np.flipud(layer.upper_mm),
        ]
    ).copy()
    transform = from_origin(
        grid["bounds"][0],
        grid["bounds"][3],
        grid["nativeResolutionDegrees"],
        grid["nativeResolutionDegrees"],
    )
    nodata = values["nodata"]
    tags = {
        "BASELINE": values["baseline"],
        "HORIZON": str(layer.horizon),
        "NATIVE_RESOLUTION_DEGREES": str(grid["nativeResolutionDegrees"]),
        "SCALE_TO_METRES": str(values["scaleToMetres"]),
        "SCENARIO": layer.scenario,
        "SOURCE_ARCHIVE_SHA256": release["source"]["archiveSha256"],
        "SOURCE_MEMBER_SHA256": layer.member_sha256,
        "SOURCE_RELEASE": release["source"]["version"],
        "METHOD_VERSION": "ar6-regional-projection-v1",
        "CONFIDENCE": values["confidence"],
        "SCIENTIFIC_DISPOSITION": release["scientificDisposition"],
        "UNITS": values["storageUnits"],
    }
    if tamper == "transform":
        transform = from_origin(
            grid["bounds"][0] + grid["nativeResolutionDegrees"],
            grid["bounds"][3],
            grid["nativeResolutionDegrees"],
            grid["nativeResolutionDegrees"],
        )
    elif tamper == "tag":
        tags["SCENARIO"] = "ssp5-85"
    elif tamper == "nodata":
        nodata += 1
    elif tamper == "value":
        source_row, source_column = np.argwhere(layer.valid)[0]
        cog_row = grid["height"] - 1 - source_row
        bands[1, cog_row, source_column] += 1

    overview_resampling = specification["overviewResampling"]
    if tamper == "overview-resampling":
        overview_resampling = "AVERAGE"

    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=grid["width"],
        height=grid["height"],
        count=3,
        dtype="int16",
        crs=grid["crs"],
        transform=transform,
        nodata=nodata,
        blocksize=specification["blockSize"],
        compress=specification["compression"],
        predictor=specification["predictor"],
        overview_count=specification["overviewCount"],
        overview_resampling=overview_resampling,
    ) as dataset:
        dataset.write(bands)
        dataset.descriptions = tuple(specification["bands"])
        dataset.update_tags(**tags)


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


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("transform", "schema differs"),
        ("tag", "schema differs"),
        ("nodata", "schema differs"),
        ("value", "values differ"),
        ("overview-resampling", "overview values differ"),
    ],
)
def test_analysis_cog_rejects_semantic_tampering(tmp_path: Path, tamper: str, message: str) -> None:
    layer = fixture_source().layers[4]
    path = tmp_path / f"tampered-{tamper}.tif"
    _write_tampered_cog(layer, path, tamper)

    with pytest.raises(ScienceContractError, match=message):
        validate_analysis_cog(path, layer, contract=contract())
