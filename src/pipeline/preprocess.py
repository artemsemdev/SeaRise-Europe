"""Step 2: Reproject and align SLR projections to the DEM grid (S03-03).

Interpolates coarse IPCC AR6 sea-level rise values (~0.25 deg) onto the
Copernicus DEM grid (~30 m) using bilinear resampling so that a pixel-level
comparison (SLR >= DEM) is meaningful.

Output: one Float32 GeoTIFF per scenario/horizon whose grid exactly matches
the DEM (same CRS, transform, and shape).
"""

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
import xarray as xr

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
    with xr.open_dataset(nc_path, engine="netcdf4") as ds:
        # Identify the sea-level variable — AR6 files use varying names.
        slr_var = None
        for candidate in ("sea_level_change", "slc", "sla", "total"):
            if candidate in ds.data_vars:
                slr_var = candidate
                break
        if slr_var is None:
            # Fall back to the first non-coordinate data variable.
            data_vars = list(ds.data_vars)
            if not data_vars:
                raise RuntimeError(
                    f"No data variables found in {nc_path}"
                )
            slr_var = data_vars[0]
            logger.warning(
                "Could not find expected SLR variable; using '%s'", slr_var
            )

        da = ds[slr_var]

        # Select the target year (nearest available).
        if "years" in da.dims:
            da = da.sel(years=horizon, method="nearest")
        elif "time" in da.dims:
            da = da.sel(time=horizon, method="nearest")

        # Select median quantile if the dimension exists.
        if "quantiles" in da.dims:
            da = da.sel(quantiles=0.5, method="nearest")
        elif "quantile" in da.dims:
            da = da.sel(quantile=0.5, method="nearest")

        # Resolve lat / lon coordinate names.
        lat_name = "lat" if "lat" in da.coords else "latitude"
        lon_name = "lon" if "lon" in da.coords else "longitude"

        lats = da.coords[lat_name].values
        lons = da.coords[lon_name].values

        slr_array = da.values.astype(np.float32)

    # Convert mm to metres if values look like millimetres.
    if np.nanmax(np.abs(slr_array)) > 50:
        logger.info("SLR values appear to be in mm — converting to metres.")
        slr_array = slr_array / 1000.0

    # Build a source transform from the coordinate arrays.
    lat_min, lat_max = float(lats.min()), float(lats.max())
    lon_min, lon_max = float(lons.min()), float(lons.max())
    height, width = slr_array.shape
    src_transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)
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
