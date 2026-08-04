# Provisional Exposure Methodology — v1.0 Candidate

> **Status:** Provisional; not approved for a real-data public release
> **Last reviewed:** 2026-08-04
> **Decision sources:** ADR-015, amended by [ADR-021](architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)
> **Blocking gate:** Phase 0 scientific validation in ADR-021
> **Canonical document:** `docs/methodology.md`

## Purpose

This document specifies the current candidate methodology and the evidence
needed before it can become a published methodology version. The repository has
unit-tested processing modules and synthetic demonstration data, but it has not
validated this method end to end against the exact real IPCC and Copernicus
source products.

No UI, README, or portfolio page may describe methodology `v1.0` as validated
until every approval condition in this document passes.

## Candidate classification

The candidate is a binary static-screening method. For a grid cell inside the
versioned coastal analysis zone:

```text
exposed = projected_mean_sea_level_rise >= terrain_elevation
```

Provisional output semantics:

| Value | Domain state | Meaning |
|:---:|---|---|
| `1` | `ModeledExposureDetected` | Candidate method finds projected mean sea-level rise greater than or equal to terrain elevation |
| `0` | `NoModeledExposureDetected` | Candidate method does not find that condition |
| nodata | `DataUnavailable` | Outside source coverage, outside the analysis mask, or required source data is missing |

The lookup uses nearest-neighbour class semantics. Rendered map colours are not
scientific values; the browser reads the exact classification artifact.

## Fixed product dimensions

| Dimension | Values |
|---|---|
| Scenario | `ssp1-26`, `ssp2-45`, `ssp5-85` |
| Horizon | `2030`, `2050`, `2100` |
| Default | `ssp2-45`, `2050` |
| Required layer matrix | 3 scenarios × 3 horizons = 9 layers |

The source variable and quantile that correspond to each product dimension
must be confirmed from the actual source metadata, not inferred from filenames
or an assumed raster layout.

## Source candidates

| Role | Candidate source | Required release evidence |
|---|---|---|
| Sea-level projection | IPCC AR6 projections distributed by the NASA Sea Level Change Team | Exact record/version, files, variables, units, quantile, location/grid model, licence, acknowledgements, SHA-256 |
| Terrain | Copernicus DEM GLO-30 or GLO-90 | Product edition, resolution choice, horizontal/vertical reference, nodata, licence, modified-product attribution, SHA-256 |
| Coastal scope | Current Natural Earth-derived 25 km approximation, to be compared with Copernicus Coastal Zones | Geometry version, source, processing recipe, distance rule, topology QA, comparison decision |
| Europe support | Natural Earth-derived support geometry | Explicit country/territory rule, clipping, source version, topology QA |

Raw inputs are acquired once per release into a local or CI cache. They are not
served to normal site visitors. The release manifest records all inputs and
published derivatives.

## Required preprocessing record

Before approval, the pipeline must record and test:

- source coordinate representation and transformation to the analysis grid;
- horizontal CRS and vertical datum/reference for both projection and terrain;
- projection units and conversion to terrain-elevation units;
- selected statistic/quantile and why it matches the UI wording;
- spatial interpolation used for a continuous projection field;
- nearest-neighbour handling for binary output;
- DEM aggregation/resampling and its effect on small coastal features;
- nodata propagation;
- coastal-zone masking;
- optional coastline-connectivity screening;
- numerical precision and deterministic software/container versions.

The existing claim that AR6 is a regular approximately 0.25-degree grid is an
unverified assumption. Phase 0 must inspect the real dataset; location-based
projection dimensions require a documented transformation or interpolation
method before publication.

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

Unless validation produces a materially different method, the UI and manifest
must disclose at least:

1. Static comparison does not model water flow, barriers, or hydraulic
   connectivity.
2. Flood defences and adaptation infrastructure are not represented.
3. Storm surge, tide, waves, drainage, and compound flooding are not included.
4. Subsidence and uplift are not included unless the chosen IPCC variable and
   processing explicitly account for them.
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

A required source value or validated artifact is unavailable. The application
does not substitute or infer a class.

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
- vertical references and unit conversions are documented;
- one representative region is reproduced end to end;
- Python output and browser lookup are bit-exact on the golden fixtures;
- connected-inundation false positives are reviewed and accepted or mitigated;
- all nine layer combinations pass array, COG, and PMTiles QA;
- a domain reviewer approves the interpretation and limitations;
- the signed release manifest links this exact methodology revision.

If any condition changes the classification rule, create methodology `v1.1` or
a superseding ADR rather than editing a released version in place.

## Version history

| Candidate version | Date | State | Change |
|---|---|---|---|
| `v1.0` | 2026-04-03 | Proposed | Initial binary comparison |
| `v1.0` | 2026-08-04 | Provisional | Added real-data, datum, connectivity, provenance, and browser-parity approval gates |
