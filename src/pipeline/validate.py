"""Step 5: QA validation for COG layers (S03-05).

Five checks — all must pass before a layer is marked valid:
  1. Valid COG structure  (rio-cogeo validate)
  2. CRS is EPSG:4326
  3. Pixel values are binary (0, 1, NoData only)
  4. At least some exposure pixels exist (value == 1)
  5. Spatial extent is within Europe bounds
"""

import logging
from pathlib import Path

import numpy as np
import rasterio
from rio_cogeo.cogeo import cog_validate

from .config import EUROPE_BBOX

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when a QA check fails."""

    def __init__(self, check_name: str, detail: str) -> None:
        self.check_name = check_name
        super().__init__(f"QA check '{check_name}' failed: {detail}")


def validate_layer(cog_path: Path, scenario: str, horizon: int) -> bool:
    """Run all 5 QA checks on a COG layer.

    Raises ``ValidationError`` on the first failing check.
    Returns ``True`` if all checks pass.
    """
    label = f"{scenario}/{horizon}"

    # -- Check 1: Valid COG structure ----------------------------------------
    is_valid, errors, _ = cog_validate(str(cog_path))
    if not is_valid:
        raise ValidationError("cog_structure", f"{label}: {errors}")
    logger.info("[%s] Check 1/5 passed: valid COG structure", label)

    with rasterio.open(cog_path) as src:
        # -- Check 2: CRS is EPSG:4326 --------------------------------------
        epsg = src.crs.to_epsg()
        if epsg != 4326:
            raise ValidationError(
                "crs", f"{label}: expected EPSG:4326, got EPSG:{epsg}"
            )
        logger.info("[%s] Check 2/5 passed: CRS is EPSG:4326", label)

        # -- Check 3: Binary pixel values ------------------------------------
        data = src.read(1, masked=True)
        valid_pixels = data.compressed()
        unique_floats = np.unique(valid_pixels)
        unique_values = set(unique_floats.tolist())
        if not unique_values.issubset({0.0, 1.0}):
            raise ValidationError(
                "binary_values",
                f"{label}: non-binary pixel values found: {unique_values}",
            )
        logger.info("[%s] Check 3/5 passed: pixel values are binary", label)

        # -- Check 4: Has exposure pixels ------------------------------------
        exposure_count = int(np.sum(valid_pixels == 1))
        if exposure_count == 0:
            raise ValidationError(
                "has_exposure",
                f"{label}: no exposure pixels (value == 1) found",
            )
        logger.info(
            "[%s] Check 4/5 passed: %d exposure pixels", label, exposure_count
        )

        # -- Check 5: Spatial extent within Europe ---------------------------
        b = src.bounds
        lon_min, lat_min, lon_max, lat_max = EUROPE_BBOX
        if b.left < lon_min or b.right > lon_max:
            raise ValidationError(
                "extent",
                f"{label}: longitude [{b.left}, {b.right}] outside "
                f"[{lon_min}, {lon_max}]",
            )
        if b.bottom < lat_min or b.top > lat_max:
            raise ValidationError(
                "extent",
                f"{label}: latitude [{b.bottom}, {b.top}] outside "
                f"[{lat_min}, {lat_max}]",
            )
        logger.info("[%s] Check 5/5 passed: extent within Europe", label)

    logger.info("[%s] All 5 QA checks passed", label)
    return True
