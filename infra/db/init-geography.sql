-- =============================================================================
-- SeaRise Europe — Geography Seed (ADR-018)
-- =============================================================================
-- Runs AFTER init.sql (ordered by filename in /docker-entrypoint-initdb.d/).
--
-- Loads real geometries into `geography_boundaries` from the GeoJSON files
-- under data/geometry/, which docker-compose mounts into the postgres
-- container at /geometry/:ro.  See data/geometry/README.md for provenance,
-- build recipe, and validation table.
--
-- Build inputs (public domain):
--   * Natural Earth 1:10m Admin 0 Countries (filtered, dissolved) -> europe
--   * Natural Earth 1:10m Ocean + europe ∩ 25km metric buffer     -> coastal zone
--
-- This file uses psql meta-commands (\set + :'var' interpolation) and is
-- therefore NOT loadable by Npgsql — the integration test harness
-- (src/api/SeaRise.Api.Tests/Integration/TestDbFixture.cs) skips it
-- entirely and seeds its own synthetic bbox geometries.
-- =============================================================================

\set europe_geojson `cat /geometry/europe.geojson`
\set coastal_geojson `cat /geometry/coastal_analysis_zone.geojson`

INSERT INTO geography_boundaries (name, geom, description, source)
VALUES (
  'europe',
  ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON((:'europe_geojson'::jsonb -> 'features' -> 0 -> 'geometry')::text), 4326)),
  'Dissolved Natural Earth 1:10m Admin 0 countries, continent=Europe minus Russia, clipped to (-30,30,45,75).',
  'naturalearthdata.com ne_10m_admin_0_countries (public domain); see data/geometry/europe.geojson and data/geometry/README.md.'
);

INSERT INTO geography_boundaries (name, geom, description, source)
VALUES (
  'coastal_analysis_zone',
  ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON((:'coastal_geojson'::jsonb -> 'features' -> 0 -> 'geometry')::text), 4326)),
  'Local approximation of Copernicus Coastal Zones 2018 (ADR-018): europe intersected with a 25 km metric buffer of ne_10m_ocean in EPSG:3035.',
  'Derived from Natural Earth ne_10m_ocean; canonical Copernicus Coastal Zones 2018 should replace this when available. See data/geometry/coastal_analysis_zone.geojson and data/geometry/README.md.'
);
