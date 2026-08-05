# Phase 0.7 Vertical Reconciliation Evidence

> **Issue:** [#83](https://github.com/artemsemdev/SeaRise-Europe/issues/83)
>
> **Recorded:** 2026-08-05
>
> **Implementation:** Complete for the fail-closed computational contract
>
> **Scientific publication gate:** `BLOCKED`

## Result

The repository now implements the deterministic mechanics selected by
ADR-023. It does not claim that the GOCO06S-to-EGM2008 numerical transform or
a release classification is scientifically validated.

The legacy `sea_level_change >= DEM` operation has no remaining opt-in. Any
caller of that path receives a scientific-contract error before inputs are
opened or outputs are written.

## Implemented contracts

- AR6 interval extraction requires the exact source coordinates `0.167`,
  `0.5`, and `0.833`, a scenario-specific locked member identity, and its
  independently verified member SHA-256.
- Baseline reconstruction requires every continuous month from January 1995
  through December 2014 exactly once. It weights all 240 monthly SLA fields by
  their 7305 calendar days, adds the static MDT, and propagates per-cell nodata.
- The geoid adapter binds GOCO06S and EGM2008 archive/member hashes and requires
  a versioned evaluator to echo the ellipsoid, tide output, model degree/order,
  normalization, GM, radius, and conversion evidence.
- Non-projection uncertainty is a conservative sum of explicit absolute metre
  bounds. A missing term, missing provenance, invalid spatial rule, negative
  bound, or unavailable total-uncertainty policy fails closed.
- Classification uses the documented lower/central/upper clearances. Ambiguous
  intervals and incomplete evidence remain nodata with stable reason codes;
  positive exposure additionally requires approved connectivity.

## Deterministic receipt

The machine receipt at
`src/pipeline/science/evidence/vertical-transformation-implementation.json` is
validated against a closed JSON Schema and hashed from canonical sorted JSON.
It records:

- contract, source-asset, and archive-member SHA-256 values;
- local runtime and package versions plus the absent external geoid engine;
- baseline interval, object-count, day-weight, and missing-period semantics;
- horizontal and vertical CRS, grid/affine/pixel state, interpolation,
  extrapolation, and nodata rules;
- geoid model degree/order, normalization, GM/radius, epoch, and tide state;
- every uncertainty term's units, provenance, spatial handling, aggregation,
  and bound status;
- output/artifact absence, validation state, and exact residual blockers.

Changing any recorded evidence changes the canonical receipt digest. A receipt
cannot become `publishable` unless it has generated hashed artifacts, complete
bounds and a total-uncertainty limit, locked grid/geoid state, no blockers, and
all automated, basin, cross-environment, and independent checks passed.

## Residual blockers

No output raster or release artifact was generated because all of the following
remain required:

1. Lock EGM2008 evaluation GM/radius, a common ellipsoid, a versioned harmonic
   evaluator, and the reviewed zero-tide-to-tide-free rule.
2. Pin QUID-derived SLA mapping evidence and approve all baseline, datum,
   interpolation, terrain, DSM, and maximum-total uncertainty bounds.
3. Complete external review of the Phase 0.8 GLO-30, coastal-scope, and
   connectivity candidates; bound the remaining terrain terms; and lock the
   Phase 0.9 regional mosaic shape and affine.
4. Validate independent controls in the Baltic and Black Sea.
5. Reproduce the transform and receipts in an approved second environment.
6. Record independent scientific/data reviewer approval.

Until those items pass, unsupported or incomplete cells are
`DataUnavailable`, the transformation receipt is not publishable, and Phase 1
remains blocked.
