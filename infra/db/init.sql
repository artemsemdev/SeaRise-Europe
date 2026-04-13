-- =============================================================================
-- SeaRise Europe -- Database Initialization Script
-- =============================================================================
-- Epic:     E-02 (Local Development Environment)
-- Story:    S02-02
-- Sources:  docs/architecture/05-data-architecture.md (section 2)
--           docs/delivery/artifacts/seed-data-spec.sql
--
-- This script runs automatically on first `docker compose up` via the
-- PostgreSQL docker-entrypoint-initdb.d mechanism.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- 1. scenarios
--    Source: ADR-016 (S01-01, OQ-02)
-- ---------------------------------------------------------------------------

CREATE TABLE scenarios (
    id           VARCHAR(64)  PRIMARY KEY,
    display_name VARCHAR(255) NOT NULL,
    description  TEXT,
    sort_order   INTEGER      NOT NULL,
    is_default   BOOLEAN      NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Invariant: at most one row has is_default = true
CREATE UNIQUE INDEX scenarios_default_idx ON scenarios (is_default) WHERE is_default = true;

-- ---------------------------------------------------------------------------
-- 2. horizons
--    Source: ADR-017 (S01-02, OQ-03), FR-015
-- ---------------------------------------------------------------------------

CREATE TABLE horizons (
    year          INTEGER     PRIMARY KEY,
    display_label VARCHAR(32) NOT NULL,
    is_default    BOOLEAN     NOT NULL DEFAULT false,
    sort_order    INTEGER     NOT NULL
);

CREATE UNIQUE INDEX horizons_default_idx ON horizons (is_default) WHERE is_default = true;

-- ---------------------------------------------------------------------------
-- 3. methodology_versions
--    Source: ADR-015 (S01-04, OQ-05)
-- ---------------------------------------------------------------------------

CREATE TABLE methodology_versions (
    version                  VARCHAR(32)  PRIMARY KEY,
    is_active                BOOLEAN      NOT NULL DEFAULT false,
    sea_level_source_name    TEXT         NOT NULL,
    elevation_source_name    TEXT         NOT NULL,
    what_it_does             TEXT         NOT NULL,
    limitations              TEXT         NOT NULL,
    resolution_note          TEXT         NOT NULL,
    exposure_threshold       NUMERIC,
    exposure_threshold_desc  TEXT         NOT NULL,
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4. layers
--    Source: docs/architecture/05-data-architecture.md section 2
-- ---------------------------------------------------------------------------

CREATE TABLE layers (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id          VARCHAR(64)  NOT NULL REFERENCES scenarios(id),
    horizon_year         INTEGER      NOT NULL REFERENCES horizons(year),
    methodology_version  VARCHAR(32)  NOT NULL REFERENCES methodology_versions(version),
    blob_path            TEXT         NOT NULL,
    blob_container       TEXT         NOT NULL DEFAULT 'geospatial',
    cog_format           BOOLEAN      NOT NULL DEFAULT true,
    layer_valid          BOOLEAN      NOT NULL DEFAULT false,
    legend_colormap      JSONB,
    generated_at         TIMESTAMPTZ  NOT NULL,
    UNIQUE (scenario_id, horizon_year, methodology_version)
);

CREATE INDEX layers_lookup_idx ON layers (scenario_id, horizon_year, methodology_version)
    WHERE layer_valid = true;

-- ---------------------------------------------------------------------------
-- 5. geography_boundaries
--    Source: ADR-018 (S01-03, OQ-04)
-- ---------------------------------------------------------------------------

CREATE TABLE geography_boundaries (
    name        VARCHAR(64)                  PRIMARY KEY,
    geom        GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    description TEXT,
    source      TEXT,
    created_at  TIMESTAMPTZ                  NOT NULL DEFAULT now()
);

CREATE INDEX geography_boundaries_geom_idx ON geography_boundaries USING GIST(geom);

-- ===========================================================================
-- Seed Data (from docs/delivery/artifacts/seed-data-spec.sql)
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- scenarios  (ADR-016, ADR-017)
-- ---------------------------------------------------------------------------

INSERT INTO scenarios (id, display_name, description, sort_order, is_default)
VALUES
  (
    'ssp1-26',
    'Lower emissions (SSP1-2.6)',
    'Lower-emissions AR6 pathway used as the lower-bound scenario in MVP.',
    1,
    false
  ),
  (
    'ssp2-45',
    'Intermediate emissions (SSP2-4.5)',
    'Mid-range AR6 pathway used as the default reference scenario in MVP.',
    2,
    true
  ),
  (
    'ssp5-85',
    'Higher emissions (SSP5-8.5)',
    'Higher-emissions AR6 pathway used as the upper-bound scenario in MVP.',
    3,
    false
  );

-- ---------------------------------------------------------------------------
-- horizons  (ADR-017, FR-015)
-- ---------------------------------------------------------------------------

INSERT INTO horizons (year, display_label, is_default, sort_order)
VALUES
  (2030, '2030', false, 1),
  (2050, '2050', true,  2),
  (2100, '2100', false, 3);

-- ---------------------------------------------------------------------------
-- methodology_versions  (ADR-015)
-- ---------------------------------------------------------------------------

INSERT INTO methodology_versions (
  version,
  is_active,
  sea_level_source_name,
  elevation_source_name,
  what_it_does,
  limitations,
  resolution_note,
  exposure_threshold,
  exposure_threshold_desc,
  updated_at
)
VALUES (
  'v1.0',
  true,
  'IPCC AR6 sea-level projections (NASA Sea Level Change Team)',
  'Copernicus DEM GLO-30 (Digital Surface Model)',
  'This methodology combines IPCC AR6 mean sea-level rise projections with Copernicus DEM surface elevation to identify locations in the coastal analysis zone where projected mean sea-level rise reaches or exceeds terrain elevation under the selected scenario and time horizon.',
  '["Flood defenses or adaptation infrastructure","Hydrodynamic flow behavior or detailed water pathways","Storm surge or tidal variability","Land subsidence or uplift","Local drainage systems or pumping infrastructure"]',
  'Results are derived from approximately 30-meter resolution datasets. Results cannot distinguish conditions within a single city block and are not suitable for site-specific engineering or property-level decisions.',
  NULL,
  'No separate runtime threshold. Binary exposure is precomputed offline using the rule: projected mean sea-level rise >= terrain elevation within the coastal analysis zone.',
  '2026-04-03T00:00:00Z'
);

-- ---------------------------------------------------------------------------
-- geography_boundaries  (ADR-018)
-- DEV SYNTHETIC: coarse bbox polygons for local development only.
-- Replace with real Natural Earth / Copernicus Coastal Zones 2018 geometries
-- in Epic 03 when the full pipeline runs.
-- ---------------------------------------------------------------------------

INSERT INTO geography_boundaries (name, geom, description, source)
VALUES (
  'europe',
  ST_GeomFromText(
    'MULTIPOLYGON(((-25 34, 45 34, 45 72, -25 72, -25 34)))',
    4326
  ),
  'DEV SYNTHETIC: coarse bbox covering Europe for local development.',
  'Synthetic bbox -- replace with Natural Earth 10m Admin 0 dissolved geometry.'
);

INSERT INTO geography_boundaries (name, geom, description, source)
VALUES (
  'coastal_analysis_zone',
  ST_GeomFromText(
    'MULTIPOLYGON(((-12 36, 20 36, 20 62, -12 62, -12 36)))',
    4326
  ),
  'DEV SYNTHETIC: coarse bbox used as coastal-zone stand-in for local development.',
  'Synthetic bbox -- replace with Copernicus Coastal Zones 2018 dissolved ~10 km inland buffer.'
);

-- ---------------------------------------------------------------------------
-- layers  (DEV SYNTHETIC)
-- All rows point at a single synthetic demo COG produced by the blob-seed
-- service. (ssp5-85, 2100) is deliberately marked invalid to exercise the
-- DataUnavailable result state. Replace with real pipeline output when
-- available.
-- ---------------------------------------------------------------------------

INSERT INTO layers (scenario_id, horizon_year, methodology_version, blob_path, layer_valid, generated_at)
VALUES
  ('ssp1-26', 2030, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp1-26', 2050, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp1-26', 2100, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp2-45', 2030, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp2-45', 2050, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp2-45', 2100, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp5-85', 2030, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp5-85', 2050, 'v1.0', 'layers/v1.0/demo.tif', true,  '2026-04-03T00:00:00Z'),
  ('ssp5-85', 2100, 'v1.0', 'layers/v1.0/demo.tif', false, '2026-04-03T00:00:00Z');
