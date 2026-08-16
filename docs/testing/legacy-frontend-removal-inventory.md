# Legacy frontend removal inventory

> **Scope:** Issue #70, with the issue #59 static application state as the
> replacement boundary<br>
> **Status:** Removal map; it does not authorize deletion by itself<br>
> **Target runtime:** `src/web` only

This inventory maps the API-shaped state and component evidence in the legacy
Next.js application to the static browser target. A legacy test may be deleted
only after its row is covered by the cited target evidence, every blocking gate
below is green, and its baseline entry in `tests/test-inventory.json` is retired
with concrete `replacementEvidence` as required by the test migration contract.

## Runtime and type boundaries

| Legacy boundary | Static target | Removal decision |
|---|---|---|
| `src/frontend/src/lib/store/appStore.ts` | `src/web/src/domain/projection-state.ts`, `src/web/src/application/assessment-controller.ts`, and `src/web/src/application/use-assessment-runtime.ts` | Replace. The target owns immutable release/selection/result state, monotonic operation tokens, cancellation, stale-completion rejection, retry, reset, and technical failures outside scientific outcomes. |
| `src/frontend/src/lib/store/mapStore.ts` | `src/web/src/domain/projection-state.ts` and `src/web/src/components/map/MapExplorer.tsx` | Replace. Map selection is an immutable `Selection`; accepted projection state is the sole intended authority for marker, layer, legend, and share state. Final deletion waits for the App-level synchronization gate below. |
| `src/frontend/src/lib/store/uiStore.ts` | Local controlled state around `src/web/src/components/MethodologyDialog.tsx` | Replace. A global UI store is not required for one controlled native dialog. Final deletion waits for App-level trigger wiring. |
| `src/frontend/src/lib/types/index.ts` | `src/web/src/domain/release.ts`, `src/web/src/domain/selection.ts`, `src/web/src/domain/scientific-lookup.ts`, and `src/web/src/contracts/generated/release-contract.ts` | Delete, do not copy. The target has release-bound selections, generated scenario/horizon contracts, verified methodology, and exactly four ADR-024 outcomes. Request IDs, backend tile templates, mutable API config, and binary exposure states have no target equivalent. |
| `src/frontend/src/lib/api/assessment.ts` | `src/web/src/scientific-runtime.ts` and `src/web/src/application/browser-runtime.ts` | Delete. Assessment executes locally from release-bound boundary and COG artifacts; no `/v1/assess` adapter remains. |
| `src/frontend/src/lib/api/geocoding.ts` | `src/web/src/search/search.worker.ts` and `src/web/src/search/client.ts` | Delete. Search is an integrity-checked GeoNames Web Worker flow; no `/v1/geocode` response or request ID remains. |
| `src/frontend/src/lib/api/config.ts` and `src/frontend/src/lib/api/methodology.ts` | `src/web/src/data/manifest-repository.ts` and `src/web/src/data/methodology-repository.ts` | Delete. Configuration and methodology are immutable, release-scoped, schema/integrity checked artifacts; no `/v1/config` fetch remains. |
| `src/frontend/src/lib/hooks/useUrlState.ts` | `src/web/src/domain/url-state.ts` | Replace. The target URL contract includes the exact release and immutable selection identity. App-level share/reload/popstate evidence remains a blocking gate. |
| `src/frontend/src/lib/contracts/generated/*` and `src/frontend/src/lib/contracts/public-contract-parity.test.ts` | `src/web/src/contracts/generated/release-contract.ts`, generated validators, `src/web/src/data/manifest-repository.test.ts`, and `npm run check:contracts --workspace @searise/web` | Replace after the inventory retirement entry cites the target contract checks. Do not preserve API DTO parity in the target. |

The C# DTOs in `src/api/SeaRise.Api/Dtos/AssessResponse.cs`,
`src/api/SeaRise.Api/Dtos/GeocodeResponse.cs`,
`src/api/SeaRise.Api/Dtos/ConfigScenariosResponse.cs`, and
`src/api/SeaRise.Api/Dtos/ConfigMethodologyResponse.cs` explain the legacy HTTP
shapes but are not target contracts. They are owned by issue #71; this
inventory does not authorize their deletion or modify their tests.

## Store and domain test mapping

