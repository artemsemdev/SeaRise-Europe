# Phase 0.9 Regional Scientific Gate

> **Issue:** [#85](https://github.com/artemsemdev/SeaRise-Europe/issues/85)
>
> **Decision date:** 2026-08-05
>
> **Final decision:** `BLOCKED`
>
> **Phase 1:** `BLOCKED`

## Decision

Phase 0.9 completed with a valid `BLOCKED` disposition. The Phase 0 scientific
gate remains blocked. The repository attempted all nine required
scenario/horizon combinations with exact locked lineage, but every attempt
stopped during scientific preflight before an array was created.
No scientific `0` or `1`, analysis COG, visual PMTiles, GeoParquet, statistics,
or release receipt was emitted.

This report supersedes the decision for the current gate only. It does not
rewrite the historical [Phase 0.3 evidence](phase-0-regional-fixture.md), whose
bytes remain referenced by SHA-256 in the new attempt record.

## Nine-combination attempt

| Scenario | AR6 member | Horizon | Outcome |
|---|---|---:|---|
| `ssp1-26` | `ssp126-medium-total` | 2030 | blocked before array |
| `ssp1-26` | `ssp126-medium-total` | 2050 | blocked before array |
| `ssp1-26` | `ssp126-medium-total` | 2100 | blocked before array |
| `ssp2-45` | `ssp245-medium-total` | 2030 | blocked before array |
| `ssp2-45` | `ssp245-medium-total` | 2050 | blocked before array |
| `ssp2-45` | `ssp245-medium-total` | 2100 | blocked before array |
| `ssp5-85` | `ssp585-medium-total` | 2030 | blocked before array |
| `ssp5-85` | `ssp585-medium-total` | 2050 | blocked before array |
| `ssp5-85` | `ssp585-medium-total` | 2100 | blocked before array |

Each row records the exact projection archive/member SHA-256, source scenario,
year, `0.167/0.5/0.833` quantiles, units and interpolation contract. Shared
lineage records the 240-month/7305-day SLA baseline, MDT, GOCO06S and EGM2008
members, selected GLO-30 five-layer manifest, geography assets, uncertainty
terms, connectivity contract, and software versions.

No synthetic scientific input was substituted. The attempt used locked
metadata to perform preflight and did not open unavailable payloads after the
gate failed.

## Evidence disposition

| Required evidence | Result |
|---|---|
| Source identities and integrity | locked and verified |
| Project source-registry redistribution evidence | every used source is marked `approved` in the project registry; independent data/licence review remains pending |
| Nine scientific arrays and statistics | not generated |
| Uncertainty/fail-closed counts | unavailable because no array exists |
| Connectivity pre/post comparison | not run because no vertical classes exist |
| Reviewed controls and golden vectors | unavailable |
| Python/TypeScript parity | not run; no approved vectors or arrays |
| COG QA | no analysis COGs generated |
| PMTiles/GeoParquet QA | no artifacts generated |
| Build time, peak memory, range locality and browser latency | not measured for a scientific release |
| Scientific/data review | pending |
| Product-scope/connectivity review | pending |
| Engineering and cross-environment review | pending |

Passing unit tests, schemas, source integrity, or CI cannot change those
results to approval. Automation is recorded as evidence, never as the reviewer
or product-owner decision.

## Exact blockers

1. `egm2008-evaluator-conventions` —
   [#94](https://github.com/artemsemdev/SeaRise-Europe/issues/94) must lock
   EGM2008 GM/radius, the common ellipsoid,
   a versioned harmonic evaluator, and the zero-tide-to-tide-free rule, then
   secure their review.
2. `numerical-uncertainty-bounds` —
   [#95](https://github.com/artemsemdev/SeaRise-Europe/issues/95) must provide
   QUID-derived baseline bounds, remaining
   geoid/tide/interpolation and terrain/DSM bounds, and the maximum-total policy
   that are currently incomplete.
3. `independent-scientific-data-review` — no independent methodology,
   uncertainty, licence, or engineering approval record exists;
   [#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98) must require
   it before deciding the gate.
4. `baltic-black-sea-controls` —
   [#96](https://github.com/artemsemdev/SeaRise-Europe/issues/96) must provide
   independent Baltic and Black Sea controls.
5. `product-scope-connectivity-approval` — the Phase 0.8 geography and
   connectivity candidates have not received their required approvals;
   [#97](https://github.com/artemsemdev/SeaRise-Europe/issues/97) must review
   them.
6. `cross-environment-reproducibility` —
   [#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98) must reject
   approval unless an approved second environment reproduces the numerical
   transform and artifacts.
7. `reviewed-golden-vectors` —
   [#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98) must reject
   approval unless independently authored and approved vectors cover all five
   states, boundaries, longitude handling, and nodata.

## Gate invariant and next decision

The machine gate permits Phase 1 only for an explicit `approved` decision with
zero blockers, all nine combinations complete, hashed arrays and delivery
artifacts present, and every named review approved with evidence. `blocked` and
`rejected` always keep `unlocksPhase1=false`.

The follow-up order is fixed: resolve
[#94](https://github.com/artemsemdev/SeaRise-Europe/issues/94) geoid
conventions, [#95](https://github.com/artemsemdev/SeaRise-Europe/issues/95)
uncertainty bounds, [#96](https://github.com/artemsemdev/SeaRise-Europe/issues/96)
basin controls, and [#97](https://github.com/artemsemdev/SeaRise-Europe/issues/97)
scope/connectivity review. Then
[#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98) is the sole
future final-gate re-evaluation and the only issue that may unlock Phase 1.
The corrected #85 gate and evidence are historical and must not be overwritten
by #98. This sequence is not permission to generate all-nodata layers, revive
the direct AR6 change-versus-DEM comparison, accept CI as a reviewer, or start
Phase 1.

## Reproducibility

From the repository root:

```bash
PYTHONPATH=src/pipeline .venv/bin/python scripts/science/build_phase_0_9_attempt.py
sha256sum src/pipeline/science/evidence/phase-0-9-regional-attempt.json
```

The expected attempt SHA-256 is
`9e158807a36cc5f445f0fecb955975dabb5119496d680063a724b18743524636`.
Tests rebuild the evidence byte-for-byte, verify every contract and historical
evidence hash, enforce the exact 3×3 matrix, and reject any blocked attempt that
claims a scientific class or artifact.
