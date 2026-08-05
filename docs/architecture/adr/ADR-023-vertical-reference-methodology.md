# ADR-023 — Vertical-reference methodology

> **Status:** Accepted for acquisition and validation; publication blocked
>
> **Decision result:** `accepted`
>
> **Decision date:** 2026-08-05
>
> **Decision owner:** Project owner
>
> **Required reviewer:** Independent scientific/data reviewer (`pending`)
>
> **Evidence:** [Phase 0.5 methodology decision](../../science/phase-0-5-vertical-methodology-evidence.md), [Phase 0.7 implementation evidence](../../science/phase-0-7-vertical-reconciliation-evidence.md)

## Decision

Adopt `absolute-mean-water-surface-egm2008-interval-v1` as the only vertical
methodology allowed to proceed to source acquisition and validation.

Construct a duration-weighted 1995–2014 baseline from Copernicus Marine
European L4 absolute dynamic topography, transform its documented GOCO06S
geoid reference to tide-free EGM2008, add AR6 relative change, and compare an
uncertainty interval with EGM2008 Copernicus DSM elevation. Ambiguous or
unsupported cells return `DataUnavailable`; they cannot become binary `0` or
`1`.

This decision supersedes the direct comparison in ADR-015 and the affected
candidate-method language in ADR-021/ADR-022. It does not approve a source
snapshot, executed numeric transform, DEM resolution, coastal scope,
connectivity algorithm, classified layer, release, or Phase 1.

## Binding model

```text
B_EGM2008 = mean_1995_2014(ADT_GOCO06S)
            + N_GOCO06S_tide_free - N_EGM2008_tide_free

W_q = B_EGM2008 + 0.001 * AR6_q

C_low  = (B_EGM2008 - U_B) + 0.001 * AR6_q17 - (Z_DSM_EGM2008 + U_Z)
C_high = (B_EGM2008 + U_B) + 0.001 * AR6_q83 - (Z_DSM_EGM2008 - U_Z)
```

- `C_low >= 0` and approved connectivity passes:
  `ModeledExposureDetected`.
- `C_high < 0`, or vertical eligibility with approved connectivity rejection:
  `NoModeledExposureDetected`.
- Otherwise: `DataUnavailable` / `uncertain-threshold`.
- Missing input, uncertainty bound, support, or required interpolation
  neighbour: `DataUnavailable` with a specific reason.

The complete variable meanings, interpolation, reference periods, physical
scope, and uncertainty components are binding in
[`vertical-methodology.json`](../../../src/pipeline/science/vertical-methodology.json).

## Rationale

The selected family is the only inspected option that:

- preserves the required AR6 scenarios and horizons;
- supplies an observed absolute baseline with an exact route to the AR6
  1995–2014 reference period;
- makes the GOCO06S/EGM2008 difference and permanent-tide convention visible;
- retains Copernicus DEM while accounting for vertical and DSM error;
- supports conservative uncertainty without adding a sixth domain state;
- can be acquired, checksum-locked, processed offline, and reproduced.

European/local tidal datums are valuable validation controls but do not form a
demonstrated continuous, consistently transformed surface for the complete
scope. Inspected JRC hazard products use different scenarios, horizons,
hazards, and output semantics. Neither can silently replace the product
contract.

## Consequences

Positive:

- Direct `AR6 change >= absolute DEM` remains prohibited.
- The reference epoch is exact rather than an undocumented offset.
- Datum and permanent-tide transformations are explicit.
- Projection spread stays distinct from mapping/terrain error.
- Ambiguous cells fail closed in the existing five-state contract.

Costs and limitations:

- Several sizeable source families and gravity-model computations must be
  pinned and validated.
- Conservative DEM/DSM bounds may produce many ambiguous cells; that is a
  scientific result, not permission to shrink uncertainty.
- Mean-water exposure excludes tides, surge, waves, drainage, defences, and
  river/pluvial flooding.
- Connectivity and terrain resolution remain separate Phase 0.8 decisions.
- Exact coastal coverage may block this strategy and trigger the documented
  MSS or published-hazard fallback.

Phase 0.7 implements the exact AR6 interval, complete baseline aggregation,
geoid adapter boundary, explicit absolute-bound aggregation, interval
classifier, and deterministic transformation receipt. The adapter will not
call an external harmonic engine unless both models' evaluation constants and
one common engine/ellipsoid/tide policy are locked. The checked-in receipt is
therefore evidence of a blocked implementation, not evidence of a numerical
GOCO06S-to-EGM2008 result.

## Gate and review

The strategy decision is accepted, but no independent scientific/data reviewer
has reviewed this project's cross-product equation. The machine gate remains
`blocked` on:

- `vertical-methodology-review`;
- `validated-vertical-transform`;
- `terrain-and-connectivity-controls`.

`validated-vertical-transform` specifically includes the pending EGM2008
constants and engine policy, numeric QUID/terrain bounds, Baltic and Black Sea
controls, cross-environment reproducibility, and independent scientific/data
review.

Phase 1 remains blocked. CI success, source download, or code completion cannot
substitute for the named review and validation evidence.

## Rollback and replacement

If source inspection shows that ADT is not tied to the documented GOCO06S
reference, the tide conversion is not reproducible, coastal coverage is
insufficient, uncertainty prevents useful classifications, or independent
controls fail, stop the build. Write a superseding ADR selecting the direct-MSS
fallback or a contract-changing validated hazard product. Do not return to the
legacy direct comparison.

## Subsequent Phase 0.8 evidence

[Phase 0.8](../../science/phase-0-8-terrain-geography-controls.md) selects
GLO-30 and an eight-neighbour ocean-seeded connectivity screen for external
review. It also decomposes `U_Z` into random, systematic, edit/fill,
DSM-representation, and resolution terms. The systematic, edit/fill, DSM, and
resolution terms remain unbounded, and neither the terrain nor connectivity
selection has external approval. The original publication block therefore
remains in force even though the implementation choices are now explicit.
