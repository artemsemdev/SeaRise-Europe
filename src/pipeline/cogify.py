"""Step 4: Convert exposure rasters to Cloud-Optimized GeoTIFF (S03-05).

COG properties (architecture doc section 8):
  - CRS:         EPSG:4326
  - Pixel type:  Float32 (0.0, 1.0, NaN)
  - Compression: deflate
  - Tile size:   256 x 256
  - Overviews:   nearest resampling (correct for binary data)
  - Levels:      2, 4, 8, 16, 32, 64, 128
"""

import logging
from pathlib import Path

from rio_cogeo.cogeo import cog_translate, cog_validate
from rio_cogeo.profiles import cog_profiles

from .config import COG_COMPRESSION, COG_OVERVIEW_LEVELS, COG_TILE_SIZE

logger = logging.getLogger(__name__)


def cogify(input_tif: Path, output_cog: Path) -> Path:
    """Convert a GeoTIFF to Cloud-Optimized GeoTIFF.

    Returns:
        *output_cog* (convenience for chaining).
    """
    output_cog.parent.mkdir(parents=True, exist_ok=True)

    profile = cog_profiles.get(COG_COMPRESSION)
    profile.update(
        blockxsize=COG_TILE_SIZE,
        blockysize=COG_TILE_SIZE,
    )

    config = {"GDAL_TIFF_INTERNAL_MASK": True}

    cog_translate(
        str(input_tif),
        str(output_cog),
        profile,
        in_memory=False,
        overview_level=COG_OVERVIEW_LEVELS,
        overview_resampling="nearest",
        config=config,
    )

    # Validate the output.
    is_valid, errors, warnings = cog_validate(str(output_cog))
    if not is_valid:
        raise RuntimeError(
            f"COG validation failed for {output_cog}: {errors}"
        )

    if warnings:
        logger.warning("COG warnings for %s: %s", output_cog.name, warnings)

    logger.info("COGified: %s -> %s (valid)", input_tif.name, output_cog.name)
    return output_cog
