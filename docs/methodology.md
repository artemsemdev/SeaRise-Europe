# Blocked Uncertainty-Aware Exposure Methodology — v1.0 Candidate

> **Status:** Blocked; not approved for a real-data public release
> **Last reviewed:** 2026-08-05
> **Decision sources:** [ADR-023](architecture/adr/ADR-023-vertical-reference-methodology.md), within [ADR-021](architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md) and the [ADR-022](architecture/adr/ADR-022-phase-0-source-and-geography-gate.md) safety gate
> **Blocking gate:** Phase 0.5 selected the vertical strategy; inputs, implementation, terrain/connectivity controls, and independent review remain blocking
> **Latest evidence:** [Phase 0.5 vertical methodology](science/phase-0-5-vertical-methodology-evidence.md) — strategy `accepted`, publication `blocked`
> **Canonical document:** `docs/methodology.md`

## Purpose

This document specifies the selected candidate methodology and the evidence
needed before it can become a published methodology version. The strategy is
binding for acquisition and validation, but the repository has not implemented
or independently reviewed it against the exact real source snapshots.

No UI, README, or portfolio page may describe methodology `v1.0` as validated
until every approval condition in this document passes.

## Selected classification

The method is `absolute-mean-water-surface-egm2008-interval-v1`. It constructs
the 1995–2014 mean water surface in EGM2008 metres, adds AR6 relative change,
and compares a complete likely/error interval with the Copernicus DSM:

```text
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

## Fixed product dimensions

| Dimension | Values |
|---|---|
| Scenario | `ssp1-26`, `ssp2-45`, `ssp5-85` |
| Horizon | `2030`, `2050`, `2100` |
| Default | `ssp2-45`, `2050` |
| Required layer matrix | 3 scenarios × 3 horizons = 9 layers |

Phase 0.2 fixed the median source variable mapping. ADR-023 adds the exact
0.17/0.50/0.83 quantiles for interval decisions. Their presence still requires
direct inspection of the SHA-256-locked regional archive and scientific/data
review before use.

## Source candidates

| Role | Candidate source | Required release evidence |
|---|---|---|
| Sea-level projection | IPCC AR6 projections distributed by the NASA Sea Level Change Team | Exact record/version, files, variables, units, quantile, location/grid model, licence, acknowledgements, SHA-256 |
| Baseline water surface | Copernicus Marine `SEALEVEL_EUR_PHY_L4_MY_008_068` `adt`, duration-weighted over 1995–2014 | Exact dataset/version/files, `adt`/`sla`/error variables, complete interval, coverage, licence, attribution, SHA-256 |
| Source geoid | GOCO06S used by European MDT `008_070` | Exact coefficients, zero-tide metadata, reference epoch, normalization, evaluation software, error bound, licence, SHA-256 |
| Target geoid | NGA EGM2008 / EPSG:3855 | Exact coefficients or grid, tide-free convention, ellipsoid, interpolation, propagated error, terms, SHA-256 |
| Terrain | Copernicus DEM GLO-30 or GLO-90 | Product edition, resolution choice, horizontal/vertical reference, nodata, licence, modified-product attribution, SHA-256 |
| Coastal scope | Current Natural Earth-derived 25 km approximation, to be compared with Copernicus Coastal Zones | Geometry version, source, processing recipe, distance rule, topology QA, comparison decision |
| Europe support | Natural Earth-derived support geometry | Explicit country/territory rule, clipping, source version, topology QA |

Raw inputs are acquired once per release into a local or CI cache. They are not
served to normal site visitors. The release manifest records all inputs and
published derivatives.

## Phase 0.2 gate result

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
transformation. The pipeline therefore fails by default before producing a
binary exposure raster. Synthetic and migration tests must opt into the
blocked methodology explicitly.

## Phase 0.5 strategy result

[Phase 0.5 evidence](science/phase-0-5-vertical-methodology-evidence.md)
selected a reproducible route through the mismatch:

1. build an exact 1995–2014 mean from European Copernicus Marine `adt`;
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

## Required preprocessing record

Before approval, the pipeline must record and test:

- source coordinate representation and transformation to the analysis grid;
- horizontal CRS and vertical datum/reference for both projection and terrain;
- exact ADT/MDT, GOCO06S, and EGM2008 reference surfaces and tide conventions;
- duration-weighted 1995–2014 baseline construction and missing-interval rule;
- projection units and conversion to terrain-elevation units;
- 0.17/0.50/0.83 projection quantiles and UI wording;
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
is enforced in code and tests; direct archive inspection and review remain
publication gates.

## Coastal analysis scope

The checked-in geometry is a 25 km inland band derived from Natural Earth. It
is an engineering approximation that includes ports/estuaries omitted by the
coarse source shoreline. It defines product eligibility only; it does not mean
that sea-level effects extend 25 km inland.

Before release, compare it with the canonical Copernicus coastal product and
record one of these decisions:

1. replace the approximation;
2. retain it with quantitative evidence and an explicit methodology version;
3. build a new connectivity-aware scope geometry.

`OutOfScope` means the selected location is inside supported Europe but outside
this versioned product boundary. `UnsupportedGeography` means it is outside the
versioned Europe support geometry.

## Known limitations

The [Phase 0.3 regional evidence](evidence/phase-0-regional-fixture.md)
records why the legacy comparison, connectivity, scientific goldens, nine
classified layers, and PMTiles were blocked. ADR-023 selects a replacement
vertical design but does not close those implementation and review gates.

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

## User-facing interpretation contract

### Modeled exposure detected

The selected point meets the candidate model condition for the chosen scenario
and horizon. It is a screening result, not a flood forecast, probability, or
property assessment.

### No modeled exposure detected

The selected point does not meet the candidate model condition for the chosen
scenario and horizon. This is not a safety determination and does not evaluate
all flood mechanisms.

### Data unavailable

A required source value, uncertainty bound, transformation, connectivity
decision, or validated artifact is unavailable, or the complete interval
crosses the threshold. The application does not substitute or infer a class.

## Scientific test set

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

## Approval conditions

Methodology `v1.0` may change from `provisional` to `approved` only when:

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

If any condition changes the classification rule, create methodology `v1.1` or
a superseding ADR rather than editing a released version in place.

## Version history

| Candidate version | Date | State | Change |
|---|---|---|---|
| `v1.0` | 2026-04-03 | Proposed | Initial binary comparison |
| `v1.0` | 2026-08-04 | Provisional | Added real-data, datum, connectivity, provenance, and browser-parity approval gates |
| `v1.0` | 2026-08-05 | Blocked | Phase 0.2 replaced source heuristics and stopped direct AR6-change versus EGM2008-height publication |
| `v1.0` | 2026-08-05 | Blocked | Phase 0.3 found no reviewed AR6-baseline-to-EGM2008 reconciliation; no classification release generated |
| `v1.0` | 2026-08-05 | Selected; publication blocked | ADR-023 selected the 1995–2014 ADT/GOCO06S-to-EGM2008 interval method; exact inputs, validation, controls, and independent review remain open |
