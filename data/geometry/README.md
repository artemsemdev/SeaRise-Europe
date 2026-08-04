# Geometry Reference Fixtures

> **Status:** checked-in migration and test fixtures, not validated production geometry
> **Architecture:** [ADR-021](../../docs/architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)

This directory contains small WGS84 GeoJSON geometries used by the existing
implementation and by migration tests. In the static-first architecture, the
offline pipeline versions the chosen source geometry, validates it, and
publishes browser PMTiles plus analytical GeoParquet inside an immutable data
release. The browser then performs support/coastal predicates locally.

These files are not loaded into a production database. Their presence does not
mean that the Europe support rule or canonical coastal source has passed the
ADR-021 Phase 0 scientific gate.

## Files

| File | Built | Source | Role and limitation |
|---|---|---|---|
| `europe.geojson` | 2026-04-14 | Natural Earth 1:10m Admin 0 Countries | Approximate support geometry; excludes Russia and Turkey under the recipe below |
| `coastal_analysis_zone.geojson` | 2026-04-14 | Natural Earth 1:10m Ocean + `europe.geojson` | Approximate 25 km band; not the canonical Copernicus coastal product |

The final treatment of transcontinental states, canonical coastal product, and
coastal-connectivity method remain measured methodology decisions. A
production release must state the exact rules in `manifest.json` and include
source/version/checksum/licence metadata.

## `europe.geojson` recipe

**Source:** `ne_10m_admin_0_countries.shp` from
[Natural Earth](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/),
public domain.

**Current fixture filter:** `CONTINENT == 'Europe' AND NAME != 'Russia'` (50
countries). Natural Earth classifies Turkey as Asia, so it is also excluded.
This is a documented fixture rule, not the final Europe product definition.

Processing:

1. Filter with the rule above.
2. Clip to `(-30, 30, 45, 75)` to remove French overseas geometry.
3. Union the remaining country polygons.
4. Buffer by `0.02` degrees to retain near-coast cities after simplification.
5. Simplify by `0.02` degrees with topology preservation.
6. Round coordinates to four decimal places.
7. Normalize to a MultiPolygon FeatureCollection in CRS84/EPSG:4326.

The buffer is a pragmatic fixture transformation, not a precise metric
operation. Production geometry must use an appropriate projected CRS for
metric operations and report the resulting spatial difference.

Current control points:

| Expected inside | Expected outside |
|---|---|
| Amsterdam, Barcelona, Copenhagen, Lisbon, Venice | New York |
| Prague, Zurich, Vienna, Munich, Bratislava | Moscow, Istanbul |
| Reykjavik, Malta | — |

Boundary points require explicit predicate tests; do not assume the behaviour
of `contains` and `covers` is interchangeable.

## `coastal_analysis_zone.geojson` recipe

The intended canonical evidence is the Copernicus Land Monitoring Service
[Coastal Zones product](https://land.copernicus.eu/en/products/coastal-zones).
The checked-in file is a local approximation because that source was not
acquired and validated in the existing automated pipeline.

**Fixture inputs:** Natural Earth `ne_10m_ocean.shp` (public domain) and the
`europe.geojson` fixture above.

Processing:

1. Clip the ocean geometry to `(-35, 28, 48, 77)`.
2. Union the clipped ocean polygons.
3. Reproject to EPSG:3035 (ETRS89 / LAEA Europe).
4. Buffer by 25,000 metres.
5. Intersect with the Europe fixture in EPSG:3035.
6. Reproject to EPSG:4326, simplify by `0.02` degrees, and round to four
   decimals.

Why 25 km: the Natural Earth 1:10m ocean geometry is too coarse around some
estuaries, waterways, and ports. In the fixture, a 25 km band includes
Amsterdam and Rotterdam while leaving selected inland controls outside. It is
a product-scope approximation and says nothing about the physical reach of
flooding.

Current control points:

| Expected inside the fixture zone | Expected outside the fixture zone |
|---|---|
| Amsterdam, Rotterdam, Barcelona, Copenhagen | Prague, Zurich, Vienna, Munich |
| Lisbon, Venice, Hamburg, Reykjavik | Bratislava, Berlin, Warsaw, Utrecht |

## Use in the target offline pipeline

Until canonical geometry passes Phase 0, these files may be used only for:

- deterministic unit and browser fixtures;
- migration parity comparisons with the legacy implementation;
- regional packaging and byte-range performance spikes;
- demonstrating geometry-to-PMTiles/GeoParquet mechanics with an explicit
  `approximation` label.

They must not be used to claim complete or scientifically validated European
coastal coverage. A real candidate release must:

1. pin the source snapshot and SHA-256;
2. record all filters, CRS operations, tolerances, and repairs;
3. validate topology, known points, islands, ports, estuaries, and support
   boundary cases;
4. compare areas and spatial differences with these fixtures and the prior
   release;
5. publish derived `geography/*.pmtiles` and `boundaries.parquet`;
6. record the support/coastal rule and QA summary in the release manifest.

## Rebuilding the fixtures

Rebuild only through a checked-in, deterministic pipeline stage that pins the
Natural Earth release and verifies input checksums. Do not rely on an
unversioned one-off script as provenance. Review all control points and commit
the updated fixture plus its source/checksum record together.
