# Phase 0.8 — Terrain, Geography, and Connectivity Controls

> **Evidence date:** 2026-08-05
>
> **Issue:** [#84](https://github.com/artemsemdev/SeaRise-Europe/issues/84)
>
> **Decision:** GLO-30, explicit Europe/25 km product scope, and an
> eight-neighbour ocean-seeded connectivity screen are selected for external
> review
>
> **Publication gate:** **Blocked** — independent approvals and terrain error
> bounds are incomplete
>
> **Machine evidence:**
> [`phase-0-8-terrain-geography.json`](../../src/pipeline/science/evidence/phase-0-8-terrain-geography.json)

## Outcome

Phase 0.8 replaces three implicit choices with versioned, executable
contracts:

- Copernicus DEM **GLO-30 release 2021_1** is the selected terrain grid;
- Europe support is an explicit 50-feature Natural Earth `ADM0_A3` allow-list,
  and the 25 km coastal band remains a product-eligibility approximation;
- connectivity is an eight-neighbour breadth-first traversal from land cells
  adjacent to GLO-30 WBM ocean cells, after vertical interval classification.

These are selections for external review, not approvals invented by the
project. The publication gate remains blocked. In particular, Copernicus DEM
is a digital surface model and its HEM does not bound systematic, edit/fill,
or DSM-representation error.

## Primary evidence

| Source | Fact used |
|---|---|
| [Copernicus DEM product page](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) | GLO-30/GLO-90 availability, product-level accuracy statement, source licence/attribution, and product editions |
| [Copernicus DEM Product Handbook, issue 5.0](https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf) | WGS84-G1150 horizontal reference, EGM2008 vertical reference, PixelIsPoint grid, EDM/FLM/HEM/WBM meanings, and HEM limitations |
| [Copernicus Coastal Zones 2018](https://land.copernicus.eu/en/products/coastal-zones/coastal-zones-2018) | Version V1-2018, EPSG:3035 vector product, DOI, published 10 km inland land-cover scope, and “not yet validated” status |
| [Copernicus Land Monitoring Service data policy](https://land.copernicus.eu/en/data-policy) | Full, open, attribution-based reuse terms for Coastal Zones evidence |

The five DEM windows and all four auxiliary layers per resolution are locked
by exact URL, byte size, and SHA-256 in the source registry. The evidence
builder refuses a missing, misaligned, mistyped, or unexpected-code layer.

| Resolution | Source-lock asset | Manifest SHA-256 | Objects / bytes |
|---|---|---|---:|
| GLO-30 | `copernicus-dem-glo30:regional-control-set` | `4803149548589b7c97d747ae99fd21267d1bc07b9ec02bf6b5e19d06c335f5e6` | 25 / 165,670,216 |
| GLO-90 | `copernicus-dem-glo90:regional-control-set` | `5c2d1848c5fefb81d9a280afbaaeb745490444ff7b5faded052f9eddc93d3e85` | 25 / 20,555,898 |

## Terrain resolution decision

Five one-degree windows were chosen before comparison to exercise distinct
coastal contexts: Malta small islands, Lisbon steep estuary, Venice lagoon,
the low Netherlands coast, and Reykjavik steep island terrain. Each window
contains GLO-30 and GLO-90 `DEM`, `EDM`, `FLM`, `HEM`, and `WBM` assets.

| Window | GLO-30 p95 HEM σ (m) | GLO-90 p95 HEM σ (m) | p95 absolute grid difference (m) | GLO-90 water cells containing GLO-30 land |
|---|---:|---:|---:|---:|
| Malta | 1.126 | 1.630 | 1.155 | 896 |
| Lisbon | 1.796 | 3.331 | 1.455 | 2,495 |
| Venice | 0.851 | 1.210 | 0.687 | 19,190 |
| Netherlands | 1.557 | 2.059 | 0.633 | 7,380 |
| Reykjavik | 0.722 | 1.067 | 1.329 | 5,930 |

Near-threshold class disagreement occurs in every window. Across all five
windows, 35,891 coarse WBM water cells contain GLO-30 land presence. GLO-30
uses nine times the pixels and 8.06 times the bytes for the five source-layer
sets. A lossless two-metre land-elevation class proxy is 6.73 times larger.

This comparison has no independent vertical truth and does not prove absolute
accuracy. It supports choosing GLO-30 because the selected product must retain
narrow coasts and small islands, while raw build cost can be isolated from the
browser. The browser will range-read immutable classified coastal COG blocks;
it will not download or evaluate raw DEM or quality layers.

## Terrain uncertainty policy

The machine contract uses every auxiliary layer and fails closed:

- `EDM` codes 0–13, `FLM` codes 0–9 and 100–102, and `WBM` codes 0–3 are the
  only accepted categorical values;
- HEM is a per-pixel one-sigma random-error estimate for unedited values;
- HEM `-32767` marks edited regions and cannot be replaced by a convenient
  number;
- `U_random = 1.645 × HEM` for a valid unedited pixel;
- the published “less than 4 m LE90” performance target is product-level
  evidence, not a per-pixel uncertainty bound;
- `U_systematic`, `U_edit`, `U_DSM`, and `U_resolution` each require an
  independent bound and never default to zero.

The terrain contribution is therefore:

```text
U_Z = U_random + U_systematic + U_edit + U_DSM + U_resolution
```

If any required term is absent, the classification is
`DataUnavailable` / `uncertain-threshold`, never
`NoModeledExposureDetected`. This deliberately leaves systematic error, edited
pixels, and DSM representation as publication blockers.

## Europe and coastal product scope

The support recipe selects 50 exact `ADM0_A3` features, clips to
`[-30, 30, 45, 75]`, repairs and quantizes topology in EPSG:3035, applies a
declared 1 km coastline tolerance for generalized source shorelines, and
simplifies by 500 m. Russia, Turkey, Cyprus, the Caucasus, Canary Islands,
Svalbard, and out-of-clip overseas territories are excluded. Included remote
European islands inside the rule include Iceland, Malta, Madeira, the Azores,
Faroe Islands, Åland, the Channel Islands, and Isle of Man.

The coastal scope buffers the pinned Natural Earth ocean by 25 km in EPSG:3035
and intersects it with support. A declared serialization inset removes
rounding slivers, and the persisted invariant is
`support.covers(coastal)`. Measured QA reports:

- valid support and coastal MultiPolygons;
- zero coastal area outside support;
- 5,933,973 km² support and 1,136,685 km² coastal product scope;
- 27/27 independent GeoNames named-place controls passing;
- `covers` includes the generated boundary control while `contains` does not.

Copernicus Coastal Zones V1-2018 was considered as canonical comparison
evidence. It is a 10 km inland land-cover/land-use mapping extent derived from
EU-Hydro and is officially marked “not yet validated.” It is not a flood-reach
or ocean-connectivity product, so it does not replace the 25 km eligibility
scope. Product-owner review of the explicit country/territory and distance
outcomes remains required.

## Connectivity control

Connectivity is evaluated only after the vertical interval. It cannot modify
`C_low`, `C_high`, or turn an uncertain cell into a class.

1. Mosaic the complete analysis region before traversal.
2. Mark confidently exposed land cells as eligible.
3. Seed eligible land cells that share an edge or corner with a pinned GLO-30
   WBM ocean cell.
4. Traverse eight neighbours through eligible cells only.
5. Treat nodata, uncertain-threshold, not-exposed, rejected-quality, and
   explicit barrier cells as non-traversable.
6. Publish connected land only and record pre/post counts.

Nine symbolic controls cover open coast, diagonal connection, nodata and
quality barriers, a disconnected inland depression, steep coast, a small
island, an estuary/lagoon corridor, and a tile seam. All pass. These controls
prove the implementation contract; they are not hydrodynamic validation.
Independent scientific review must still decide whether eight-neighbour
corner connectivity and the available barrier model are acceptable.

## Reproduction

Rebuild the geography byte-for-byte from the source-lock-verified Natural
Earth archives:

```bash
PYTHONPATH=src/pipeline python scripts/science/rebuild_phase_0_8_geography.py \
  --admin-archive /path/to/ne_10m_admin_0_countries.zip \
  --ocean-archive /path/to/ne_10m_ocean.zip
```

Rebuild the measured evidence from the 50 source-lock-verified DEM assets:

```bash
PYTHONPATH=src/pipeline python scripts/science/build_phase_0_8_evidence.py \
  --dem-dir /path/to/phase-0-8-dem-samples
```

## Remaining blockers

- independent scientific/data review of GLO-30 and connectivity;
- product-owner review of Europe, territory, and 25 km scope outcomes;
- independently bounded systematic, edit/fill, DSM-representation, and
  resolution errors;
- Phase 0.6 source-lock integration and Phase 0.7 reconciliation controls;
- the Phase 0.9 real regional rebuild and final scientific gate decision.

No public release or Phase 1 work is authorized by this evidence alone.
