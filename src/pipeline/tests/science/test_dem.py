"""Tests for measured, identity-checked Copernicus DEM comparison."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from searise_pipeline.science import ScienceContractError, compare_dem_samples


def _write_sample(path: Path, shape: tuple[int, int], spacing: tuple[float, float]) -> None:
    values = np.arange(shape[0] * shape[1], dtype=np.float32).reshape(shape)
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=shape[1],
        height=shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(4, 53, spacing[0] / 3600, spacing[1] / 3600),
    ) as dataset:
        dataset.write(values, 1)
        dataset.update_tags(AREA_OR_POINT="Point")


def _identity(path: Path, shape: tuple[int, int], spacing: tuple[float, float]) -> dict[str, Any]:
    return {
        "sampleAsset": path.name,
        "sampleByteSize": path.stat().st_size,
        "sampleSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "sampleShape": list(shape),
        "latitudeSpacingArcSeconds": spacing[1],
        "sampleLongitudeSpacingArcSeconds": spacing[0],
    }


def test_dem_comparison_reports_size_resolution_and_difference(tmp_path: Path) -> None:
    glo30_path = tmp_path / "glo30.tif"
    glo90_path = tmp_path / "glo90.tif"
    _write_sample(glo30_path, (6, 6), (1.5, 1.0))
    _write_sample(glo90_path, (2, 2), (4.5, 3.0))
    terrain = {
        "verticalCrs": "EGM2008 (EPSG:3855)",
        "verticalUnits": "m",
        "instances": {
            "GLO-30": _identity(glo30_path, (6, 6), (1.5, 1.0)),
            "GLO-90": _identity(glo90_path, (2, 2), (4.5, 3.0)),
        },
    }

    report = compare_dem_samples(glo30_path, glo90_path, terrain)

    assert report["metrics"]["pixelCountRatioGlo30ToGlo90"] == 9
    assert report["metrics"]["validPixelCount"] == 4
    assert report["instances"]["GLO-30"]["pixelInterpretation"] == "Point"
    assert report["instances"]["GLO-90"]["maskedPixelCount"] == 0
    assert report["decision"]["status"] == "pending-scientific-review"


def test_dem_comparison_rejects_unpinned_bytes(tmp_path: Path) -> None:
    glo30_path = tmp_path / "glo30.tif"
    glo90_path = tmp_path / "glo90.tif"
    _write_sample(glo30_path, (6, 6), (1.5, 1.0))
    _write_sample(glo90_path, (2, 2), (4.5, 3.0))
    terrain = {
        "verticalCrs": "EGM2008 (EPSG:3855)",
        "verticalUnits": "m",
        "instances": {
            "GLO-30": _identity(glo30_path, (6, 6), (1.5, 1.0)),
            "GLO-90": _identity(glo90_path, (2, 2), (4.5, 3.0)),
        },
    }
    terrain["instances"]["GLO-90"]["sampleSha256"] = "0" * 64

    with pytest.raises(ScienceContractError, match="identity"):
        compare_dem_samples(glo30_path, glo90_path, terrain)
