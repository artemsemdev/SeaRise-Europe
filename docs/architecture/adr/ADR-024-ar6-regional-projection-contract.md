# ADR-024 — AR6 regional projection product contract

> **Status:** Accepted
>
> **Decision date:** 2026-08-05
>
> **Decision owner:** Project owner
>
> **Implementation state:** Contract and #135 lookup parity implemented; publication remains blocked on #110 trusted evidence and owner disposition
>
> **Machine contract:** [`ar6-projection-contract.json`](../../../src/pipeline/science/ar6-projection-contract.json)
>
> **Historical evidence:** [ADR-023](ADR-023-vertical-reference-methodology.md), [Phase 0.14 no-go](../../evidence/phase-0-14-final-no-go.md)

## Decision

SeaRise Europe will publish **IPCC AR6 regional relative sea-level projection**
values and will not classify terrain exposure, flooding, inundation, or property
risk.

For one supported scenario and horizon, `ProjectionAvailable` reports:

- median projected regional relative sea-level change (`q0.5`);
- the published medium-confidence likely range (`q0.167`–`q0.833`);
- metres relative to the 1995–2014 mean baseline;
- the selected source-grid location, its coordinates, and its distance from the
  requested point;
- the scenario, horizon, source release, method version, and native 1°
  resolution.

The product does not construct an absolute water surface, compare projection
with terrain, or derive a new cross-source uncertainty interval. The likely
range is the range published in the pinned AR6 dataset, not a flood
probability or property-level confidence statement.

## Product states

The target browser contract has exactly four domain states:

1. `ProjectionAvailable` — all three required AR6 quantiles exist at the
   selected grid location.
2. `DataUnavailable` — the selected grid location is beyond the maximum
   distance, or any required quantile is source `nodata`.
3. `OutOfScope` — the point is inside supported Europe but outside the
   versioned coastal product zone.
4. `UnsupportedGeography` — the point is outside the versioned Europe support
   polygon.

`ProjectionAvailable` replaces both legacy binary exposure outcomes. The
historical `ModeledExposureDetected` and `NoModeledExposureDetected` states do
not appear in a release governed by this ADR.

## Source binding

The contract uses the already locked IPCC AR6 Sea Level Projections release:

- Zenodo DOI `10.5281/zenodo.6382554`, version `20210809`, CC BY 4.0;
- source variable `sea_level_change`, stored in millimetres and published in
  metres with an exact `0.001` scale;
- medium-confidence `q0.167`, `q0.5`, and `q0.833`;
- scenarios `ssp1-26`, `ssp2-45`, and `ssp5-85`;
- horizons `2030`, `2050`, and `2100`;
- baseline `1995–2014 mean`;
- the source-native complete 181 × 360 grid represented by location IDs at or
  above `1000000000`.

Low-confidence projections and the approximately 1,030 tide-gauge locations
are outside this product contract. The source archive and scenario-member
hashes remain authoritative in the source lock and source-semantics contract.

## Spatial lookup

Map and point results use the same source-native 1° grid family.

For an in-scope point, the point lookup:

1. computes haversine distance to source-grid locations using the fixed mean
   Earth radius `6371.0088 km`;
2. selects the geometrically nearest grid location using unrounded distance,
   resolving an exact tie by the lowest source location ID;
3. returns `DataUnavailable/source-location-too-distant` when the distance is
   greater than `100 km`;
4. reads `q0.167`, `q0.5`, and `q0.833` at that one location;
5. returns `DataUnavailable/source-value-nodata` if any required value is the
   source fill value.

The reported source distance is rounded to six decimal places only after
selection. Rounding never participates in location choice or the 100 km gate.

The lookup must not search for a more distant non-nodata cell, interpolate,
extrapolate, or fall back to a tide-gauge location. Those behaviours would add
project-defined spatial semantics that the source does not publish and could
make the map and point result disagree.

The 100 km cap is a product guardrail around the native 1° grid, not a claim of
100 km scientific precision. Every result discloses the actual source distance
and native resolution.

## Validation and approval

Validation is offline and source-bound:

- #135 records a predeclared golden set for all nine scenario/horizon
  combinations, the four named European basin contexts, nodata, scope, and
  boundary cases;
- expected values are extracted from the SHA-256-locked NetCDF members with an
  independent reader and stored with source location IDs and provenance;
- Python and TypeScript must agree on state, source location, and numeric
  values within an absolute tolerance of `0.000001 m` and zero relative
  tolerance;
- schema, source hash, dimensional, unit, quantile, and baseline checks run
  before value comparison.

The NASA/Rutgers tool and published reader may support a documented manual
cross-check, but a mutable or unavailable web interface is not a CI oracle.
CI may report `automatedValidation=passed`; it cannot set the owner-controlled
release disposition or describe the product as approved. The machine-contract
snapshot names this authority `releaseDecision`; measured release artifacts
record the same boundary as `releaseDisposition`.

## Superseded decisions

This ADR supersedes:

- ADR-010's five-state result model;
- the binary assessment and exposure-specific sections of ADR-021;
- ADR-023 as a publication path;
- the active use of terrain, coastal mean-water, geoid reconciliation,
  connectivity, and cross-source uncertainty in the target product.

ADR-021 remains authoritative for the static-first runtime, immutable open
artifacts, local search, offline behaviour, provenance, hosting, and
performance budgets. ADR-023 and all Phase 0 evidence remain immutable records
of the rejected binary publication path.

## Consequences

Positive consequences:

- the displayed quantity comes directly from one locked, licensed dataset;
- no relative-to-absolute datum conversion is performed;
- map and point results share one spatial source family;
- the published uncertainty wording is preserved without manufacturing an
  additional interval;
- the release remains static, reproducible, backend-free, and auditable.

Limitations:

- native resolution is 1°, so a precise marker does not imply precise local
  modelling;
- values are regional relative sea-level projections, not observed local
  water levels;
- projections do not include a project-specific flood model, elevation,
  defences, tides, surge, waves, drainage, erosion, or river/pluvial flooding;
- grid-only lookup may return `DataUnavailable` where the selected source cell
  is nodata; a farther or tide-gauge value is never silently substituted.

## Delivery and rollback

Implementation proceeds in dependency order:

1. #135 implements and independently reproduces the grid-only lookup.
2. #110 lands the reviewed builder and fixed workflows on `master`, then builds
   and measures the nine regional projection layers on pinned Linux and macOS
   ARM64 runners.
3. An evidence-only pull request binds those trusted artifacts to the exact
   source commit before the protected owner workflow records the disposition.
4. #48 may unlock Phase 1 only after the owner records an approved release
   disposition with all automated evidence passing and immutable decision
   records committed.

Rollback means keeping the projection release unpublished. It never means
reviving the direct AR6-versus-terrain comparison or rewriting historical
evidence.

## Acceptance criteria

- The machine contract validates and is loaded with the other science
  decisions.
- Active architecture, product, methodology, risk, delivery, and changelog
  documents point to this ADR and the four-state contract.
- Tests reject tide-gauge fallback, interpolation, nodata substitution, changed
  source identity, weakened disclosure, or CI-as-approver semantics.
- #135 evidence is implemented; #110 remains blocking until trusted release
  evidence and the owner disposition exist. This decision alone does not unlock
  Phase 1 or authorize publication.