| Legacy evidence | Equivalent-or-stronger target evidence | State |
|---|---|---|
| `src/frontend/src/__tests__/stores/appStore.test.ts` | `src/web/src/domain/projection-state.test.ts`, `src/web/src/application/assessment-controller.test.ts`, `src/web/src/application/use-assessment-runtime.test.tsx`, and `src/web/src/App.test.tsx` cover every target phase, one-command production wiring, atomic accepted tuples, four outcomes, technical failures, stale work, cancellation, release replacement, URL navigation, retry, and reset. | Equivalent-or-stronger target unit and production-composition coverage complete. |
| `src/frontend/src/__tests__/stores/mapStore.test.ts` | `src/web/src/components/map/MapExplorer.test.tsx` covers immutable coordinate selection and accepted-only overlay/marker/text-alternative state; `src/web/src/App.test.tsx` proves a pending selection cannot replace the accepted map tuple; `src/web/src/components/map/render-token.test.ts` guards stale map work. | Equivalent-or-stronger target component and production-composition coverage complete. |
| `src/frontend/src/__tests__/stores/uiStore.test.ts` | `src/web/src/components/MethodologyDialog.test.tsx` covers controlled open/close, Escape, deterministic focus, focus return, release identity, and fail-closed content; `src/web/src/App.test.tsx` covers the verified-only production trigger and focus restoration. | Equivalent-or-stronger target component and production-composition coverage complete. |
| `src/frontend/src/__tests__/domain/resultState.characterization.test.ts` and `src/frontend/src/__tests__/builders/resultStateBuilder.ts` | `src/web/src/domain/release.test.ts`, `src/web/src/domain/projection-state.test.ts`, `src/web/src/domain/scientific-lookup.test.ts`, and `src/web/src/data/cog-analysis-reader.golden.test.ts` enforce exactly `ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, and `UnsupportedGeography`. | Superseded, not ported. The legacy binary classification is historical evidence only; see below. |

## Component and API-contract test mapping

| Legacy test | Target evidence | State or remaining gate |
|---|---|---|
| `src/frontend/src/__tests__/components/CandidateList.test.tsx` | `src/web/src/components/SettlementSearch.test.tsx`, `src/web/src/search/runtime.test.ts`, and `src/web/src/search/search.worker.test.ts` cover listbox/option semantics, the release-bound ranking/result-limit contract, active-descendant keyboard selection, exact stable place identity, stale-query rejection, and worker failures. | Covered by a stronger local-search boundary. The legacy arbitrary five-option slice is not copied over the target search contract. |
| `src/frontend/src/__tests__/components/SearchBar.test.tsx` | `src/web/src/components/SettlementSearch.test.tsx` and `src/web/src/App.test.tsx` cover the labelled search/combobox, local query privacy, empty/current-result safety, and settlement-only interaction. | Production keyboard journey remains part of the final browser gate. |
| `src/frontend/src/__tests__/components/EmptyState.test.tsx` | `src/web/src/App.test.tsx` covers the semantic landing page, honest fixture disclosure, navigation, skip link, and search entry point. | Add/retain production-static accessibility evidence for status announcement, focus order, and disclaimer before retirement. |
| `src/frontend/src/__tests__/components/LoadingState.test.tsx` | The phase table in `src/web/src/components/ProjectionPanel.test.tsx` covers booting, searching, evaluating, updating, and explicit status text; `src/web/tests/projection-ux.spec.ts` proves terminal success and failure states in the production build. | Replacement coverage complete. |
| `src/frontend/src/__tests__/components/ErrorBanner.test.tsx` | `src/web/src/components/ProjectionPanel.test.tsx`, `src/web/src/components/SettlementSearch.test.tsx`, and `src/web/src/App.test.tsx` cover presentation and routing; `src/web/tests/projection-ux.spec.ts` corrupts a real COG range and injects one transient 503 to prove retained prior state and explicit retry. | Replacement coverage complete. |
| `src/frontend/src/__tests__/components/NoResults.test.tsx` | `src/web/src/components/SettlementSearch.test.tsx` covers an honest no-match state separately from technical failure and prevents stale selection. | Covered by a stronger search-state boundary. |
| `src/frontend/src/__tests__/components/ScenarioControl.test.tsx` and `src/frontend/src/__tests__/components/HorizonControl.test.tsx` | `src/web/src/components/ProjectionPanel.test.tsx` covers exactly three scenarios, exactly three horizons, active radio state, and one immutable selection command; `src/web/tests/projection-ux.spec.ts` exercises keyboard radio changes and the exact nine-combination production-static journey. | Replacement coverage complete; retain both target tests through retirement. |
| `src/frontend/src/__tests__/components/Legend.test.tsx` | `src/web/src/components/map/MapExplorer.test.tsx` covers accepted-only overlay/band/marker/text-alternative changes and attribution; `src/web/src/App.test.tsx` and `src/web/tests/projection-ux.spec.ts` prove atomic accepted tuple and visual identity during stale updates. | Covered by stronger target evidence. Binary exposure colour stops are intentionally not ported; PMTiles remains visual context only. |
| `src/frontend/src/__tests__/components/ResultPanel.test.tsx` | `src/web/src/components/ProjectionPanel.test.tsx` covers all and only the four ADR-024 outcomes, exact quantile/source metadata, limitations, attribution/licence, technical-state separation, dispositions, and prohibited wording; `src/web/tests/projection-ux.spec.ts` proves all four production-static journeys and technical isolation. | Replacement coverage complete. Binary exposure assertions are intentionally not ported. |
| `src/frontend/src/__tests__/api/methodology.contract.test.ts` | `src/web/src/data/methodology-repository.test.ts` and `src/web/src/components/MethodologyDialog.test.tsx` cover schema, SHA-256, release identity, attribution, licence, ADR-024 constants, disposition, and fail-closed rendering. | Covered by a stronger immutable-artifact boundary; request ID and legacy HTTP response shape are deleted. |

## Other `src/frontend` test suites

Issue #70 removes the whole directory, so the permanent-behaviour suites below
must also be retired or relocated even though they do not exercise API-shaped
UI state:

| Legacy suite paths | Existing target candidate | Required inventory action |
|---|---|---|
| `src/frontend/src/lib/ar6/*.test.ts` and `src/frontend/src/lib/regional-fixture/*.test.ts` | `src/web/src/domain/scientific-lookup.test.ts`, `src/web/src/data/cog-analysis-reader.golden.test.ts`, and the reusable Python goldens | Record exact replacement evidence before removing the frontend copies; keep the scientific goldens and pipeline evidence. |
| `src/frontend/src/lib/contracts/public-contract-parity.test.ts` | `src/web/src/data/manifest-repository.test.ts` and generated release contract checks | Retire the API-era parity entry; retain release/STAC/manifest contracts. |
| `src/frontend/src/search/evaluation/*.test.ts`, `src/frontend/src/search/shards/*.test.ts`, and `src/frontend/src/search/worker/*.test.ts` | `src/web/src/search/runtime.test.ts`, `src/web/src/search/search.worker.test.ts`, and `src/web/src/components/SettlementSearch.test.tsx` | Record the exact search replacement evidence before deletion. |
| `src/frontend/src/search/performance/browser-worker-evidence.test.ts` | `src/web/tests/static-shell.spec.ts` and `src/web/scripts/measure-local-candidate-search.mjs` | Retire only after the committed-fixture performance journey and local Candidate measurement command pass. Candidate bytes and measurements remain local-only. |

## Blocking removal gates

Issue #70 must not delete `src/frontend` until all of these are true:

1. The production `src/web/src/App.tsx` is wired to the assessment controller,
   projection panel, methodology dialog, and accepted-projection map state.
2. Production-static Playwright proves all four outcomes, technical failures,
   rapid-selection stale-work rejection, all nine combinations, share/reload/
   popstate release isolation, map/legend synchronization, keyboard and
   accessibility behavior, and zero `/assess`, `/geocode`, or `/config`
   requests.
3. The static build and offline/update journeys pass from a clean clone against
   the committed synthetic fixture without Docker, cloud credentials, or any
   private Candidate artifact.
4. Every `src/frontend` baseline entry in `tests/test-inventory.json` is changed
   to `retired` with issue #70 as the approved removal gate and exact target
   `replacementEvidence`. Entries currently marked permanent or carrying a
   null removal gate must be explicitly reconciled; deleting their files alone
   is forbidden.
5. A repository and built-asset scan rejects Next.js, API-shaped browser state,
   request IDs, backend tile templates, and `/assess`, `/geocode`, `/config`
   endpoints outside an approved historical allowlist.

## Historical five-state evidence

`tests/fixtures/tdd/five-state-characterization-v1.json` is designated
**historical legacy evidence only**. Its own metadata identifies
`legacy-v1.0-characterization`, and its two binary exposure outcomes are
superseded by ADR-024. It may remain for traceability with
`tests/evidence/tdd-slices.json` and
`tests/evidence/mutation-pilot-result-state.json`, but it is prohibited from
the `src/web` target domain, release contracts, synthetic target fixture, built
assets, and product copy. It cannot serve as replacement evidence for an
ADR-024 outcome test.

The target domain contains exactly four outcomes. Technical errors remain a
separate runtime taxonomy and never become a fifth scientific outcome.

## Validation commands

Run from an installed clean clone at the repository root before approving the
issue #70 retirement PR. These are future removal gates, not claimed execution
evidence for this inventory-only change:

```bash
npm run web:check
npm run web:e2e
python3 scripts/tests/validate_test_inventory.py
python3 -m unittest discover -s tests/harness -p 'test_*.py'
git diff --check
```

The final issue #70 PR must also record its clean-clone forbidden-reference and
built-asset scan commands; this document does not invent results that have not
yet been produced.

## Rollback and external resources

Git history is the source-recovery mechanism for the deleted Next.js and
API-shaped browser code. Revert the focused issue #70 cleanup commits if a
hidden repository dependency is found. This repository inventory authorizes no
deletion of cloud resources, credentials, GitHub environments, secrets, or
private local Candidate artifacts.
