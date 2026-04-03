"""Shared test fixtures — small synthetic rasters and geometries.

All fixtures produce tiny (100x100 pixel) datasets so tests run in
milliseconds without downloading real data.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import box, mapping

# A small bounding box (roughly "mini-Europe" for testing).
TEST_BOUNDS = (4.0, 52.0, 5.0, 53.0)  # lon_min, lat_min, lon_max, lat_max
TEST_SHAPE = (100, 100)  # height, width


def _make_raster(path: Path, data: np.ndarray, nodata: float = np.nan) -> Path:
    """Write a single-band Float32 GeoTIFF."""
    h, w = data.shape
    transform = from_bounds(*TEST_BOUNDS, w, h)
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": w,
        "height": h,
        "count": 1,
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype(np.float32), 1)
    return path


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Shortcut for the pytest tmp directory."""
    return tmp_path


@pytest.fixture()
def dem_tif(tmp_path: Path) -> Path:
    """Synthetic DEM: elevation gradient from 10 m (north/top) to 0 m (south/bottom).

    In rasterio, row 0 = north.  The coastal zone fixture covers the
    southern half, which therefore has low elevations (0-5 m).
    With SLR = 2 m, the southernmost ~20% of the coastal zone is exposed.
    """
    rows = np.linspace(10.0, 0.0, TEST_SHAPE[0])
    data = np.tile(rows[:, np.newaxis], (1, TEST_SHAPE[1]))
    return _make_raster(tmp_path / "dem.tif", data)


@pytest.fixture()
def slr_tif(tmp_path: Path) -> Path:
    """Synthetic SLR: uniform 2.0 m rise across the whole grid.

    This means pixels with elevation <= 2.0 m are exposed.
    """
    data = np.full(TEST_SHAPE, 2.0, dtype=np.float32)
    return _make_raster(tmp_path / "slr_aligned.tif", data)


@pytest.fixture()
def coastal_zone_geojson(tmp_path: Path) -> Path:
    """GeoJSON polygon covering the lower-left quadrant of the test area.

    Only pixels inside this polygon should get 0/1 values;
    pixels outside should be NoData.
    """
    lon_min, lat_min, lon_max, lat_max = TEST_BOUNDS
    mid_lon = (lon_min + lon_max) / 2
    mid_lat = (lat_min + lat_max) / 2
    # Cover the bottom-left quadrant.
    geom = box(lon_min, lat_min, mid_lon, mid_lat)
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": mapping(geom),
            }
        ],
    }
    path = tmp_path / "coastal_zone.geojson"
    path.write_text(json.dumps(feature_collection))
    return path


@pytest.fixture()
def exposure_tif(tmp_path: Path, dem_tif: Path, slr_tif: Path, coastal_zone_geojson: Path) -> Path:
    """Pre-computed exposure raster (uses compute_binary_exposure)."""
    from pipeline.compute_exposure import compute_binary_exposure

    out = tmp_path / "exposure_raw.tif"
    compute_binary_exposure(dem_tif, slr_tif, coastal_zone_geojson, out)
    return out
