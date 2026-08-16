# AR6 Regional Projection Methodology

> **Status:** Projection lookup, source parity, and Phase 0R release gate approved
> **Last reviewed:** 2026-08-16
> **Decision source:** [ADR-024](architecture/adr/ADR-024-ar6-regional-projection-contract.md), within [ADR-021](architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)
> **Machine contract:** [`ar6-projection-contract.json`](../src/pipeline/science/ar6-projection-contract.json)
> **Release gate:** [`final-gate.json`](../src/pipeline/evidence/ar6-regional-release/owner-promotion/final-gate.json) records automated validation passed, zero blockers, and owner `releaseDisposition=approved`
> **Phase 1:** `CLOSED`; the private final Candidate remains local-only
> **Historical reconciliation evidence:** [Phase 0.7 vertical reconciliation evidence](science/phase-0-7-vertical-reconciliation-evidence.md) — superseded binary-method investigation
> **Historical input evidence:** [Phase 0.6 vertical source evidence](science/phase-0-6-vertical-source-evidence.md) — retained audit evidence, not the active method
> **Canonical document:** `docs/methodology.md`

## Purpose

The active method reports three values directly from the locked IPCC AR6
regional projection source: `q0.167`, `q0.5`, and `q0.833`. Values are converted
from millimetres to metres and remain relative to the 1995–2014 mean. They form
AR6's medium-confidence likely range; SeaRise Europe does not add a terrain,
datum, or cross-source uncertainty model.

For map and point results, the method uses only source-native 1° grid locations.
Point lookup chooses the geometrically nearest grid location with unrounded
haversine distance, a fixed `6371.0088 km` Earth radius, a `100 km` maximum,
and lowest-location-ID tie-break. It never interpolates, falls back to a tide
gauge, or skips source nodata in favour of a farther cell. Reported distance is
rounded to six decimal places after selection.

An available result shows the median, likely range, scenario, horizon,
baseline, source location and distance, native resolution, method, and source
release. The product says explicitly that this is regional relative sea-level
change, not flooding, inundation, terrain exposure, or property risk.

