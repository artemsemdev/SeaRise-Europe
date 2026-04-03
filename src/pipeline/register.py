"""Step 7: Register layers and seed metadata in PostgreSQL (S03-07).

Seeds the following tables from the Epic 01 specification:
  - scenarios       (ADR-016, ADR-017)
  - horizons        (ADR-017, FR-015)
  - methodology_versions  (ADR-015)
  - geography_boundaries  (ADR-018)

Then registers each COG as a ``layers`` row and activates the methodology
version atomically.

All INSERTs use ON CONFLICT to be idempotent (re-runs are safe).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import psycopg2

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed data (from docs/delivery/artifacts/seed-data-spec.sql)
# ---------------------------------------------------------------------------

_SCENARIOS = [
    ("ssp1-26", "Lower emissions (SSP1-2.6)",
     "Lower-emissions AR6 pathway used as the lower-bound scenario in MVP.", 1, False),
    ("ssp2-45", "Intermediate emissions (SSP2-4.5)",
     "Mid-range AR6 pathway used as the default reference scenario in MVP.", 2, True),
    ("ssp5-85", "Higher emissions (SSP5-8.5)",
     "Higher-emissions AR6 pathway used as the upper-bound scenario in MVP.", 3, False),
]

_HORIZONS = [
    (2030, "2030", False, 1),
    (2050, "2050", True, 2),
    (2100, "2100", False, 3),
]

_METHODOLOGY_V1 = {
    "version": "v1.0",
    "sea_level_source_name": "IPCC AR6 sea-level projections (NASA Sea Level Change Team)",
    "elevation_source_name": "Copernicus DEM GLO-30 (Digital Surface Model)",
    "what_it_does": (
        "This methodology combines IPCC AR6 mean sea-level rise projections "
        "with Copernicus DEM surface elevation to identify locations in the "
        "coastal analysis zone where projected mean sea-level rise reaches or "
        "exceeds terrain elevation under the selected scenario and time horizon."
    ),
    "limitations": json.dumps([
        "Flood defenses or adaptation infrastructure",
        "Hydrodynamic flow behavior or detailed water pathways",
        "Storm surge or tidal variability",
        "Land subsidence or uplift",
        "Local drainage systems or pumping infrastructure",
    ]),
    "resolution_note": (
        "Results are derived from approximately 30-meter resolution datasets. "
        "Results cannot distinguish conditions within a single city block and "
        "are not suitable for site-specific engineering or property-level decisions."
    ),
    "exposure_threshold": None,
    "exposure_threshold_desc": (
        "No separate runtime threshold. Binary exposure is precomputed offline "
        "using the rule: projected mean sea-level rise >= terrain elevation "
        "within the coastal analysis zone."
    ),
}

_GEOGRAPHY_BOUNDARIES = [
    {
        "name": "europe",
        "description": "WGS84 boundary geometry for supported European countries.",
        "source": (
            "Natural Earth 10m cultural vectors -- Admin 0 countries, "
            "filtered to European countries and dissolved."
        ),
    },
    {
        "name": "coastal_analysis_zone",
        "description": (
            "European coastal analysis zone (~10 km inland extent). "
            "Locations inside this zone are eligible for exposure assessment; "
            "locations outside return OutOfScope."
        ),
        "source": (
            "Copernicus Land Monitoring Service -- Coastal Zones 2018 "
            "(https://land.copernicus.eu/en/products/coastal-zones). "
            "Dissolved, cleaned in EPSG:3035, reprojected to EPSG:4326, "
            "clipped to europe boundary."
        ),
    },
]


# ---------------------------------------------------------------------------
# Seeding functions
# ---------------------------------------------------------------------------

def seed_scenarios(conn_string: str) -> None:
    """Seed the ``scenarios`` table (idempotent)."""
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            for sid, display, desc, sort, default in _SCENARIOS:
                cur.execute(
                    """
                    INSERT INTO scenarios (id, display_name, description, sort_order, is_default)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description  = EXCLUDED.description,
                        sort_order   = EXCLUDED.sort_order,
                        is_default   = EXCLUDED.is_default
                    """,
                    (sid, display, desc, sort, default),
                )
        conn.commit()
        logger.info("Seeded %d scenarios", len(_SCENARIOS))
    finally:
        conn.close()


def seed_horizons(conn_string: str) -> None:
    """Seed the ``horizons`` table (idempotent)."""
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            for year, label, default, sort in _HORIZONS:
                cur.execute(
                    """
                    INSERT INTO horizons (year, display_label, is_default, sort_order)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (year) DO UPDATE SET
                        display_label = EXCLUDED.display_label,
                        is_default    = EXCLUDED.is_default,
                        sort_order    = EXCLUDED.sort_order
                    """,
                    (year, label, default, sort),
                )
        conn.commit()
        logger.info("Seeded %d horizons", len(_HORIZONS))
    finally:
        conn.close()


def seed_methodology_version(conn_string: str) -> None:
    """Seed the ``methodology_versions`` table with v1.0 (idempotent)."""
    m = _METHODOLOGY_V1
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO methodology_versions (
                    version, is_active,
                    sea_level_source_name, elevation_source_name,
                    what_it_does, limitations, resolution_note,
                    exposure_threshold, exposure_threshold_desc
                ) VALUES (%s, false, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (version) DO UPDATE SET
                    sea_level_source_name = EXCLUDED.sea_level_source_name,
                    elevation_source_name = EXCLUDED.elevation_source_name,
                    what_it_does          = EXCLUDED.what_it_does,
                    limitations           = EXCLUDED.limitations,
                    resolution_note       = EXCLUDED.resolution_note,
                    exposure_threshold    = EXCLUDED.exposure_threshold,
                    exposure_threshold_desc = EXCLUDED.exposure_threshold_desc
                """,
                (
                    m["version"],
                    m["sea_level_source_name"],
                    m["elevation_source_name"],
                    m["what_it_does"],
                    m["limitations"],
                    m["resolution_note"],
                    m["exposure_threshold"],
                    m["exposure_threshold_desc"],
                ),
            )
        conn.commit()
        logger.info("Seeded methodology version %s", m["version"])
    finally:
        conn.close()


