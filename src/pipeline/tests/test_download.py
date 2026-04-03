"""Tests for pipeline.download — data retrieval and caching."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.download import (
    SCENARIO_FILE_MAP,
    _dem_tile_id,
    download_ipcc_ar6,
)


def test_scenario_file_map_covers_all_scenarios():
    """The file map should include entries for all 3 ADR-016 scenarios."""
    assert "ssp1-26" in SCENARIO_FILE_MAP
    assert "ssp2-45" in SCENARIO_FILE_MAP
    assert "ssp5-85" in SCENARIO_FILE_MAP


def test_unknown_scenario_raises():
    """Requesting an unknown scenario should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown scenario"):
        download_ipcc_ar6("ssp-invalid", 2050, Path("/tmp"))


def test_dem_tile_id_north_east():
    assert _dem_tile_id(52, 4) == "Copernicus_DSM_COG_10_N52_00_E004_DEM"


def test_dem_tile_id_south_west():
    assert _dem_tile_id(-10, -20) == "Copernicus_DSM_COG_10_S10_00_W020_DEM"


def test_cached_file_skips_download(tmp_path: Path):
    """If the file already exists, download_ipcc_ar6 should return it without downloading."""
    filename = SCENARIO_FILE_MAP["ssp2-45"]
    cached = tmp_path / filename
    cached.write_bytes(b"fake-netcdf")

    with patch("pipeline.download.urllib.request.urlretrieve") as mock_dl:
        # Will fail on xarray open, but we test caching path
        result = download_ipcc_ar6("ssp2-45", 2050, tmp_path)
        mock_dl.assert_not_called()
        assert result == cached
