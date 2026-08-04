"""Legacy pipeline step: reproject and align assumed SLR data to a DEM grid.

The regular ~0.25 degree source-grid assumption below is not validated against
the pinned real AR6 release. ADR-021 Phase 0 must confirm or replace it before
publication.

Interpolates coarse IPCC AR6 sea-level rise values (~0.25 deg) onto the
Copernicus DEM grid (~30 m) using bilinear resampling so that a pixel-level
comparison (SLR >= DEM) is meaningful.

Output: one Float32 GeoTIFF per scenario/horizon whose grid exactly matches
the DEM (same CRS, transform, and shape).
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import xarray as xr
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from searise_pipeline.science import extract_projection_grid, load_science_contracts

logger = logging.getLogger(__name__)


def _extract_slr_grid(
    nc_path: Path,
    scenario: str,
    horizon: int,
) -> tuple[np.ndarray, rasterio.crs.CRS, rasterio.transform.Affine]:
    """Read median SLR values from an IPCC AR6 NetCDF and return as a 2-D array.

    Returns:
        (slr_array, source_crs, source_transform)
        slr_array is shaped (lat, lon) with Float32 values in metres.
    """
    contracts = load_science_contracts()
    projection = contracts.source_semantics["projection"]
    with xr.open_dataset(nc_path, engine="netcdf4") as dataset:
        native_grid = extract_projection_grid(dataset, projection, scenario, horizon)

    # Raster rows run north-to-south; native coordinates are sorted ascending.
    slr_array: np.ndarray[Any, np.dtype[np.float32]] = native_grid.values_m[
        ::-1, :
    ].astype(np.float32)
    src_transform = from_origin(
        float(native_grid.longitudes[0]) - 0.5,
        float(native_grid.latitudes[-1]) + 0.5,
        1.0,
        1.0,
    )
    src_crs = rasterio.crs.CRS.from_epsg(4326)

    logger.info(
        "Extracted SLR grid for %s/%d: shape=%s, range=[%.4f, %.4f] m",
        scenario, horizon, slr_array.shape,
        float(np.nanmin(slr_array)), float(np.nanmax(slr_array)),
    )

    return slr_array, src_crs, src_transform


def align_to_dem_grid(
    slr_nc: Path,
    dem_tif: Path,
    scenario: str,
    horizon: int,
    output_tif: Path,
) -> Path:
    """Reproject SLR projection onto the DEM grid using bilinear resampling.

    Args:
        slr_nc:     Path to the IPCC AR6 NetCDF file for *scenario*.
        dem_tif:    Path to the mosaicked DEM GeoTIFF.
        scenario:   Scenario identifier (e.g. ``"ssp2-45"``).
        horizon:    Projection year (e.g. ``2050``).
        output_tif: Destination for the aligned SLR GeoTIFF.

    Returns:
        *output_tif* (convenience for chaining).
    """
    output_tif.parent.mkdir(parents=True, exist_ok=True)

    slr_array, src_crs, src_transform = _extract_slr_grid(
        slr_nc, scenario, horizon
    )

    with rasterio.open(dem_tif) as dem:
        dst_crs = dem.crs
        dst_transform = dem.transform
        dst_shape = (dem.height, dem.width)

    aligned = np.empty(dst_shape, dtype=np.float32)

    reproject(
        source=slr_array,
        destination=aligned,
        src_crs=src_crs,
        src_transform=src_transform,
        dst_crs=dst_crs,
        dst_transform=dst_transform,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": dst_shape[1],
        "height": dst_shape[0],
        "count": 1,
        "crs": dst_crs,
        "transform": dst_transform,
        "nodata": np.nan,
        "compress": "deflate",
    }

    with rasterio.open(output_tif, "w", **profile) as dst:
        dst.write(aligned, 1)

    logger.info(
        "Aligned SLR for %s/%d: shape=%s, range=[%.4f, %.4f] m -> %s",
        scenario, horizon, dst_shape,
        float(np.nanmin(aligned)), float(np.nanmax(aligned)),
        output_tif,
    )

    return output_tif
