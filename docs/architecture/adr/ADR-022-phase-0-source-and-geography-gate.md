# ADR-022 — Phase 0 Source and Geography Gate

> **Status:** Proposed; enforced as a publication safety gate pending named approvals
> **Decision date:** 2026-08-05
> **Decision owner:** Project owner, scientific/data reviewer, and product owner
> **Scope:** AR6 semantics, vertical reference, DEM grid, Europe support,
> coastal scope, connectivity, and boundary predicates
> **Evidence:** [Phase 0.2 source and geography evidence](../../science/phase-0-2-source-and-geography-evidence.md) and [Phase 0.8 terrain, geography, and connectivity controls](../../science/phase-0-8-terrain-geography-controls.md)

## 1. Decision

SeaRise Europe will stop the legacy binary exposure build by default. The
inspected sources do not yet support a scientifically defensible comparison of
relative sea-level change with absolute EGM2008 DSM elevation.

The repository adopts fail-closed machine contracts for every resolved or
pending interpretation:

- [`source-semantics.json`](../../../src/pipeline/science/source-semantics.json)
  is the only allowed mapping for IPCC AR6 version `20210809` and Copernicus
  DEM release `2021_1`;
- [`geography-rules.json`](../../../src/pipeline/science/geography-rules.json)
  versions the current support/coastal approximations, controls, predicate,
  and connectivity comparison rule;
- unexpected variables, dimensions, units, coordinates, grids, assets, or
  checksums fail rather than selecting a fallback;
- mechanics-only tests may opt into the blocked methodology explicitly, but
  those outputs cannot be published or described as validated.

This ADR accepts the **stop decision and evidence contract**. Phase 0.8 selects
supported-geography, coastal-product-scope, connectivity, and DEM candidates
for external review; it does not claim that the required reviewers approved
them or that the terrain uncertainty is complete.

## 2. Binding decision log

| Question | Decision | State and next authority |
|---|---|---|
| Projection asset | Zenodo record `6382554`, version `20210809`, regional confidence archive | Archive SHA-256 and direct schema inspection remain blocking |
| Variable | `sea_level_change` from total medium-confidence value files | Enforced; scientific/data review pending |
| Statistic | Exact quantile `0.5`; no nearest fallback | Enforced; scientific/data review pending |
| Units | Source `mm`, multiply by exactly `0.001` to metres | Enforced |
| Coordinate model | Select IDs `>= 1,000,000,000`; validate and reshape explicit complete 1° lat/lon coordinates | Enforced and tested |
| Interpolation | Bilinear for the continuous change field, inside native coverage only; required nodata neighbours propagate | Enforced and tested |
| Vertical datum | Unit conversion is insufficient; an approved baseline water surface and transformation to EGM2008 are absent | **Blocked**; scientific/data reviewer required |
| DEM resolution | GLO-30 selected after five DEM/EDM/FLM/HEM/WBM windows; nine times the pixels and 8.06 times the five-layer source bytes | Selected for external scientific review; independent truth and full error bounds remain blocking |
| Target grid | Exact pinned GLO-30 grid with PixelIsPoint semantics and quality layers; no implicit legacy grid | Selected for external scientific review |
| Europe rule | Explicit 50-feature Natural Earth 5.1.1 `ADM0_A3` allow-list, fixed clip, EPSG:3035 coastline tolerance, and deterministic serialization | Selected-scope approximation; product-owner approval required |
| Russia and Turkey | Excluded by the current candidate; no silent whole-country inclusion | Product-owner approval required |
| Territories | Azores/Madeira/Faroe and named in-clip islands included; Canary Islands, Svalbard, and out-of-clip overseas territories excluded | Product-owner approval required |
| Coastal rule | Natural Earth ocean buffered 25 km in EPSG:3035 and intersected with support; product eligibility only | Selected-scope approximation; not a flood-reach claim; product-owner approval required |
| Canonical coastal evidence | Copernicus Coastal Zones V1-2018 is an open 10 km inland land-cover scope with “not yet validated” status | Compared and rejected as flood-reach/connectivity geometry; external review required |
| Connectivity | Eight-neighbour ocean-seeded traversal after the vertical interval; nodata/uncertain/rejected-quality cells are barriers; mosaic before traversal | Selected for external scientific review; nine mechanism controls pass |
| Boundary predicate | Use `covers`, so boundary points are included | Enforced and tested |

