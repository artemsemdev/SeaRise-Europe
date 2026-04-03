"""Step 1: Download and cache source data (S03-02).

Downloads IPCC AR6 sea-level projection NetCDF files and Copernicus DEM
GeoTIFF tiles, caching locally to avoid repeated network requests.

Data sources:
  - IPCC AR6: NASA Sea Level Change Team (CC BY 4.0)
    https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool
  - Copernicus DEM GLO-30: Copernicus / DLR via AWS Open Data
    https://registry.opendata.aws/copernicus-dem/
"""

from __future__ import annotations

import logging
import shutil
import urllib.request
from pathlib import Path

import rasterio
import xarray as xr
from rasterio.merge import merge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IPCC AR6 sea-level projections
# ---------------------------------------------------------------------------
# The IPCC AR6 sea-level projection data is published by the NASA Sea Level
# Change Team.  Gridded NetCDF files contain total projected sea-level change
# (median and confidence intervals) per scenario across a lat/lon grid.
#
# The canonical data repository is:
#   https://zenodo.org/records/6382554  (Garner et al., 2021)
#
# Each file covers one SSP scenario with dimensions:
#   years  - projection years (2020-2150)
#   quantiles - confidence levels (0.05, 0.17, 0.5, 0.83, 0.95)
#   locations - tide-gauge / grid-point index
# plus lat/lon coordinate variables.
# ---------------------------------------------------------------------------

IPCC_AR6_BASE_URL = (
    "https://zenodo.org/records/6382554/files"
)

SCENARIO_FILE_MAP: dict[str, str] = {
    "ssp1-26": "total_ssp126_medium_confidence_values.nc",
    "ssp2-45": "total_ssp245_medium_confidence_values.nc",
    "ssp5-85": "total_ssp585_medium_confidence_values.nc",
}

# ---------------------------------------------------------------------------
# Copernicus DEM GLO-30 (AWS Open Data mirror)
# ---------------------------------------------------------------------------
# Tiles are 1-degree x 1-degree COGs named by their SW corner coordinate.
# https://copernicus-dem-30m.s3.amazonaws.com/
# ---------------------------------------------------------------------------

COPERNICUS_DEM_BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"


def download_ipcc_ar6(scenario: str, horizon: int, output_dir: Path) -> Path:
    """Download IPCC AR6 SLR projection NetCDF for *scenario*.

    The file is shared across horizons (the NetCDF contains all years), so
    *horizon* is accepted for interface consistency but does not affect which
    file is downloaded.

    Returns the path to the cached NetCDF file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = SCENARIO_FILE_MAP.get(scenario)
    if filename is None:
        raise ValueError(
            f"Unknown scenario '{scenario}'. "
            f"Expected one of: {list(SCENARIO_FILE_MAP)}"
        )

    output_path = output_dir / filename
    if output_path.exists():
        logger.info("Cached (skip download): %s", output_path)
        return output_path

    url = f"{IPCC_AR6_BASE_URL}/{filename}"
    logger.info("Downloading IPCC AR6 data: %s", url)

    tmp_path = output_path.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(url, tmp_path)
        shutil.move(str(tmp_path), str(output_path))
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to download IPCC AR6 data from {url} — {exc}"
        ) from exc

    # Verify the file is readable by xarray
    try:
        with xr.open_dataset(output_path, engine="netcdf4") as ds:
            logger.info(
                "Verified %s: variables=%s, dims=%s",
                filename,
                list(ds.data_vars),
                dict(ds.dims),
            )
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded file is not a valid NetCDF: {exc}"
        ) from exc

    return output_path


# ---------------------------------------------------------------------------
# Copernicus DEM helpers
# ---------------------------------------------------------------------------

def _dem_tile_id(lat: int, lon: int) -> str:
    """Copernicus DEM tile identifier from the SW-corner coordinate."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_DEM"


def _dem_tile_url(tile_id: str) -> str:
    return f"{COPERNICUS_DEM_BASE_URL}/{tile_id}/{tile_id}.tif"


def download_copernicus_dem(
    bbox: tuple[float, float, float, float],
    output_dir: Path,
) -> Path:
    """Download Copernicus DEM GLO-30 tiles for *bbox* and mosaic them.

    Args:
        bbox: (lon_min, lat_min, lon_max, lat_max) in EPSG:4326.
        output_dir: Directory for tiles and the mosaicked output.

    Returns:
        Path to the mosaicked DEM GeoTIFF.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    mosaic_path = output_dir / "europe_dem_30m.tif"

    if mosaic_path.exists():
        logger.info("Cached (skip download): %s", mosaic_path)
        return mosaic_path

    lon_min, lat_min, lon_max, lat_max = bbox
    tiles_dir = output_dir / "dem_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    tile_paths: list[Path] = []
    downloaded = 0
    cached = 0
    unavailable = 0

    lat_start, lat_end = int(lat_min), int(lat_max)
    lon_start, lon_end = int(lon_min), int(lon_max)
    total = (lat_end - lat_start) * (lon_end - lon_start)
    logger.info(
        "DEM tile grid: lat [%d, %d), lon [%d, %d) — %d tiles",
        lat_start, lat_end, lon_start, lon_end, total,
    )

    for lat in range(lat_start, lat_end):
        for lon in range(lon_start, lon_end):
            tile_id = _dem_tile_id(lat, lon)
            tile_path = tiles_dir / f"{tile_id}.tif"

            if tile_path.exists():
                tile_paths.append(tile_path)
                cached += 1
                continue

            url = _dem_tile_url(tile_id)
            try:
                urllib.request.urlretrieve(url, tile_path)
                tile_paths.append(tile_path)
                downloaded += 1
            except Exception:
                # Tiles over open ocean do not exist — expected.
                unavailable += 1

    logger.info(
        "DEM tiles: %d downloaded, %d cached, %d unavailable (ocean)",
        downloaded, cached, unavailable,
    )

    if not tile_paths:
        raise RuntimeError(
            "No DEM tiles downloaded — check bounding box and network."
        )

    # Mosaic all tiles into a single GeoTIFF
    logger.info("Mosaicking %d DEM tiles into %s ...", len(tile_paths), mosaic_path)
    datasets = [rasterio.open(p) for p in tile_paths]
    try:
        mosaic_array, mosaic_transform = merge(datasets)
        profile = datasets[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=mosaic_array.shape[1],
            width=mosaic_array.shape[2],
            transform=mosaic_transform,
            compress="deflate",
        )
        with rasterio.open(mosaic_path, "w", **profile) as dst:
            dst.write(mosaic_array)
    finally:
        for ds in datasets:
            ds.close()

    # Quick sanity check
    with rasterio.open(mosaic_path) as src:
        logger.info(
            "Mosaic complete: CRS=%s, shape=%s, bounds=%s",
            src.crs, src.shape, src.bounds,
        )

    return mosaic_path
