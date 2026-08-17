# Executable test migration contract

This directory explains how SeaRise moves from the legacy distributed stack to
the static-first target without losing the only evidence for an invariant.
The machine-readable source of truth is
[`tests/test-inventory.json`](../../tests/test-inventory.json); its schema and
enforcement live in `tests/contracts/test-inventory.schema.json` and
`scripts/tests/validate_test_inventory.py`.

## Required loop

Every refactor or behavior slice follows this order:

1. **Characterize or specify.** Name the first failing test and the invariant.
2. **Red.** Run it and record that it fails for the intended reason.
3. **Green.** Add the smallest target behavior that passes.
4. **Refactor.** Improve structure while the focused command stays green.
5. **Compare.** Run legacy and target against independent expected evidence.
6. **Promote.** Add the deterministic target suite to its declared CI tier.
7. **Retire.** Remove a baseline test only with its approved gate and
   equivalent-or-stronger replacement evidence in the same PR.

The measured pipeline and browser examples are recorded in
[`tests/evidence/tdd-slices.json`](../../tests/evidence/tdd-slices.json). They
also show that target parity alone does not authorize legacy deletion.

The [legacy frontend removal inventory](legacy-frontend-removal-inventory.md)
maps every API-shaped store, type, component test, and directly related
frontend suite to static target evidence and explicit issue #70 blocking gates.

## Locations and naming

| Evidence | Location | Naming rule |
|---|---|---|
| Cross-language contracts | `tests/contracts/` | `<subject>.schema.json` |
| Shared inputs and goldens | `tests/fixtures/<kind>/` | `<subject>-v<major>.json` |
| Measured evidence | `tests/evidence/` | `<experiment-or-gate>.json` |
| Repository harness tests | `tests/harness/` | `test_<behavior>.py` |
| Pipeline target tests | `src/pipeline/tests/<domain>/` | `test_<behavior>.py` |
| Static browser unit/component tests | `src/web/src/<domain>/` | `<behavior>.test.ts[x]` |
| Static browser journeys | `src/web/tests/` | `<journey>.spec.ts` |
| Legacy frontend evidence | `src/frontend/src/` | Historical test names remain until their approved retirement PR |

Builders belong next to the consuming test suite under a `builders/` directory.
They expose domain intent and must not copy legacy request, database, TiTiler,
or server-lifecycle types into target tests.

## Inventory and removal matrix

Every suite declares:

- lifecycle `status`, an approved `removalGate`, and concrete
  `replacementEvidence` when retired;
- owner and purpose;
- exact source and changed-path patterns;
- migration disposition and replacement gate;
- focused/full commands and promotion tier;
- measured or traceable estimated cost;
- flake status and accountable owner.

`baselineTests` locks every discovered current test file. An active suite must
use `status: active` with null suite-level retirement metadata, and every one
of its `sourcePaths` patterns must resolve. A retirement PR keeps both the
suite and baseline history, changes them to `status: retired`, cites the
approved `removalGate`, and records the target test, PR, or report in
`replacementEvidence`. Retired source paths may be absent because deletion is
the event they record; a retired baseline path must be absent. The validator
rejects on-disk tests marked retired and active baseline tests owned by a
retired suite.

Only active suites own discovered tests or participate in changed-path
routing. Selection, the credential-free fast filter, and command execution
each reject retired suites independently, including direct `--run` use. The
legacy Compose smoke test is discovered only while its script exists, so its
approved removal cannot create a phantom unowned test. New tests must receive
an active baseline entry and active suite ownership in the PR that introduces
them.

No `WIP`, skip, quarantine, or reduced assertion count is removal evidence.
Coverage percentage is not replacement evidence. A replacement must cite the
same invariant and be equivalent or stronger at a public contract boundary.

## Fast feedback and promotion tiers

Validate ownership and choose local suites without Docker or cloud credentials:

```bash
python scripts/tests/validate_test_inventory.py
python -m unittest discover -s tests/harness -p 'test_*.py'
python scripts/tests/changed_suites.py --changed path/to/file another/file
python scripts/tests/changed_suites.py --base-ref origin/master
```

Add `--run` to execute the selected fast commands. Use `--all-tiers` to inspect
regional, release, container, and scheduled ownership; those suites are shown
but are not silently executed by the fast local runner.

The tiers have different purposes:

- `fast`: deterministic unit/contract/static feedback on each PR;
- `regional`: representative real-source and adapter evidence;
- `release`: full regional/browser/delivery evidence required for promotion;
- `scheduled`: security, mutation, and other diagnostics not needed per edit.

A fast pass cannot waive regional or release evidence. Promotion workflows in
#61 must consume the same suite IDs rather than maintain an unrelated path map.

Settlement search validation and its fixture-versus-production evidence limits
are documented in the
[static settlement search runbook](../operations/static-settlement-search.md).

## Path-aware pull request CI

`scripts/ci/changed_components.py` is the shared path router for CI and CodeQL.
Its mapping is versioned and covered by `tests/harness/test_changed_components.py`.
Each workflow always runs a lightweight detection job and an aggregate gate;
component jobs between them are conditional:

- frontend paths run frontend checks and JavaScript/TypeScript CodeQL;
- API paths run .NET checks and C# CodeQL;
- pipeline, scientific data, and test-contract paths run pipeline checks;
- infrastructure/compose paths run infrastructure validation and the relevant
  full-stack smoke test;
- image builds run only for production/container inputs, not test-only edits;
- Markdown and other documentation-only changes skip all heavyweight jobs;
- router or workflow changes run every route so filtering cannot weaken itself.

Manual CI and scheduled/manual CodeQL runs enable every route. Renames evaluate
both the old and new path so moving code into documentation cannot bypass its
former owner.

Branch protection should require the stable `CI Gate` and `CodeQL Gate`
checks, not each conditional implementation job. A skipped component is valid
only when its aggregate gate succeeds.

## Review ownership

Changes to this contract need the relevant owners below. The PR records actual
review; inventory ownership does not claim that human review already happened.

| Area | Required review |
|---|---|
| Source, transforms, fixtures | data |
| Browser, components, accessibility | frontend |
| CI, containers, delivery, rollback | platform |
| Semantics, goldens, methodology | science |
| Public delivery, validation, waivers | security |

Cross-cutting inventory changes require all five. Scientific, integrity,
licence, provenance, public-delivery, and promotion gates are non-waivable.