No unresolved row is converted into a default. Release metadata must expose
the state of every row that affects a result.

## 3. Context

The legacy implementation selected possible variable names, chose the first
data variable as a fallback, used nearest years and quantiles, assumed a 2-D
regular raster, and inferred millimetres from value magnitude. It then compared
the result directly with a DSM.

The exact source documentation and pinned samples show why that is unsafe:

- AR6 regional NetCDF stores tide gauges and grid points on one flattened
  `locations` dimension;
- the grid is one degree, not the documented legacy `~0.25°` assumption;
- AR6 values are relative change from 1995–2014;
- Copernicus DEM is absolute EGM2008-referenced DSM height;
- GLO-30/GLO-90 storage, angular spacing, and local values differ materially;
- current geography files are historical approximations with measurable
  rebuild and topology differences;
- the intended Copernicus coastal evidence is not a reviewed locked input.

Continuing the binary build would make an unresolved datum assumption appear
scientifically authoritative merely because the software is deterministic.

## 4. Alternatives considered

| Option | Decision |
|---|---|
| Keep legacy guesses for compatibility | Rejected; reproducible guessing is still scientifically wrong |
| Convert AR6 millimetres to metres and compare directly with DEM | Rejected; unit conversion does not reconcile relative change with absolute orthometric height |
| Select GLO-30 because it has more pixels | Rejected as a rationale; the later selection also requires five-window HEM, mask/detail, threshold, and delivery evidence |
| Select GLO-90 because it is smaller | Rejected without coastal-feature and independent-control evidence |
| Promote current geometry because controls pass | Rejected; approvals, canonical comparison, rebuild parity, and topology remain open |
| Treat `contains` and `covers` as interchangeable | Rejected; boundary outcomes differ |
| Stop publication while preserving explicit mechanics fixtures | Accepted |

## 5. Consequences

Positive consequences:

- source schema drift fails immediately;
- every projection statistic and conversion is reviewable;
- the invalid direct vertical comparison cannot run accidentally;
- regional spikes can reuse one contract across Python and browser fixtures;
- geometry and connectivity differences become measured evidence rather than
  undocumented implementation choices.

Costs and limitations:

- Phase 0 cannot approve the binary methodology today;
- the nine-gigabyte AR6 archive requires a reviewed SHA-256 acquisition path;
- a baseline sea-surface/tidal product and vertical transformation are new
  required inputs;
- independent vertical controls and complete systematic/edit/DSM/resolution bounds are required;
- product and scientific reviewers must decide the open geography rows;
- the existing fixtures remain useful only as explicitly approximate migration
  and performance fixtures.

## 6. Verification and promotion criteria

This ADR can move from `Proposed` only when:

1. a scientific/data reviewer approves the AR6 mapping and datum treatment;
2. the regional projection archive is SHA-256 locked and the exact member
   schema report matches the contract;
3. a local baseline water surface and EGM2008 transformation are pinned,
   reproduced, and uncertainty-tested;
4. an independent reviewer accepts or changes the GLO-30 selection and every
   systematic/edit/DSM/resolution uncertainty term is bounded;
5. the product owner approves transcontinental and territory outcomes;
6. the product owner accepts or changes the documented Natural Earth/Copernicus
   Coastal Zones comparison and 25 km eligibility scope;
7. connectivity and boundary semantics receive scientific review;
8. the rebuilt v2 geometry and 27 controls receive product-owner approval;
9. the real-source regional fixture passes without the blocked-methodology
   override.

If evidence invalidates the binary formula, ADR-015 must be superseded rather
than weakening this gate.

## 7. Rollback

The safety gate may be reverted mechanically, but doing so does not restore a
scientific basis for publication. The legitimate rollback is to retain the
legacy implementation only for synthetic characterization while all public
release paths remain disabled.
