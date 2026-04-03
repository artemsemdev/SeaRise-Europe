# Geometry Data Directory

This directory holds geometry files used by SeaRise Europe for geography validation.

## Expected Contents

| File | Source | Produced By | Status |
|------|--------|-------------|--------|
| `coastal_analysis_zone.geojson` | Copernicus Coastal Zones 2018 | Pipeline bootstrap (Epic 03, `src/pipeline/download.py`) | Pending — produce via pipeline or manual download |

## Coastal Analysis Zone Specification

**Decision:** ADR-018 (S01-03, OQ-04)

**Source dataset:** Copernicus Land Monitoring Service — Coastal Zones 2018
- URL: https://land.copernicus.eu/en/products/coastal-zones
- License: Copernicus Land Monitoring Service (free, open, attribution required)
- Inland extent: ~10 km (defined by the dataset)

**Processing steps:**
1. Download the vector Coastal Zones dataset from Copernicus.
2. Dissolve all coastal-land polygons into a single multipolygon.
3. Clean topology in EPSG:3035 (Europe Lambert Azimuthal Equal Area).
4. Reproject to EPSG:4326 (WGS84).
5. Clip to the `europe` support geometry.
6. Export as GeoJSON.

**Validation (must pass before seeding to PostGIS):**

| Location | Lat | Lon | Expected |
|----------|-----|-----|----------|
| Amsterdam | 52.37 | 4.90 | In coastal zone |
| Barcelona | 41.39 | 2.17 | In coastal zone |
| Copenhagen | 55.68 | 12.57 | In coastal zone |
| Lisbon | 38.72 | -9.14 | In coastal zone |
| Venice | 45.44 | 12.34 | In coastal zone |
| Prague | 50.08 | 14.43 | Out of scope |
| Zurich | 47.38 | 8.54 | Out of scope |
| Vienna | 48.21 | 16.37 | Out of scope |
| Munich | 48.14 | 11.58 | Out of scope |
| Bratislava | 48.15 | 17.11 | Out of scope |
