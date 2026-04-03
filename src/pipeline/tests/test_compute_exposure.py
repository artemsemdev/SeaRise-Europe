"""Tests for pipeline.compute_exposure — binary exposure logic."""

from pathlib import Path

import numpy as np
import rasterio

from pipeline.compute_exposure import compute_binary_exposure


def test_exposure_produces_binary_values(
    dem_tif: Path, slr_tif: Path, coastal_zone_geojson: Path, tmp_path: Path
):
    """Output should contain only 0.0, 1.0, and NaN."""
    out = tmp_path / "exposure.tif"
    compute_binary_exposure(dem_tif, slr_tif, coastal_zone_geojson, out)

    with rasterio.open(out) as src:
        data = src.read(1)

    valid = data[~np.isnan(data)]
    unique = set(np.unique(valid))
    assert unique.issubset({0.0, 1.0}), f"Non-binary values found: {unique}"


def test_low_elevation_is_exposed(
    dem_tif: Path, slr_tif: Path, coastal_zone_geojson: Path, tmp_path: Path
):
    """Pixels with elevation < SLR (2 m) inside the coastal zone should be 1."""
    out = tmp_path / "exposure.tif"
    compute_binary_exposure(dem_tif, slr_tif, coastal_zone_geojson, out)

    with rasterio.open(out) as src:
        data = src.read(1)

    valid = data[~np.isnan(data)]
    assert np.any(valid == 1.0), "Expected some exposed pixels"


def test_high_elevation_not_exposed(
    dem_tif: Path, slr_tif: Path, coastal_zone_geojson: Path, tmp_path: Path
):
    """Pixels with elevation >> SLR inside the coastal zone should be 0."""
    out = tmp_path / "exposure.tif"
    compute_binary_exposure(dem_tif, slr_tif, coastal_zone_geojson, out)

    with rasterio.open(out) as src:
        data = src.read(1)

    valid = data[~np.isnan(data)]
    assert np.any(valid == 0.0), "Expected some non-exposed pixels"


def test_outside_coastal_zone_is_nodata(
    dem_tif: Path, slr_tif: Path, coastal_zone_geojson: Path, tmp_path: Path
):
    """Pixels outside the coastal zone polygon should be NaN."""
    out = tmp_path / "exposure.tif"
    compute_binary_exposure(dem_tif, slr_tif, coastal_zone_geojson, out)

    with rasterio.open(out) as src:
        data = src.read(1)

    # The coastal zone covers only the bottom-left quadrant,
    # so at least some of the raster should be NaN.
    nan_count = int(np.sum(np.isnan(data)))
    total = data.size
    assert nan_count > 0, "Expected NoData pixels outside coastal zone"
    assert nan_count < total, "Entire raster is NoData — masking too aggressive"
