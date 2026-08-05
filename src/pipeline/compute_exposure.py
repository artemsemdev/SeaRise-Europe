"""Disabled legacy relative-change exposure step.

The inputs to this function cannot express the baseline water surface, datum
transformation, uncertainty budget, or connectivity evidence required by the
accepted methodology. It therefore remains as an explicit migration stop and
cannot be enabled by a test or runtime flag.
"""

from pathlib import Path

from searise_pipeline.science import ScienceContractError


def compute_binary_exposure(
    dem_tif: Path,
    slr_tif: Path,
    coastal_zone_geojson: Path,
    output_tif: Path,
) -> Path:
    """Reject the superseded input contract before reading or writing bytes.

    Args:
        dem_tif:  Mosaicked DEM GeoTIFF (terrain elevation in metres).
        slr_tif:  Aligned SLR GeoTIFF (projected rise in metres, on DEM grid).
        coastal_zone_geojson: GeoJSON of the coastal analysis zone (ADR-018).
        output_tif: Former destination for the raw exposure raster.
    """
    raise ScienceContractError(
        "Legacy exposure inputs are prohibited: relative sea-level change cannot "
        "be classified against absolute terrain. Use the uncertainty-aware "
        "vertical reconciliation pipeline."
    )
