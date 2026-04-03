"""Step 3: Compute binary exposure rasters (S03-04).

For each scenario/horizon combination, compares projected sea-level rise
against terrain elevation and classifies every coastal pixel as:
  1.0 = exposed  (SLR >= DEM)
  0.0 = not exposed (SLR < DEM)
  NaN = outside coastal analysis zone or DEM NoData

This is the core scientific computation of the pipeline (ADR-015).

Limitations (documented in methodology panel text):
  - Static inundation model only.
  - Does NOT account for flood defences, hydrodynamic connectivity,
    storm surge, tidal variation, local subsidence, or drainage.
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask as raster_mask
from shapely.geometry import mapping

logger = logging.getLogger(__name__)


def _load_coastal_zone(geojson_path: Path) -> list[dict]:
    """Load coastal analysis zone geometries as GeoJSON-like dicts."""
    gdf = gpd.read_file(geojson_path)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    return [mapping(geom) for geom in gdf.geometry]


def compute_binary_exposure(
    dem_tif: Path,
    slr_tif: Path,
    coastal_zone_geojson: Path,
    output_tif: Path,
) -> Path:
    """Compute a binary exposure raster.

    Args:
        dem_tif:  Mosaicked DEM GeoTIFF (terrain elevation in metres).
        slr_tif:  Aligned SLR GeoTIFF (projected rise in metres, on DEM grid).
        coastal_zone_geojson: GeoJSON of the coastal analysis zone (ADR-018).
        output_tif: Destination for the raw exposure raster.

    Returns:
        *output_tif* (convenience for chaining).
    """
    output_tif.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_tif) as dem_src, rasterio.open(slr_tif) as slr_src:
        dem_data = dem_src.read(1, masked=True)
        slr_data = slr_src.read(1, masked=True)
        profile = dem_src.profile.copy()

    # Binary comparison: exposed where SLR >= DEM (ADR-015)
    combined_mask = dem_data.mask | slr_data.mask
    exposure = np.where(
        combined_mask,
        np.nan,
        np.where(slr_data >= dem_data, 1.0, 0.0),
    ).astype(np.float32)

    profile.update(dtype="float32", nodata=np.nan, count=1, compress="deflate")

    # Write the full-extent exposure first, then mask to coastal zone.
    with rasterio.open(output_tif, "w", **profile) as dst:
        dst.write(exposure, 1)

    # Apply coastal analysis zone mask — pixels outside become NoData.
    geometries = _load_coastal_zone(coastal_zone_geojson)
    with rasterio.open(output_tif, "r+") as src:
        masked_data, masked_transform = raster_mask(
            src, geometries, crop=False, nodata=np.nan, filled=True
        )
        src.write(masked_data)

    # Log summary statistics.
    with rasterio.open(output_tif) as src:
        data = src.read(1)
        valid = data[~np.isnan(data)]
        exposed = int(np.sum(valid == 1.0))
        not_exposed = int(np.sum(valid == 0.0))
        nodata_count = int(np.sum(np.isnan(data)))

    logger.info(
        "Exposure raster -> %s: exposed=%d, not_exposed=%d, nodata=%d",
        output_tif.name, exposed, not_exposed, nodata_count,
    )

    return output_tif