def seed_geography_boundaries(
    conn_string: str,
    coastal_zone_geojson: Path | None = None,
    europe_geojson: Path | None = None,
) -> None:
    """Seed ``geography_boundaries`` with actual or placeholder geometries.

    If GeoJSON paths are provided, real geometries are loaded via PostGIS
    ``ST_GeomFromGeoJSON``.  Otherwise placeholder EMPTY geometries are used
    (matching the Epic 02 init.sql baseline).
    """
    import geopandas as gpd

    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            for row in _GEOGRAPHY_BOUNDARIES:
                geojson_path = None
                if row["name"] == "coastal_analysis_zone" and coastal_zone_geojson:
                    geojson_path = coastal_zone_geojson
                elif row["name"] == "europe" and europe_geojson:
                    geojson_path = europe_geojson

                if geojson_path and geojson_path.exists():
                    gdf = gpd.read_file(geojson_path)
                    if gdf.crs and gdf.crs.to_epsg() != 4326:
                        gdf = gdf.to_crs(epsg=4326)
                    geom_geojson = gdf.union_all().geojson if hasattr(gdf, "union_all") else gdf.unary_union.__geo_interface__
                    geom_json = json.dumps(geom_geojson) if isinstance(geom_geojson, dict) else geom_geojson
                    geom_sql = "ST_Multi(ST_GeomFromGeoJSON(%s))"
                    geom_param = (geom_json,)
                else:
                    geom_sql = "ST_GeomFromText(%s, 4326)"
                    geom_param = ("MULTIPOLYGON EMPTY",)

                cur.execute(
                    f"""
                    INSERT INTO geography_boundaries (name, geom, description, source)
                    VALUES (%s, {geom_sql}, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        geom        = EXCLUDED.geom,
                        description = EXCLUDED.description,
                        source      = EXCLUDED.source
                    """,
                    (row["name"], *geom_param, row["description"], row["source"]),
                )
        conn.commit()
        logger.info("Seeded %d geography boundaries", len(_GEOGRAPHY_BOUNDARIES))
    finally:
        conn.close()


def seed_all(
    conn_string: str,
    coastal_zone_geojson: Path | None = None,
    europe_geojson: Path | None = None,
) -> None:
    """Run all seed functions in dependency order."""
    seed_scenarios(conn_string)
    seed_horizons(conn_string)
    seed_methodology_version(conn_string)
    seed_geography_boundaries(conn_string, coastal_zone_geojson, europe_geojson)


# ---------------------------------------------------------------------------
# Layer registration
# ---------------------------------------------------------------------------

def register_layer(
    conn_string: str,
    scenario_id: str,
    horizon_year: int,
    methodology_version: str,
    blob_path: str,
    legend_colormap: dict,
) -> str:
    """Insert a layer row with ``layer_valid=false``.  Returns the layer UUID."""
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO layers
                    (scenario_id, horizon_year, methodology_version,
                     blob_path, generated_at, legend_colormap)
                VALUES (%s, %s, %s, %s, now(), %s)
                ON CONFLICT (scenario_id, horizon_year, methodology_version)
                DO UPDATE SET
                    blob_path       = EXCLUDED.blob_path,
                    generated_at    = EXCLUDED.generated_at,
                    layer_valid     = false,
                    legend_colormap = EXCLUDED.legend_colormap
                RETURNING id
                """,
                (
                    scenario_id,
                    horizon_year,
                    methodology_version,
                    blob_path,
                    json.dumps(legend_colormap),
                ),
            )
            layer_id = cur.fetchone()[0]
        conn.commit()
        logger.info(
            "Registered layer %s for %s/%d (valid=false)",
            layer_id, scenario_id, horizon_year,
        )
        return str(layer_id)
    finally:
        conn.close()


def mark_layer_valid(conn_string: str, layer_id: str) -> None:
    """Set ``layer_valid = true`` after QA validation passes."""
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE layers SET layer_valid = true WHERE id = %s",
                (layer_id,),
            )
        conn.commit()
        logger.info("Marked layer %s as valid", layer_id)
    finally:
        conn.close()


def activate_methodology_version(conn_string: str, version: str) -> None:
    """Atomically deactivate all versions and activate *version*."""
    conn = psycopg2.connect(conn_string)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE methodology_versions SET is_active = false "
                "WHERE is_active = true"
            )
            cur.execute(
                "UPDATE methodology_versions SET is_active = true "
                "WHERE version = %s",
                (version,),
            )
        conn.commit()
        logger.info("Activated methodology version %s", version)
    finally:
        conn.close()
