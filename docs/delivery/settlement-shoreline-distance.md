# Settlement shoreline distance source

> **Issue:** [#50](https://github.com/artemsemdev/SeaRise-Europe/issues/50)
> **Boundary:** immutable settlement distance source and recipe only; no hazard,
> canonical-coastline, owner-approval, or publication claim.

The settlement pipeline uses direct Natural Earth 10m coastline linework from
two official archives. The scoped source lock, closed policy, generated
GeoJSON, and QA evidence are reviewed together:

- `src/pipeline/sources/source-lock.phase-1-settlement-coastline.json`
- `src/pipeline/settlements/shoreline-distance-policy-v1.json`
- `data/settlements/europe-settlement-shoreline-v1.geojson`
- `src/pipeline/settlements/evidence/shoreline-distance-qa-v1.json`

The source archives remain in the ignored raw cache and are never committed.
The 3.55 MB canonical GeoJSON is committed intentionally because downstream
builds must consume and verify one exact immutable byte identity.

## Source and selection contract

The scoped lock binds the archive and every ZIP member by byte size, compressed
size, CRC32, SHA-256, registry version, and bundled native version. The global
Phase 0R source lock remains byte-identical.

The recipe accepts only direct source `LineString` geometry. Its Europe bbox
selects every source feature that intersects the bbox, but retains the complete
source feature. It does not intersect or clip geometry. This prevents bbox
edges from becoming synthetic line endpoints that could be mistaken for the
nearest shoreline. Administrative boundaries, ocean-polygon boundaries,
coastal-zone boundaries, and bbox edges are explicitly prohibited substitutes.

## Distance and coastal classification

Production distance is one fixed operation:

1. Read WGS84 coordinates as longitude-latitude XY.
2. Transform places and shoreline from EPSG:4326 to EPSG:3035 with pinned
   DuckDB Spatial 1.5.4 and the always-XY flag.
3. Apply planar `ST_Distance` in meters, then persist its `DOUBLE` result as a
   whole-meter `BIGINT` with DuckDB's nearest-half-to-even cast.

Downstream contracts bind this rule as
`epsg3035-planar-whole-meter-half-even-v1`.
The exact persistence expression is
`CAST(ST_Distance(place_3035, shoreline_3035) AS BIGINT)`. There is no
nearest-in-degrees preselection, spheroid-distance fallback, or sub-meter
precision claim for the generalized Natural Earth linework.

The independent QA oracle reads through Pyogrio 0.11.1 and GDAL 3.10.3, then
uses GeoPandas 1.0.1, Shapely 2.0.7, PyProj 3.6.1, PROJ 9.3.0, and GEOS 3.11.4
to check Ponta Delgada, Capri, Barcelona, and Prague.

`isCoastal` is not derived from the distance value. It remains a separate
`ST_Covers` predicate against the versioned 25 km product-eligibility zone.

## Rebuild and verification

After fetching the two assets with the scoped lock, run:

```bash
PYTHONPATH=src/pipeline python scripts/release/build_settlement_shoreline.py \
  --coastline-archive /path/to/ne_10m_coastline.zip \
  --minor-islands-archive /path/to/ne_10m_minor_islands_coastline.zip
```

Add `--write` only when intentionally refreshing the declared immutable output
and evidence in a reviewed source-update PR. CI fetches the official locked
archives, executes the exact rebuild twice, and fails if that test is skipped,
the archives drift, or the rebuilt bytes differ from the checked-in artifact.

The named-place controls are regression evidence for source completeness and
distance behavior. They are not a scientific validation of a hazard model or
an authorization to publish the settlement catalog.

This source slice intentionally does not remove the classifier's
`shoreline-geometry-unavailable` production blocker. A separate dependent
wiring change must bind this exact policy and artifact before production
classification can run.
