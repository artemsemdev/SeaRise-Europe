"""Tests for pipeline.validate — QA checks."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline.cogify import cogify
from pipeline.validate import ValidationError, validate_layer


def _make_cog(tmp_path: Path, exposure_tif: Path) -> Path:
    """Helper: convert the exposure fixture to a COG for validation."""
    cog = tmp_path / "valid.tif"
    cogify(exposure_tif, cog)
    return cog


def test_valid_layer_passes(exposure_tif: Path, tmp_path: Path):
    """A correctly produced COG should pass all 5 checks."""
    cog = _make_cog(tmp_path, exposure_tif)
    assert validate_layer(cog, "ssp2-45", 2050) is True


def test_wrong_crs_fails(tmp_path: Path):
    """A COG with the wrong CRS should fail check 2."""
    # Create a small raster in EPSG:3857 (Web Mercator).
    data = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    raw = tmp_path / "wrong_crs_raw.tif"
    transform = from_bounds(0, 0, 1000, 1000, 2, 2)
    with rasterio.open(
        raw, "w", driver="GTiff", dtype="float32",
        width=2, height=2, count=1, crs="EPSG:3857",
        transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(data, 1)

    cog = tmp_path / "wrong_crs.tif"
    cogify(raw, cog)

    with pytest.raises(ValidationError, match="crs"):
        validate_layer(cog, "ssp2-45", 2050)


def test_non_binary_values_fail(tmp_path: Path):
    """A COG with values other than 0/1 should fail check 3."""
    data = np.array([[0.5, 0.7], [1.0, 0.0]], dtype=np.float32)
    raw = tmp_path / "non_binary_raw.tif"
    transform = from_bounds(4.0, 52.0, 5.0, 53.0, 2, 2)
    with rasterio.open(
        raw, "w", driver="GTiff", dtype="float32",
        width=2, height=2, count=1, crs="EPSG:4326",
        transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(data, 1)

    cog = tmp_path / "non_binary.tif"
    cogify(raw, cog)

    with pytest.raises(ValidationError, match="binary_values"):
        validate_layer(cog, "ssp2-45", 2050)


def test_no_exposure_pixels_fail(tmp_path: Path):
    """A COG with only 0-valued pixels should fail check 4."""
    data = np.zeros((4, 4), dtype=np.float32)
    raw = tmp_path / "no_exposure_raw.tif"
    transform = from_bounds(4.0, 52.0, 5.0, 53.0, 4, 4)
    with rasterio.open(
        raw, "w", driver="GTiff", dtype="float32",
        width=4, height=4, count=1, crs="EPSG:4326",
        transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(data, 1)

    cog = tmp_path / "no_exposure.tif"
    cogify(raw, cog)

    with pytest.raises(ValidationError, match="has_exposure"):
        validate_layer(cog, "ssp2-45", 2050)
