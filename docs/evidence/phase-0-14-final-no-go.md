# Phase 0.14 Scientific No-Go Gate

> **Issue:** [#98](https://github.com/artemsemdev/SeaRise-Europe/issues/98)
>
> **Decision date:** 2026-08-05
>
> **Phase 0 disposition:** `COMPLETE-WITH-NO-GO`
>
> **Authoritative scientific disposition:** `BLOCKED`
>
> **Automated methodology recommendation:** `REJECTED`
>
> **Phase 1:** `LOCKED`

## Decision

Phase 0 has reached a terminal, scientifically honest project result. Automated
methodology analysis recommends rejecting the selected binary coastal-screening
method because issue #95 found that the mandatory cell-level vertical
uncertainty cannot be bounded from the pinned evidence. A classified `0` or `1`
would therefore communicate more certainty than the sources support.

That recommendation is not an authoritative scientific rejection. Independent
review is still pending, so the scientific disposition is `BLOCKED`. Automation
records the evidence and fail-closed recommendation, but it cannot approve or
reject the science on behalf of an independent reviewer.

`COMPLETE-WITH-NO-GO` means the Phase 0 investigation is complete. It does not
mean that the scientific gate passed, that a regional release exists, or that
Phase 1 may start. A future continuation requires a newly scoped methodology
and a new versioned gate; it must not reinterpret this decision as approval.

## Fail-closed 3×3 preflight

All required scenario/horizon combinations short-circuit at scientific
preflight:

| Scenario | 2030 | 2050 | 2100 |
|---|---|---|---|
| `ssp1-26` | stopped before array | stopped before array | stopped before array |
| `ssp2-45` | stopped before array | stopped before array | stopped before array |
| `ssp5-85` | stopped before array | stopped before array | stopped before array |

The preflight does not open scientific source payloads. It emits no scientific
class values, arrays, COGs, PMTiles, GeoParquet, statistics, release receipts,
or synthetic substitute. Review and cross-environment claims remain pending;
CI is explicitly unable to approve science or act as an independent reviewer.

## Dependency evidence

The builder reserves one exact binding slot for each prerequisite:

| Issue | Scientific disposition | Required evidence path |
|---|---|---|
| #94 geoid evaluator | blocked | `src/pipeline/science/evidence/geoid-evaluator-validation.json` |
| #95 uncertainty budget | blocked | `src/pipeline/science/coastal-uncertainty-budget.json` |
| #96 basin controls | blocked | `src/pipeline/science/evidence/phase-0-12-basin-controls.json` |
| #97 scope/connectivity review | blocked | `src/pipeline/science/scope-connectivity-review.json` |

Before dependency integration, these slots are `pending` and retain their exact
expected paths. Such a draft cannot validate or serialize as terminal checked-in
evidence. After issues #94–#97 are in the integration history, the builder must
bind every path and SHA-256 and verify that each file actually records the
corresponding blocked state. A missing binding, changed path, hash mismatch, or
contradictory disposition fails validation.

The #95 automated rejection recommendation is sufficient to stop all nine
release attempts. Binding the other evidence cannot turn this gate into
approval: the binary method would first need replacement or scientifically
adequate new evidence, followed by a separately reviewed gate.

## Historical immutability

Phase 0.14 does not edit or replace the content of the Phase 0.9/#85 record.
It checksum-binds these historical files as immutable inputs:

- `src/pipeline/science/phase-0-9-gate.json`
- `src/pipeline/science/evidence/phase-0-9-regional-attempt.json`

This preserves the earlier `BLOCKED` decision while recording the later project
disposition `COMPLETE-WITH-NO-GO`. The authoritative scientific disposition
remains `BLOCKED`.

## Machine-enforced invariants

The Phase 0.14 schema and validator require:

- the exact three-scenario by three-horizon matrix;
- all four dependency dispositions to remain `blocked` with issue-specific
  reasons and exact evidence paths;
- the automated methodology recommendation to remain distinct from the
  authoritative `blocked` disposition;
- every dependency to be hash-bound before a final record can be checked in;
- every attempt to stop before arrays, classes, artifacts, or statistics;
- both scientific approval capabilities on automation to remain false;
- historical and any integrated dependency hashes to verify;
- Phase 1 to remain locked.

The Phase 0.14 schema is outcome-specific. Fabricating a completed review,
recording an authoritative approval/rejection, adding a release artifact, or
setting `phase1.unlocked=true` invalidates the record instead of silently
changing the decision.

## Reproducibility

After issues #94–#97 have been integrated, build the final record from the
repository root:

```bash
PYTHONPATH=src/pipeline .venv/bin/python scripts/science/build_phase_0_14_gate.py
PYTHONPATH=src/pipeline .venv/bin/python -m pytest \
  src/pipeline/tests/regional_fixture/test_phase_0_14_gate.py -q
```

The builder refuses to serialize terminal evidence while any dependency slot is
pending. Once all slots are bound, it serializes canonical JSON and validation
checks every required file hash and its blocked-state semantics.
