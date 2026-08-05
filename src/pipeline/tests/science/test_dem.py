"""Tests for measured, identity-checked Copernicus DEM comparison."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from searise_pipeline.science import (
    ScienceContractError,
    compare_dem_samples,
    compare_dem_windows,
    inspect_dem_window,
)


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


def _write_layer(
    path: Path,
    values: np.ndarray,
    spacing: tuple[float, float],
) -> None:
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=str(values.dtype),
        crs="EPSG:4326",
        transform=from_origin(4, 53, spacing[0] / 3600, spacing[1] / 3600),
    ) as dataset:
        dataset.write(values, 1)
        dataset.update_tags(AREA_OR_POINT="Point")


def _write_window(
    root: Path,
    prefix: str,
    shape: tuple[int, int],
    spacing: tuple[float, float],
) -> dict[str, Path]:
    paths = {name: root / f"{prefix}-{name}.tif" for name in ("DEM", "EDM", "FLM", "HEM", "WBM")}
    elevation = np.arange(shape[0] * shape[1], dtype=np.float32).reshape(shape) - 2
    _write_layer(paths["DEM"], elevation, spacing)
    _write_layer(paths["EDM"], np.ones(shape, dtype=np.uint8), spacing)
    _write_layer(paths["FLM"], np.full(shape, 2, dtype=np.uint8), spacing)
    _write_layer(paths["HEM"], np.full(shape, 1.5, dtype=np.float32), spacing)
    water = np.zeros(shape, dtype=np.uint8)
    water[:, 0] = 1
    _write_layer(paths["WBM"], water, spacing)
    return paths


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


def test_quality_aware_window_requires_and_reports_every_auxiliary_layer(
    tmp_path: Path,
) -> None:
    paths = _write_window(tmp_path, "glo30", (6, 6), (1, 1))

    report = inspect_dem_window(paths)

    assert set(report["assets"]) == {"DEM", "EDM", "FLM", "HEM", "WBM"}
    assert report["quality"]["waterBodyMaskCounts"] == {"0": 30, "1": 6}
    assert report["quality"]["heightError"]["p95SigmaMetres"] == 1.5
    assert report["quality"]["uneditedUnfilledLandPixelCount"] == 30
    assert report["delivery"]["losslessLandElevationClass2mGeoTiffBytes"] > 0

    with pytest.raises(ScienceContractError, match="missing required layers"):
        inspect_dem_window({name: path for name, path in paths.items() if name != "HEM"})


def test_quality_aware_window_rejects_unknown_mask_codes(tmp_path: Path) -> None:
    paths = _write_window(tmp_path, "glo30", (6, 6), (1, 1))
    _write_layer(paths["WBM"], np.full((6, 6), 255, dtype=np.uint8), (1, 1))

    with pytest.raises(ScienceContractError, match="Unexpected WBM quality codes"):
        inspect_dem_window(paths)


def test_quality_aware_comparison_measures_resolution_loss(tmp_path: Path) -> None:
    glo30 = _write_window(tmp_path, "glo30", (6, 6), (1, 1))
    glo90 = _write_window(tmp_path, "glo90", (2, 2), (3, 3))

    report = compare_dem_windows(glo30, glo90)

    assert report["GLO-30"]["grid"]["pixelCount"] == 36
    assert report["GLO-90"]["grid"]["pixelCount"] == 4
    assert report["comparison"]["validCommonLandPixelCount"] > 0
    assert set(report["comparison"]["thresholdClassDisagreement"]) == {"0", "1", "2", "5"}