The [offline #135 goldens](../src/pipeline/science/evidence/ar6-lookup-goldens.json)
bind the full archive, all three members, the lookup and decision contracts,
both scope geometries, and the independent generator. Seven regional points
cover the four required basins, an island, two estuaries, and a high-latitude
port. Each has all nine scenario/horizon combinations and all three source
quantiles: 189 source values in total. Two further points prove `OutOfScope`
and `UnsupportedGeography` precedence.

The independent `netCDF4` reader preserves exact integer source millimetres;
the production `xarray` reader reproduced every value within the predeclared
`0.000001 m` tolerance. TypeScript reproduces the integer millimetres, source
location identity, six-decimal distance, states, nodata, maximum-distance, and
tie-break semantics bit-exactly. An exhaustive search across 154 source-grid
locations covered by the versioned coastal scope in all three members found no
real in-scope nodata location, so the required nodata path remains a declared
synthetic mutation control rather than a manufactured real-source golden.

The NASA/Rutgers IPCC AR6 Sea Level Projection Tool is a supplementary manual
cross-check only, not the CI oracle. Automated source/implementation parity for
#135 passed, and #110 subsequently recorded trusted dual-platform evidence plus
the separate project-owner approval that opened Phase 1.

The hash-bound `ar6-projection-contract.json` is the accepted pre-run decision
snapshot. Its `publicationGate` therefore still records `automatedValidation`
as `pending` and lists #135 with #110; those fields are not the final release
gate or the current #135 evidence status. Issue #110 owns the measured final
gate and records the separate owner-controlled release disposition.

The remainder of this document preserves the v1 binary investigation and why
it was not publishable. It is historical evidence, not an alternative active
method.

## Historical binary-method evidence (superseded)

Everything below this heading records the rejected v1 terrain-comparison
investigation. It is retained for audit only. It is not product guidance, an
implementation alternative, a rollback baseline, or an allowed target-domain
contract. ADR-024 and the active method above are authoritative.

The investigated method is `absolute-mean-water-surface-egm2008-interval-v1`.
It constructs
the 1995–2014 mean water surface in EGM2008 metres, adds AR6 relative change,
and compares a complete likely/error interval with the Copernicus DSM:

```text
ADT_GOCO06S(t) = SLA_monthly(t) + MDT_GOCO06S
B_E = mean_1995_2014(ADT_GOCO06S) + N_GOCO06S_tide_free - N_EGM2008_tide_free

C_low  = (B_E - U_B) + 0.001 * AR6_q17 - (Z_E + U_Z)
C_high = (B_E + U_B) + 0.001 * AR6_q83 - (Z_E - U_Z)
```

Provisional output semantics after the approved connectivity filter:

| Value | Domain state | Meaning |
|:---:|---|---|
| `1` | `ModeledExposureDetected` | `C_low >= 0` and the approved ocean-connectivity rule passes |
| `0` | `NoModeledExposureDetected` | `C_high < 0`, or a vertically eligible cell is rejected by the approved connectivity rule |
| nodata | `DataUnavailable` | The interval crosses zero, or required source, error, transformation, coverage, or connectivity evidence is unavailable |

The lookup uses nearest-neighbour class semantics. Rendered map colours are not
scientific values; the browser reads the exact classification artifact.

### Historical fixed dimensions

| Dimension | Values |
|---|---|
| Scenario | `ssp1-26`, `ssp2-45`, `ssp5-85` |
| Horizon | `2030`, `2050`, `2100` |
| Default | `ssp2-45`, `2050` |
| Required layer matrix | 3 scenarios × 3 horizons = 9 layers |

Phase 0.2 fixed the median source variable mapping. ADR-023 adds the exact
0.167/0.500/0.833 source coordinates for interval decisions. Phase 0.6
confirmed them in each SHA-256-locked regional member; scientific/data review
of their implemented use remains required.

### Historical source candidates

| Role | Candidate source | Required release evidence |
|---|---|---|
| Sea-level projection | IPCC AR6 projections distributed by the NASA Sea Level Change Team | Exact record/version, files, variables, units, quantile, location/grid model, licence, acknowledgements, SHA-256 |
| Baseline water surface | Copernicus Marine `008_068` monthly `sla` plus static European `008_070` `mdt`, calendar-day weighted over 1995–2014 | Exact dataset/version/files, complete interval, `err_mdt` and QUID error evidence, coverage, licence, attribution, SHA-256 |
| Source geoid | GOCO06S used by European MDT `008_070` | Exact coefficients, zero-tide metadata, reference epoch, normalization, evaluation software, error bound, licence, SHA-256 |
| Target geoid | NGA EGM2008 / EPSG:3855 | Exact coefficients or grid, tide-free convention, ellipsoid, interpolation, propagated error, terms, SHA-256 |
| Terrain | Copernicus DEM GLO-30 release `2021_1`, selected for external review | Exact DEM/EDM/FLM/HEM/WBM assets, reference semantics, licence, attribution, SHA-256, and independently bounded error terms |
| Coastal scope | Natural Earth 5.1.1 ocean-derived 25 km product scope, selected for external review after Copernicus Coastal Zones comparison | Geometry version, processing recipe, topology QA, controls, and product-owner approval |
| Europe support | Explicit 50-feature Natural Earth 5.1.1 `ADM0_A3` allow-list | Country/territory rule, fixed clip/tolerance, topology QA, controls, and product-owner approval |

Raw inputs are acquired once per release into a local or CI cache. They are not
served to normal site visitors. The release manifest records all inputs and
published derivatives.

### Historical Phase 0.2 gate result

[Phase 0.2 evidence](science/phase-0-2-source-and-geography-evidence.md)
established these binding implementation facts:

- IPCC AR6 version `20210809`, variable `sea_level_change`;
- total medium-confidence values at exact quantile `0.5`;
- exact years `2030`, `2050`, and `2100`;
- flattened explicit one-degree grid locations, not an assumed raster;
- millimetres converted to metres by `0.001`;
- bilinear interpolation only inside the native coordinate coverage;
- no extrapolation or nodata bridging;
- Copernicus DEM release `2021_1` is an EGM2008-referenced DSM;
- current support/coastal geometry remains `approximation` and uses `covers`.

The gate also established that the candidate formula cannot currently be
evaluated scientifically. AR6 supplies relative sea-level change from the
1995–2014 baseline; Copernicus DEM supplies absolute orthometric height.
Converting units does not provide the missing baseline water surface or datum
transformation. The pipeline therefore fails before producing a binary exposure
raster. The legacy direct comparison is disabled, including for synthetic or
migration callers.

### Historical Phase 0.5 strategy result

[Phase 0.5 evidence](science/phase-0-5-vertical-methodology-evidence.md)
selected a reproducible route through the mismatch:

1. lock European Copernicus Marine monthly `sla`, derive `adt = sla + mdt`
   with the locked static MDT, and calendar-day weight the exact 1995–2014
   interval;
2. transform the documented GOCO06S geoid reference to EGM2008 only after
   reconciling zero-tide and tide-free conventions;
3. add AR6 relative change on its matching 1995–2014 baseline;
4. compare the AR6 likely range and conservative non-projection bounds with
   EGM2008 DSM height;
5. return `DataUnavailable` / `uncertain-threshold` when the interval crosses
   zero, and require approved connectivity before emitting exposure.

The relationship to EGM2008 is an explicit transformation hypothesis, not an
assumed equivalence. It remains blocked until exact inputs and independent
controls validate the numerical chain. No independent project reviewer has
yet approved or rejected it.

### Historical Phase 0.6 input result

[Phase 0.6 evidence](science/phase-0-6-vertical-source-evidence.md) locks the
full AR6 archive and exact scenario members, all 240 monthly SLA objects, the
static MDT with `err_mdt`, GOCO06S and EGM2008 coefficients, and five-layer
GLO-30/GLO-90 terrain controls. The official monthly product is a simple mean
of daily L4 SLA, so calendar-day weighting plus the static MDT reconstructs the
selected daily-ADT mean without changing its statistic.

This closes source identity, licensing, and coverage evidence. It does not
close numerical transformation, uncertainty-bound, DEM selection, or
independent-review gates.

### Historical Phase 0.7 implementation result

[Phase 0.7 evidence](science/phase-0-7-vertical-reconciliation-evidence.md)
implements and tests the deterministic parts of the selected method:

- exact `0.167`, `0.5`, and `0.833` AR6 extraction bound to the locked scenario
  member and verified member SHA-256;
- a complete 240-month, 7305-calendar-day baseline plus static MDT;
- a geoid-evaluator boundary that rejects changed model degree/order,
  normalization, GM, radius, ellipsoid, engine version, tide output, or
  conversion evidence;
- conservative absolute-bound aggregation with no missing term treated as
  zero;
- interval classification with stable nodata reason codes and required
  connectivity for positive exposure;
- a deterministic evidence-receipt schema binding software, sources, members,
  grid/reference semantics, equations, uncertainty provenance, outputs, and
  residual blockers.

At the Phase 0.7 boundary, the checked-in receipt intentionally recorded no
classified artifacts. EGM2008 evaluation constants and a versioned
evaluator/tide rule are not yet locked;
QUID-derived and terrain bounds are not approved; the target grid, affine,
terrain, and connectivity controls were still pending; and Baltic/Black Sea,
cross-environment, and independent-review evidence was absent. Those conditions
produced `DataUnavailable` or stopped the build rather than guessed values.

### Historical Phase 0.8 terrain and scope result

[Phase 0.8 evidence](science/phase-0-8-terrain-geography-controls.md) selects
GLO-30 after comparing five GLO-30/GLO-90 coastal windows with their EDM, FLM,
HEM, and WBM layers. GLO-30 retains materially more narrow-coast and island
detail, reports a lower p95 HEM sigma in every window, and has near-threshold
differences in every window. This is resolution-selection evidence, not
independent elevation truth.

Terrain now fails closed through explicit terms:

```text
U_Z = U_random + U_systematic + U_edit + U_DSM + U_resolution
```

Only `U_random = 1.645 × HEM` is defined for a valid, unedited pixel. The
systematic, edit/fill, DSM-representation, and resolution terms require
independent bounds and never default to zero. The Copernicus product-level
“less than 4 m LE90” target is not treated as a per-pixel bound.

The same phase versions an explicit 50-feature Europe allow-list, the 25 km
Natural Earth-derived product scope, the `covers` boundary predicate, and an
eight-neighbour ocean-seeded connectivity screen. Twenty-seven named-place
geography controls and nine symbolic connectivity controls pass. External
product/scientific review remains mandatory, and the connectivity screen is
not a hydraulic model.

### Historical Phase 0.9 final gate result

[Phase 0.9 evidence](evidence/phase-0-9-regional-gate.md) records the Phase 0.9
disposition as `BLOCKED`; the Phase 0 scientific gate remains blocked. The
reproducible preflight covers all three
scenarios and all three horizons with exact scenario-member hashes and complete
shared lineage. All nine attempts stop before array creation on the same seven
named evidence gaps.

No scientific classes, statistics, connectivity comparison, reviewed parity
vectors, COGs, PMTiles, or GeoParquet were generated. This is not an all-nodata
release: it is the absence of a scientifically authorized release. Source-lock
and automated tests pass, but automation is explicitly unable to authorize the
methodology, product scope, connectivity control, or Phase 1.

The corrected Phase 0.9 record is immutable historical evidence. Issues
[#94](https://github.com/artemsemdev/SeaRise-Europe/issues/94) through
[#97](https://github.com/artemsemdev/SeaRise-Europe/issues/97) subsequently
recorded their evidence without manufacturing approval. Issue
[#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98) then performed
the terminal v1 re-evaluation recorded in Phase 0.14.

### Historical Phase 0.11 uncertainty-budget result

The [machine-readable Phase 0.11 budget](../src/pipeline/science/coastal-uncertainty-budget.json)
calibrates every selected non-projection term at a common 90% interpretation
and keeps the AR6 `0.167`/`0.833` interval separate. It derives a conservative
`0.0981413 m` SLA mapping term from the worst European QUID variance plus the
documented two-altimeter degradation, uses `1.645 × err_mdt` per valid MDT
cell, and retains the GLO-30 `4 m` product LE90 as an envelope rather than
double-counting it with `1.645 × HEM`.

That calibration does not make the binary method publishable. The SLA QUID
gives an open-ended coastal error range without a cell mapping, while GLO-30
is a DSM and supplies neither a bare-earth correction nor a finite maximum
building/vegetation bias. Edited/fill, shoreline, and effective-resolution
terms also lack independent truth bounds. Since those terms apply to the
intended coastal land result, they become `DataUnavailable`; a maximum-total
threshold is deliberately absent because it cannot repair missing evidence.

The resulting automated recommendation is `rejected`, as required by #95 when
the selected binary method is indefensible. This is not an authoritative
reviewed rejection: the human disposition remains `pending` and the
publication gate remains `blocked` until an independent scientific/data
reviewer records it. The v1 method is superseded for publication; its evidence
remains historical input to the recovery decision.

### Historical Phase 0.14 terminal no-go

[Phase 0.14 evidence](evidence/phase-0-14-final-no-go.md) records three distinct
states that must not be collapsed:

- the Phase 0 investigation is `complete-with-no-go`;
- the #95 automated methodology recommendation is `rejected`;
- the authoritative scientific and release disposition is `blocked` because
  no independent reviewer has approved or rejected the method.

All nine scenario/horizon attempts stopped before arrays. No classes, COGs,
PMTiles, GeoParquet, statistics, release receipt, or synthetic substitute were
created. At that historical gate, Phase 1 remained locked.

The original recovery plan through #107–#109 was superseded when ADR-024
removed the absolute-water and terrain comparison. Recovery through #135 and
#110 is complete. CI recorded automated validation; the project owner separately
set the release decision that unlocked
[#48](https://github.com/artemsemdev/SeaRise-Europe/issues/48).

### Historical v1 required preprocessing record

Before approval, the pipeline must record and test:

- source coordinate representation and transformation to the analysis grid;
- horizontal CRS and vertical datum/reference for both projection and terrain;
- exact ADT/MDT, GOCO06S, and EGM2008 reference surfaces and tide conventions;
- duration-weighted 1995–2014 baseline construction and missing-interval rule;
- projection units and conversion to terrain-elevation units;
- exact 0.167/0.500/0.833 projection coordinates and q17/q50/q83 UI wording;
- separate baseline, datum/tide, interpolation, DEM, and DSM uncertainty bounds;
- spatial interpolation used for a continuous projection field;
- nearest-neighbour handling for binary output;
- DEM aggregation/resampling and its effect on small coastal features;
- nodata propagation;
- coastal-zone masking;
- mandatory approved coastline-connectivity filtering after the vertical test;
- numerical precision and deterministic software/container versions.

The former claim that AR6 is a regular approximately 0.25-degree raster is
rejected. The pinned location list proves a complete one-degree grid stored on
the same flattened location dimension as tide gauges. The exact transformation
is enforced in code and tests. Direct archive/member inspection is complete;
review of the implemented interval transform remains a publication gate.

### Historical coastal-analysis scope

The checked-in v2 geometry is a deterministic 25 km inland band derived from
pinned Natural Earth 5.1.1 inputs. It includes a fixed EPSG:3035 recipe,
explicit Europe/territory allow-list, declared coastline tolerance, topology
invariants, and independent named-place controls. It defines product
eligibility only; it does not mean that sea-level effects extend 25 km inland.

Copernicus Coastal Zones V1-2018 was compared and not selected as flood-reach
or connectivity geometry. Its published 10 km inland extent is a
land-cover/land-use mapping scope derived from EU-Hydro and is officially
marked “not yet validated.” The 25 km approximation is therefore retained for
external product-owner review, not promoted as a canonical hazard boundary.

`OutOfScope` means the selected location is inside supported Europe but outside
this versioned product boundary. `UnsupportedGeography` means it is outside the
versioned Europe support geometry.

### Historical limitations

The [Phase 0.3 regional evidence](evidence/phase-0-regional-fixture.md)
records why the legacy comparison, connectivity, scientific goldens, nine
classified layers, and PMTiles were blocked. ADR-023 selects a replacement
vertical design, and Phase 0.7 characterizes its fail-closed mechanics, but
does not close the numerical or review gates.

Unless validation produces a materially different method, the UI and manifest
must disclose at least:

1. The approved connectivity screen is not a hydraulic flow model and does not
   model all barriers or pathways.
2. Flood defences and adaptation infrastructure are not represented.
3. Storm surge, tide, waves, drainage, and compound flooding are not included.
4. Do not double-count the vertical-land-motion contribution in AR6 total;
   local anthropogenic subsidence absent from the exact source remains outside
   the method.
5. Copernicus DEM is a digital surface model and may include vegetation and
   structures.
6. Source and output resolution do not support property-level conclusions.
7. A `0` is not a safety determination.
8. A `1` is not a prediction that flooding will occur.

### Historical v1 interpretation record

#### Historical `ModeledExposureDetected`

The selected point meets the candidate model condition for the chosen scenario
and horizon. It is a screening result, not a flood forecast, probability, or
property assessment.

#### Historical `NoModeledExposureDetected`

The selected point does not meet the candidate model condition for the chosen
scenario and horizon. This is not a safety determination and does not evaluate
all flood mechanisms.

#### Historical v1 `DataUnavailable`

A required source value, uncertainty bound, transformation, connectivity
decision, or validated artifact is unavailable, or the complete interval
crosses the threshold. The application does not substitute or infer a class.

### Historical v1 scientific test set

The approval suite contains:

- known coastal low/high elevation points across Atlantic, Baltic,
  Mediterranean, Adriatic, and North Sea contexts;
- exposed and non-exposed expectations reviewed against the source arrays;
- explicit nodata points;
- cell-edge and tile-edge coordinates;
- coastal-zone boundary points;
- disconnected low-lying inland candidates that exercise the principal static
  model limitation;
- points in ports, estuaries, lagoons, islands, and steep coastlines;
- independently calculated coordinate-to-row/column fixtures shared with the
  TypeScript client.

Every release records the test-set version and result summary in
`manifest.json`. A failed golden point blocks publication.

### Historical v1 approval conditions

These conditions explain why v1 did not pass. They are retained for audit, not
as a route to revive ADR-023. The recovery issues must define and approve a new
versioned contract. Methodology `v1.0` would have required all of the following:

- exact real source snapshots and licences are recorded;
- the IPCC dimensional/coordinate assumption is confirmed or replaced;
- the ADT/GOCO06S/EGM2008 reference surfaces, tide conversion, epoch, and unit
  conversions are implemented and independently validated;
- one representative region is reproduced end to end;
- Python output and browser lookup are bit-exact on the golden fixtures;
- connected-inundation false positives are reviewed and accepted or mitigated;
- all nine layer combinations pass array, COG, and PMTiles QA;
- a domain reviewer approves the interpretation and limitations;
- every AR6, baseline, datum/tide, interpolation, DEM, and DSM uncertainty term
  has a reviewed bound and ambiguous cells fail closed;
- DEM resolution, Europe/territory scope, canonical coastal evidence, and
  connectivity have explicit approvals;
- the signed release manifest links this exact methodology revision.

Any future classification rule belongs to methodology v2 and a superseding
ADR. Do not edit the v1 evidence or interpretation in place.

### Methodology version history

| Candidate version | Date | State | Change |
|---|---|---|---|
| `v1.0` | 2026-04-03 | Proposed | Initial binary comparison |
| `v1.0` | 2026-08-04 | Provisional | Added real-data, datum, connectivity, provenance, and browser-parity approval gates |
| `v1.0` | 2026-08-05 | Blocked | Phase 0.2 replaced source heuristics and stopped direct AR6-change versus EGM2008-height publication |
| `v1.0` | 2026-08-05 | Blocked | Phase 0.3 found no reviewed AR6-baseline-to-EGM2008 reconciliation; no classification release generated |
| `v1.0` | 2026-08-05 | Selected; publication blocked | ADR-023 selected the 1995–2014 ADT/GOCO06S-to-EGM2008 interval method; exact inputs, validation, controls, and independent review remain open |
| `v1.0` | 2026-08-05 | Inputs locked; publication blocked | Phase 0.6 pinned the exact AR6, SLA/MDT, GOCO06S, EGM2008, and terrain-control evidence; implementation and review remain open |
| `v1.0` | 2026-08-05 | Mechanics implemented; publication blocked | Phase 0.7 added the fail-closed interval implementation and receipt; numerical conventions, bounds, controls, reproducibility, and review remain open |
| `v1.0` | 2026-08-05 | Controls selected; publication blocked | Phase 0.8 selected fail-closed GLO-30 terrain, explicit Europe/25 km product scope, and eight-neighbour ocean connectivity; independent approvals and terrain bounds remain open |
| `v1.0` | 2026-08-05 | Phase 0.9 completed; scientific gate blocked | Phase 0.9 attempted all nine exact combinations, emitted no scientific artifacts, and recorded seven unresolved evidence gates; Phase 0 and Phase 1 remain blocked |
| `v1.0` | 2026-08-05 | Phase 0 complete with no-go; publication superseded | Phase 0.14 preserved the authoritative `BLOCKED` state, recorded the automated `REJECTED` recommendation, emitted no release artifacts, and routed future work through #106–#110 |
| `v2.0` | 2026-08-10 | Recovery approved; Phase 1 open | ADR-024 replaced binary exposure with source-native AR6 q0.167/q0.5/q0.833 reporting; #135 parity and the trusted, owner-approved #110 release gate passed. |
