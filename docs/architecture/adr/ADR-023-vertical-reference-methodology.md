# ADR-023 — Vertical-reference methodology

> **Status:** Superseded as a publication path; historical validation decision retained
>
> **Historical decision result:** `accepted` for acquisition and validation
>
> **Current result:** Phase 0 `complete-with-no-go`; automated publication recommendation `rejected`; authoritative scientific disposition `blocked`
>
> **Decision date:** 2026-08-05
>
> **Decision owner:** Project owner
>
> **Required reviewer:** Independent scientific/data reviewer (`pending`)
>
> **Evidence:** [Phase 0.5 methodology decision](../../science/phase-0-5-vertical-methodology-evidence.md), [Phase 0.7 implementation evidence](../../science/phase-0-7-vertical-reconciliation-evidence.md), [Phase 0.9 historical gate](../../evidence/phase-0-9-regional-gate.md), [Phase 0.14 final no-go](../../evidence/phase-0-14-final-no-go.md)

## Current disposition

Phase 0.14 completed the investigation without a publishable scientific
result. Issue #95 found that the pinned evidence cannot provide finite bounds
for coastal SLA representativeness or GLO-30 DSM-to-bare-earth error. Its
automated recommendation is therefore `rejected`. Because independent review
is still pending, the authoritative scientific and release disposition remains
`blocked`; automation cannot turn that state into a human rejection.

This ADR remains the immutable explanation of the v1 acquisition and
validation path. Phase 0.14 started recovery at
[#106](https://github.com/artemsemdev/SeaRise-Europe/issues/106); ADR-024 later
accepted the replacement projection method, and the owner-approved Phase 0R
gate opened Phase 1 without changing this v1 no-go.

## Decision

The historical decision adopted
`absolute-mean-water-surface-egm2008-interval-v1` as the only vertical
methodology allowed to proceed to source acquisition and validation.

Construct a duration-weighted 1995–2014 baseline by deriving absolute dynamic
topography as `adt = sla + mdt` from the locked Copernicus Marine European L4
`008_068` monthly `sla` source and locked `008_070` static MDT. Transform the
MDT's documented GOCO06S geoid reference to tide-free EGM2008, add AR6 relative
change, and compare an uncertainty interval with EGM2008 Copernicus DSM
elevation. Ambiguous or unsupported cells return `DataUnavailable`; they
cannot become binary `0` or `1`.

This decision supersedes the direct comparison in ADR-015 and the affected
candidate-method language in ADR-021/ADR-022. It does not approve a source
snapshot, executed numeric transform, DEM resolution, coastal scope,
connectivity algorithm, classified layer, release, or Phase 1.

## Binding model

```text
ADT_GOCO06S(t) = SLA_monthly(t) + MDT_GOCO06S
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

## Historical rationale

At the time of selection, this family was the only inspected option that:

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
- Phase 0.8 selects connectivity and terrain-resolution candidates, but their
  external reviews and terrain uncertainty bounds remain open.
- Exact coastal coverage may block this strategy and trigger the documented
  MSS or published-hazard fallback.

Terminal consequence:

- The locked evidence confirmed that mandatory coastal water and bare-earth
  terrain terms are unbounded for the binary product. The method may remain in
  tests and evidence for reproducibility, but it cannot produce a release.
- No threshold, all-nodata layer, synthetic substitute, or successful CI run
  may convert the no-go into a scientific class.
- Future publication requires the new contract and evidence chain
  #106 → (#107, #108) → #109 → #110.

Phase 0.7 implements the exact AR6 interval, complete baseline aggregation,
geoid adapter boundary, explicit absolute-bound aggregation, interval
classifier, and deterministic transformation receipt. The adapter will not
call an external harmonic engine unless both models' evaluation constants and
one common engine/ellipsoid/tide policy are locked. The checked-in receipt is
therefore evidence of a blocked implementation, not evidence of a numerical
GOCO06S-to-EGM2008 result.

## Gate and review

The historical acquisition/validation decision was accepted, but no independent
scientific/data reviewer has reviewed this project's cross-product equation.
The final v1 machine gate is terminal `complete-with-no-go`; its authoritative
scientific and release disposition remains `blocked` on independent review and
finite source-backed uncertainty evidence.

The original gate was blocked on:

- `vertical-methodology-review`;
- `validated-vertical-transform`;
- `terrain-uncertainty-bounds-and-control-reviews`.

`validated-vertical-transform` specifically includes the pending EGM2008
constants and engine policy, numeric QUID/terrain bounds, Baltic and Black Sea
controls, cross-environment reproducibility, and independent scientific/data
review.

At this historical decision point, Phase 1 remained locked. CI success, source
download, or code completion could not substitute for the named review and
validation evidence.

## Rollback and replacement

The stop condition has fired: uncertainty prevents defensible binary
classification with the pinned coastal SLA and GLO-30 DSM evidence. Keep the
build stopped and do not return to the legacy direct comparison.

Recovery follows this dependency order:

1. [#106](https://github.com/artemsemdev/SeaRise-Europe/issues/106) selects a
   post-no-go scientific product contract and produces the superseding ADR.
2. [#107](https://github.com/artemsemdev/SeaRise-Europe/issues/107) validates a
   datum-safe coastal mean-water reference while
   [#108](https://github.com/artemsemdev/SeaRise-Europe/issues/108) validates
   bare-earth coastal terrain.
3. [#109](https://github.com/artemsemdev/SeaRise-Europe/issues/109) implements
   and independently reviews methodology v2 from approved inputs.
4. [#110](https://github.com/artemsemdev/SeaRise-Europe/issues/110) rebuilds
   the regional proof and records the recovery gate.

This was superseded by the #106 → #135 → #110 recovery actually completed
under ADR-024. Its independently verified, owner-approved #110 gate unlocked
[#48](https://github.com/artemsemdev/SeaRise-Europe/issues/48); the v1 outcome
in this ADR remains a valid no-go and authorizes no release.

## Subsequent Phase 0.8 evidence

[Phase 0.8](../../science/phase-0-8-terrain-geography-controls.md) selects
GLO-30 and an eight-neighbour ocean-seeded connectivity screen for external
review. It also decomposes `U_Z` into random, systematic, edit/fill,
DSM-representation, and resolution terms. The systematic, edit/fill, DSM, and
resolution terms remain unbounded, and neither the terrain nor connectivity
selection has external approval. The original publication block therefore
remains in force even though the implementation choices are now explicit.

## Final Phase 0.9 disposition

Phase 0.9 attempted all nine scenario/horizon combinations with exact lineage
and returned `BLOCKED` before array creation. It produced no scientific classes
or release artifacts. The final gate additionally names missing reviewed golden
vectors and product, connectivity, cross-environment, Baltic, and Black Sea
evidence. ADR-023 remained the selected candidate methodology at that
historical boundary, but Phase 1 was not authorized. The corrected Phase 0.9
evidence remains immutable.

## Phase 0.14 final disposition

[#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98) completed the v1
investigation as `complete-with-no-go`. The automated recommendation is
`rejected`, while the authoritative disposition remains `blocked` pending
independent review. No scientific arrays or release artifacts were generated.
ADR-023 is therefore superseded for publication, not retroactively erased or
relabelled as an independently reviewed rejection.
