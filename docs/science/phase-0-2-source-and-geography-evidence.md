# Phase 0.2 — Source Semantics and Geography Evidence

> **Evidence date:** 2026-08-05
>
> **Issue:** [#46](https://github.com/artemsemdev/SeaRise-Europe/issues/46)
>
> **Gate result:** **Blocked** — the legacy binary comparison is not
> scientifically publishable
>
> **Machine contracts:**
> [`source-semantics.json`](../../src/pipeline/science/source-semantics.json),
> [`geography-rules.json`](../../src/pipeline/science/geography-rules.json)

## Outcome

Phase 0.2 replaced variable, quantile, unit, and coordinate guessing with a
strict mapping for IPCC AR6 version `20210809`. It also made the current Europe
and 25 km coastal fixtures reproducible and measurable while retaining their
required `approximation` status.

The inspection found a blocking vertical-reference mismatch. AR6 supplies a
change in relative sea level from the 1995–2014 baseline. Copernicus DEM
supplies absolute DSM heights in metres relative to EGM2008. No pinned local
baseline sea-surface or tidal datum and no reviewed transformation to EGM2008
exists. Therefore this repository now refuses the legacy
`sea_level_change >= DEM elevation` build by default.

This is a valid scientific-gate result, not a software failure. A downstream
regional fixture may exercise mechanics only when it explicitly opts into the
blocked methodology and labels every output non-publishable.

## IPCC AR6 inspection

### Exact source identity

| Field | Inspected fact |
|---|---|
| Zenodo record | `6382554`, DOI `10.5281/zenodo.6382554` |
| Dataset version | `20210809` |
| Regional confidence archive | `ar6-regional-confidence.zip` |
| Archive bytes | `9,243,771,601` |
| Upstream checksum | `md5:fec362a2385079fac32fa736d4a39944` |
| Locked location list | `location_list.lst`, 2,659,137 bytes |
| Location-list SHA-256 | `431bf1a682b5938290565fb4c1969e56cfbb7c4b1fb08bc7459d9b2dc758d88d` |

The regional archive has not been added as an acquirable locked asset because
the publisher exposes an MD5 but the repository requires SHA-256 before use.
Downloading nine gigabytes merely to invent an unreviewed local pin was not
hidden behind a default. `projection-archive-sha256` remains a visible blocker.

### Binding projection mapping

The official FACTS confidence-file guide documents the following source
schema. The pipeline enforces it exactly:

| Semantic | Binding value |
|---|---|
| Source key | `ipcc-ar6-sea-level/20210809` |
| File basename | `total_{scenario}_medium_confidence_values.nc` |
| Scenarios | `ssp126`, `ssp245`, `ssp585` |
| Variable | `sea_level_change` |
| Dimension order | `quantiles`, `years`, `locations` |
| Expected sizes | 107 quantiles, 14 years, 66,190 locations |
| Selected statistic | medium-confidence quantile `0.5` |
| Selected years | exact `2030`, `2050`, `2100`; no nearest-year fallback |
| Units | `mm`; exact conversion `value * 0.001` to metres |
| Fill value | `-32768`; propagated as nodata |
| Baseline | mean over 1995–2014 |

Any missing variable, changed dimension order or size, unexpected coordinate
unit, missing exact year/quantile, or changed fill value fails closed.

### Native coordinates and interpolation

The checksum-verified location list contains:

- 66,190 unique location records;
- 1,030 tide-gauge locations with IDs below `1,000,000,000`;
- 65,160 gridded locations with IDs at or above `1,000,000,000`;
- a complete `181 × 360` one-degree coordinate product;
- latitudes from `-90` through `90` and longitudes from `-180` through `179`;
- no duplicate gridded coordinate pair;
- 3,496 gridded points inside the current broad Europe inspection bounds.

The NetCDF stores tide gauges and grid points on one flattened `locations`
dimension. It is not a two-dimensional raster. The approved transformation
candidate therefore:

1. validates the exact source schema;
2. selects only IDs at or above `1,000,000,000`;
3. validates explicit latitude/longitude coordinates as a complete one-degree
   product;
4. reshapes by coordinate value, never by record order or encoded ID;
5. selects the exact year and quantile;
6. converts millimetres to metres using the contract constant;
7. bilinearly interpolates continuous change values inside the native grid;
8. performs no extrapolation and never interpolates across required nodata
   neighbours.

Tests prove exact source nodes are preserved, midpoint interpolation is stable,
out-of-range targets remain nodata, and a missing neighbour is not bridged.
The production target grid remains pending the DEM-resolution review.

Primary evidence:

- [Zenodo record 6382554](https://zenodo.org/records/6382554)
- [Official Rutgers AR6 data guide](https://github.com/Rutgers-ESSP/IPCC-AR6-Sea-Level-Projections)
- [FACTS confidence output file guide](https://github.com/Rutgers-ESSP/IPCC-AR6-Sea-Level-Projections/blob/main/FACTS_confidence_output_file_readme.pdf)
- [NASA PO.DAAC release announcement](https://podaac.jpl.nasa.gov/announcements/2021-08-09-Sea-level-projections-from-the-IPCC-6th-Assessment-Report)

## Copernicus DEM inspection and comparison

The inspected products are DSMs: buildings, infrastructure, and vegetation may
be represented. They are not bare-earth terrain models.

Binding source semantics from the Copernicus product material:

| Semantic | Value |
|---|---|
| Release | `2021_1` |
| Horizontal CRS | WGS84-G1150 / EPSG:4326 |
| Vertical CRS | EGM2008 / EPSG:3855 |
| Vertical unit | metres |
| Pixel interpretation | `RasterPixelIsPoint` |
| GLO-30 latitude spacing | 1 arc-second |
| GLO-90 latitude spacing | 3 arc-seconds |
| Published absolute vertical accuracy | less than 4 m at 90% linear error |

The same Netherlands `N52 E004` source window was downloaded from both public
S3 collections and checked against the recorded SHA-256 values. Actual
longitude spacing at this latitude is 1.5 arc-seconds for GLO-30 and 4.5
arc-seconds for GLO-90; this measured fact is recorded rather than assuming a
square angular pixel.

| Measure | GLO-30 | GLO-90 |
|---|---:|---:|
| Source bytes | 17,037,271 | 1,998,003 |
| Raster shape | 3,600 × 2,400 | 1,200 × 800 |
| Pixel count | 8,640,000 | 960,000 |
| Masked/void pixels | 0 | 0 |
| Sample minimum | -20.632 m | -11.670 m |
| Sample maximum | 60.502 m | 57.135 m |

Resampling GLO-30 bilinearly to the GLO-90 native grid produced 960,000
comparisons:

- mean absolute difference: `0.0794 m`;
- root mean square difference: `0.2228 m`;
- 95th percentile absolute difference: `0.4211 m`;
- 99th percentile absolute difference: `0.9662 m`;
- maximum absolute difference: `7.1168 m`;
- source-byte ratio: `8.53×`;
- pixel-count ratio: `9×`;
- measured local resampling wall time: `0.121 s` on the inspection machine.

Negative values are valid EGM2008-referenced heights in this sample and are
not treated as voids by magnitude. The sample contains no nodata mask.

One low-lying window and no independent vertical truth cannot select a
production resolution. GLO-90 materially reduces storage and browser delivery,
while the local maximum difference is material relative to sea-level-change
classes. `productionChoice` therefore remains `pending-scientific-review`.

Machine evidence:
[`dem-netherlands-n52-e004.json`](../../src/pipeline/science/evidence/dem-netherlands-n52-e004.json).

Primary evidence:

- [Copernicus DEM product page](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)
- [AWS Open Data registry entry](https://registry.opendata.aws/copernicus-dem/)

## Vertical compatibility decision

The two inputs do not currently share a demonstrated vertical reference:

- AR6: relative sea-level **change** from a historical baseline, in millimetres;
- Copernicus DEM: absolute orthometric DSM **height** in EGM2008, in metres.

Multiplying AR6 millimetres by `0.001` only reconciles units. It does not create
an absolute future water-surface elevation. Publication remains blocked until
the project pins and reviews:

1. a local baseline mean-sea-level or tidal surface;
2. its vertical datum and transformation to EGM2008;
3. spatial interpolation and uncertainty for that baseline;
4. controls showing the combined vertical uncertainty is fit for the selected
   class resolution.

## Europe and coastal geometry QA

The current fixtures remain `approximation`. They are checksum-bound to Natural
Earth 5.1.1 inputs and explicit parameters in `geography-rules.json`.

The Europe support candidate uses 50 Natural Earth features matching
`CONTINENT == 'Europe' AND NAME != 'Russia'`, clips to
`(-30, 30, 45, 75)`, and retains the historical degree buffer and
simplification only for migration parity. Metric coastal operations use
EPSG:3035. The coastal candidate buffers the Natural Earth ocean by 25,000 m,
intersects support, then derives WGS84 output.

Measured fixture QA:

| Measure | Europe support | Coastal approximation |
|---|---:|---:|
| Valid | yes | yes |
| Components | 237 | 240 |
| Area | 5,990,331.79 km² | 1,183,211.91 km² |
| Perimeter | 74,925.06 km | 97,783.46 km |

All 19 named controls pass, covering ports, estuaries, lagoons, islands,
inland low terrain, Russia, Turkey, territories, and outside-Europe points.
The explicit predicate is `covers`: a derived boundary control is covered but
not contained.

The QA also found two reasons not to promote the historical fixtures:

- a deterministic rebuild with the current toolchain differs from the old
  fixture by 655.01 km² for support and 2,019.66 km² for the coastal zone;
- after historical independent rounding, 290.96 km² of coastal fragments lie
  outside support, so strict `support.covers(coastal)` is false.

The accepted Copernicus Coastal Zones comparison cannot be performed: the
source registry has no checksum-locked downloadable asset, rights/scientific
role review is incomplete, and the publisher labels V1-2018 not yet validated.
No claim is substituted for that missing evidence.

Machine evidence:
[`geometry-approximation-qa.json`](../../src/pipeline/science/evidence/geometry-approximation-qa.json).

## Connectivity candidate

The comparison alternative is `ocean-connected-eight-neighbour-v1`:

- seeds are eligible cells intersecting pinned ocean geometry at the analysis
  boundary;
- traversal uses edge or corner adjacency;
- nodata and ineligible cells are barriers;
- disconnected eligible cells are reported separately;
- unfiltered and connected counts must both be retained for review.

The implementation is deterministic and tested for diagonal connection,
nodata barriers, and disconnected inland basins. It is a comparison candidate,
not an approved physical flood model.

## Remaining external gates

The implementation and evidence are complete as a blocking Phase 0 result.
These decisions require authority or source access outside the repository:

- scientific/data reviewer approval of AR6 mapping and datum interpretation;
- product-owner approval of supported geography;
- SHA-256 lock and direct schema inspection of the regional projection archive;
- reviewed local sea-surface/tidal datum transformation to EGM2008;
- production DEM resolution decision using more representative windows and
  independent controls;
- checksum-locked, rights-reviewed canonical coastal asset;
- scientific approval or replacement of the connectivity rule;
- resolution of geometry rebuild parity and coastal-outside-support topology.

Until those gates close, no default may describe Phase 0.2 or the binary
exposure methodology as approved.
