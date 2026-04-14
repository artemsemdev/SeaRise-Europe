"""Pipeline configuration constants and environment variable helpers."""

from __future__ import annotations

import os
from pathlib import Path

# -- Geography (ADR-018) -----------------------------------------------------

EUROPE_BBOX = (-30.0, 30.0, 40.0, 75.0)  # (lon_min, lat_min, lon_max, lat_max)

# -- Scenarios and horizons (ADR-016, ADR-017, FR-015) -----------------------

SCENARIOS = ["ssp1-26", "ssp2-45", "ssp5-85"]
HORIZONS = [2030, 2050, 2100]
DEFAULT_METHODOLOGY_VERSION = "v1.0"

# -- COG profile (architecture doc section 8) --------------------------------

COG_TILE_SIZE = 256
COG_OVERVIEW_LEVELS = [2, 4, 8, 16, 32, 64, 128]
COG_COMPRESSION = "deflate"

# -- Legend colormap (architecture doc section 10) ---------------------------

LEGEND_COLORMAP = {
    "colorStops": [
        {"value": 1, "color": "#E85D04", "label": "Modeled exposure zone"}
    ]
}

# -- Blob storage layout (architecture doc section 9) -----------------------

BLOB_CONTAINER = "geospatial"


# -- Environment helpers -----------------------------------------------------

def get_env(name: str, default: str | None = None) -> str:
    """Return an environment variable or raise if missing and no default."""
    value = os.environ.get(name, default)
    if value is None:
        raise EnvironmentError(
            f"Required environment variable {name} is not set. "
            "See .env.pipeline.example for documentation."
        )
    return value


def get_download_dir() -> Path:
    return Path(get_env("DOWNLOAD_DIR", "data/raw"))


def get_work_dir() -> Path:
    return Path(get_env("WORK_DIR", "data/work"))


def get_output_dir() -> Path:
    return Path(get_env("OUTPUT_DIR", "data/output"))


def get_blob_connection_string() -> str:
    return get_env("AZURE_STORAGE_CONNECTION_STRING")


def get_postgres_connection_string() -> str:
    return get_env("POSTGRES_CONNECTION_STRING")


def get_coastal_zone_path() -> Path:
    """Path to the coastal analysis zone GeoJSON (ADR-018)."""
    return Path("data/geometry/coastal_analysis_zone.geojson")


def get_europe_path() -> Path:
    """Path to the Europe support geometry GeoJSON (ADR-018)."""
    return Path("data/geometry/europe.geojson")
