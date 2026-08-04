# ADR-022 — Phase 0 Source and Geography Gate

> **Status:** Proposed; enforced as a publication safety gate pending named approvals
> **Decision date:** 2026-08-05
> **Decision owner:** Project owner, scientific/data reviewer, and product owner
> **Scope:** AR6 semantics, vertical reference, DEM grid, Europe support,
> coastal scope, connectivity, and boundary predicates
> **Evidence:** [Phase 0.2 source and geography evidence](../../science/phase-0-2-source-and-geography-evidence.md)

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

This ADR accepts the **stop decision and evidence contract**. It does not
approve the candidate scientific methodology, supported geography, coastal
product, connectivity algorithm, or production DEM resolution.

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
| DEM resolution | GLO-30 is 9× the pixels and 8.53× the source bytes in the inspected window; one window has no independent truth | **Pending** representative evidence and scientific review |
| Target grid | Must be the approved DEM grid; no implicit legacy grid | **Pending** DEM resolution decision |
| Europe rule | Natural Earth 5.1.1 Europe filter excluding Russia, clipped to migration bounds | `approximation`; product-owner approval required |
| Russia and Turkey | Excluded by the current candidate; no silent whole-country inclusion | Product-owner approval required |
| Territories | Azores included; Canary Islands and out-of-clip French territories excluded | Product-owner approval required |
| Coastal rule | Natural Earth ocean buffered 25 km in EPSG:3035 and intersected with support | `approximation`; not a flood-reach claim |
| Canonical coastal source | Copernicus Coastal Zones V1-2018 cannot be selected without a locked asset, rights review, and scientific-role review | **Blocked** |
| Connectivity | Compare eight-neighbour ocean-seeded flood fill; nodata is a barrier | Candidate only; scientific review required |
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
| Select GLO-30 because it has more pixels | Rejected without representative accuracy and delivery evidence |
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
- additional DEM windows and independent vertical controls are required;
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
4. GLO-30/GLO-90 evidence covers representative coastal terrain and
   independent controls, then records one production choice;
5. the product owner approves transcontinental and territory outcomes;
6. a canonical coastal asset is locked and compared, or an alternative is
   approved explicitly;
7. connectivity and boundary semantics receive scientific review;
8. rebuilt geometry resolves parity/topology findings and passes the control
   corpus;
9. the real-source regional fixture passes without the blocked-methodology
   override.

If evidence invalidates the binary formula, ADR-015 must be superseded rather
than weakening this gate.

## 7. Rollback

The safety gate may be reverted mechanically, but doing so does not restore a
scientific basis for publication. The legitimate rollback is to retain the
legacy implementation only for synthetic characterization while all public
release paths remain disabled.
