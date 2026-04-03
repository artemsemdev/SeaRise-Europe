"""Tests for pipeline.preprocess — SLR alignment to DEM grid."""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from pipeline.preprocess import align_to_dem_grid


def _make_slr_nc(tmp_path: Path) -> Path:
    """Create a minimal SLR raster (standing in for the NetCDF)."""
    # We create a GeoTIFF that mimics the output of _extract_slr_grid
    # to test the alignment step in isolation.
    data = np.full((10, 10), 2.0, dtype=np.float32)
    path = tmp_path / "slr_source.tif"
    transform = from_bounds(4.0, 52.0, 5.0, 53.0, 10, 10)
    with rasterio.open(
        path, "w", driver="GTiff", dtype="float32",
        width=10, height=10, count=1, crs="EPSG:4326",
        transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
    return path


def test_align_preserves_crs(dem_tif: Path, tmp_path: Path):
    """Aligned output should keep the DEM CRS (EPSG:4326)."""
    slr_nc = _make_slr_nc(tmp_path)
    out = tmp_path / "aligned.tif"

    # Patch _extract_slr_grid to return a simple array
    import pipeline.preprocess as pp
    original = pp._extract_slr_grid

    def fake_extract(nc_path, scenario, horizon):
        data = np.full((10, 10), 2.0, dtype=np.float32)
        transform = from_bounds(4.0, 52.0, 5.0, 53.0, 10, 10)
        crs = rasterio.crs.CRS.from_epsg(4326)
        return data, crs, transform

    pp._extract_slr_grid = fake_extract
    try:
        align_to_dem_grid(slr_nc, dem_tif, "ssp2-45", 2050, out)
    finally:
        pp._extract_slr_grid = original

    with rasterio.open(out) as src:
        assert src.crs.to_epsg() == 4326


def test_align_matches_dem_shape(dem_tif: Path, tmp_path: Path):
    """Aligned output should match the DEM's spatial dimensions."""
    slr_nc = _make_slr_nc(tmp_path)
    out = tmp_path / "aligned.tif"

    import pipeline.preprocess as pp
    original = pp._extract_slr_grid

    def fake_extract(nc_path, scenario, horizon):
        data = np.full((10, 10), 2.0, dtype=np.float32)
        transform = from_bounds(4.0, 52.0, 5.0, 53.0, 10, 10)
        crs = rasterio.crs.CRS.from_epsg(4326)
        return data, crs, transform

    pp._extract_slr_grid = fake_extract
    try:
        align_to_dem_grid(slr_nc, dem_tif, "ssp2-45", 2050, out)
    finally:
        pp._extract_slr_grid = original

    with rasterio.open(dem_tif) as dem, rasterio.open(out) as aligned:
        assert aligned.shape == dem.shape
