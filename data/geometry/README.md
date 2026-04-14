# Geometry Data Directory

This directory holds geometry files used by SeaRise Europe for geography
validation (`/v1/assess` routes queries through `europe` and
`coastal_analysis_zone` before returning a result state).

## Contents

| File | Status | Source | Size |
|------|--------|--------|------|
| `europe.geojson` | Present (2026-04-14, Block D) | Natural Earth 1:10m Admin 0 Countries | ~165 KB |
| `coastal_analysis_zone.geojson` | Present (2026-04-14, Block D) | Natural Earth 1:10m Ocean + europe intersect | ~185 KB |

Both files are mounted read-only into the `postgres` container at `/geometry`
(see [docker-compose.yml](../../docker-compose.yml)) and loaded into the
`geography_boundaries` table by [infra/db/init.sql](../../infra/db/init.sql)
via `\set` + `ST_GeomFromGeoJSON`. The pipeline (`src/pipeline/run_pipeline.py`)
re-seeds the same rows from the same files through `seed_geography_boundaries`,
keeping init.sql and pipeline output in sync.

## `europe.geojson` — build recipe

**Source:** `ne_10m_admin_0_countries.shp` from
[Natural Earth](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/).
License: public domain.

**Filter:** `CONTINENT == 'Europe' AND NAME != 'Russia'` (50 countries) —
Russia is excluded because its territory dominates the bbox and distorts
simplification. Turkey is naturally excluded because Natural Earth classifies
it under `CONTINENT == 'Asia'`. Iceland, the UK, Malta, and Cyprus-class
islands are retained.

**Processing:**
1. Filter as above.
2. Clip to bbox `(-30, 30, 45, 75)` to drop French overseas departments
   (Guadeloupe, Martinique, French Guiana, Réunion) that Natural Earth
   stores inside the France MultiPolygon.
3. `unary_union` all remaining country polygons.
4. `buffer(0.02)` (≈2.2 km) to pad coastlines so cities very close to the
   sea (Copenhagen, Reykjavik) stay inside after simplification.
5. `simplify(0.02, preserve_topology=True)`.
6. Round coordinates to 4 decimal places (~11 m).
7. Force the result to a single MultiPolygon.
8. Write as GeoJSON FeatureCollection with EPSG:4326 (CRS84) CRS.

**Validation:** every point in the table below is verified with
`europe_geom.contains(Point(lon, lat))` during the build.

| Location | Lat | Lon | Expected | Actual |
|----------|-----|-----|----------|--------|
| Amsterdam | 52.37 | 4.90 | In | In |
| Barcelona | 41.39 | 2.17 | In | In |
| Copenhagen | 55.68 | 12.57 | In | In |
| Lisbon | 38.72 | -9.14 | In | In |
| Venice | 45.44 | 12.34 | In | In |
| Prague | 50.08 | 14.43 | In | In |
| Zurich | 47.38 | 8.54 | In | In |
| Vienna | 48.21 | 16.37 | In | In |
| Munich | 48.14 | 11.58 | In | In |
| Bratislava | 48.15 | 17.11 | In | In |
| Reykjavik | 64.15 | -21.94 | In | In |
| Malta | 35.90 | 14.51 | In | In |
| New York | 40.71 | -74.01 | Out | Out |
| Moscow | 55.75 | 37.62 | Out | Out |
| Istanbul | 41.01 | 28.98 | Out | Out |

## `coastal_analysis_zone.geojson` — build recipe

**Decision:** ADR-018 (S01-03, OQ-04). The canonical source is Copernicus
Land Monitoring Service — Coastal Zones 2018
(<https://land.copernicus.eu/en/products/coastal-zones>), which defines a
~10 km inland extent. That dataset sits behind a free EEA login and cannot
be downloaded non-interactively, so the file checked in here is a **local
approximation** derived from public-domain Natural Earth data.

**Source:** `ne_10m_ocean.shp` from Natural Earth (public domain) plus the
`europe.geojson` above.

**Processing:**
1. Clip `ne_10m_ocean` to bbox `(-35, 28, 48, 77)` (slightly wider than
   Europe so the buffer is clean at the edges).
2. `unary_union` the clipped ocean polygons.
3. Reproject to **EPSG:3035** (ETRS89 / LAEA Europe) for metric buffering.
4. `buffer(25_000)` — 25 km inland band.
5. Intersect with the europe geometry (also reprojected to 3035).
6. Reproject back to EPSG:4326, `simplify(0.02)`, round to 4 decimals.

**Why 25 km and not 10 km?** Natural Earth 1:10m `ne_10m_ocean` is too
coarse to represent estuaries, tidal waterways, and polder geography: the
Dutch coast at Rotterdam is measured at ~24 km from the nearest NE ocean
edge, even though Rotterdam is literally a maritime port. A 25 km buffer is
the smallest value that correctly includes Amsterdam and Rotterdam in the
coastal zone while keeping inland capitals (Prague, Vienna, Munich,
Bratislava) and `OutOfScope` reference cities (Utrecht, Berlin, Warsaw)
outside. The canonical Copernicus dataset is built on actual maritime land
classification and does not need this compensation.

**Validation:** every point in the table below is verified with
`coastal_geom.contains(Point(lon, lat))` during the build.

| Location | Lat | Lon | Expected | Actual |
|----------|-----|-----|----------|--------|
| Amsterdam | 52.37 | 4.90 | In coastal zone | In |
| Rotterdam | 51.92 | 4.48 | In coastal zone | In |
| Barcelona | 41.39 | 2.17 | In coastal zone | In |
| Copenhagen | 55.68 | 12.57 | In coastal zone | In |
| Lisbon | 38.72 | -9.14 | In coastal zone | In |
| Venice | 45.44 | 12.34 | In coastal zone | In |
| Hamburg | 53.55 | 9.99 | In coastal zone | In |
| Reykjavik | 64.15 | -21.94 | In coastal zone | In |
| Prague | 50.08 | 14.43 | Out of scope | Out |
| Zurich | 47.38 | 8.54 | Out of scope | Out |
| Vienna | 48.21 | 16.37 | Out of scope | Out |
| Munich | 48.14 | 11.58 | Out of scope | Out |
| Bratislava | 48.15 | 17.11 | Out of scope | Out |
| Berlin | 52.52 | 13.40 | Out of scope | Out |
| Warsaw | 52.23 | 21.01 | Out of scope | Out |
| Utrecht | 52.09 | 5.12 | Out of scope | Out |

## Rebuilding the files

The files are checked in as ground truth and should only be rebuilt when
switching data sources. The recipe is fully reproducible from public-domain
Natural Earth inputs — see the Block D entry in
[docs/delivery/audit.md](../../docs/delivery/audit.md) for the exact Python
used to build them.
