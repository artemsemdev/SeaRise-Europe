"""Tests for pipeline.cogify — COG conversion."""

from pathlib import Path

import rasterio
from rio_cogeo.cogeo import cog_validate

from pipeline.cogify import cogify


def test_cogify_produces_valid_cog(exposure_tif: Path, tmp_path: Path):
    """Output should pass rio-cogeo validation."""
    cog = tmp_path / "output.tif"
    cogify(exposure_tif, cog)

    is_valid, errors, _ = cog_validate(str(cog))
    assert is_valid, f"COG validation errors: {errors}"


def test_cogify_preserves_crs(exposure_tif: Path, tmp_path: Path):
    """COG should keep EPSG:4326."""
    cog = tmp_path / "output.tif"
    cogify(exposure_tif, cog)

    with rasterio.open(cog) as src:
        assert src.crs.to_epsg() == 4326


def test_cogify_uses_deflate(exposure_tif: Path, tmp_path: Path):
    """COG should use deflate compression."""
    cog = tmp_path / "output.tif"
    cogify(exposure_tif, cog)

    with rasterio.open(cog) as src:
        assert src.compression == rasterio.enums.Compression.deflate


def test_cogify_has_tiled_layout(exposure_tif: Path, tmp_path: Path):
    """COG should have internal 256x256 tiles."""
    cog = tmp_path / "output.tif"
    cogify(exposure_tif, cog)

    with rasterio.open(cog) as src:
        assert src.profile["tiled"] is True
        assert src.profile["blockxsize"] == 256
        assert src.profile["blockysize"] == 256
