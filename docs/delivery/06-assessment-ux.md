# Epic 06 — Scenario Controls and Assessment UX

| Field          | Value                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Epic ID        | E-06                                                                                               |
| Phase          | 1 — MVP Implementation                                                                             |
| Status         | Not Started                                                                                        |
| Effort         | ~6 days                                                                                            |
| Dependencies   | Epic 04 (assess endpoint), Epic 05 (map + shell + search flow)                                     |
| Stories        | 7 (S06-01 through S06-07)                                                                          |
| Produces       | Complete assessment cycle — from search to all 5 result states displayed                           |

---

## 1  Objective

Implement the scenario controls, time horizon controls, result panel, exposure overlay, legend, and all supporting UX states so that a user can complete the full assessment cycle: search for a location, view an exposure result, change scenario and horizon, see updated results, and reset to the initial state. All 5 result states (BR-010) must render with correct copy, correct map behavior, and correct accessibility annotations.

---

## 2  Why This Epic Exists

Epic 04 produces the API. Epic 05 produces the map shell, search bar, and candidate selection flow. But neither delivers the assessment result experience. Without this epic, the user can search for a location but never see what the application exists to show: whether that location has modeled coastal exposure under a given scenario and time horizon. This epic closes the gap between "location selected" and "result displayed, understood, and actionable." It is the epic that delivers the product's core value proposition to the screen.

---

## 3  Scope

### 3.1 In Scope

- ScenarioControl and HorizonControl components populated from the config query (Epic 05).
- TanStack Query hook for `POST /v1/assess` with cache key `['assess', lat, lng, scenarioId, horizonYear]`.
- ResultPanel with all 5 result states rendering correct copy from `en.ts` (CONTENT_GUIDELINES sections 3 and 4).
- ExposureLayer (deck.gl TileLayer) visible only for `ModeledExposureDetected`.
- Legend component reading `legendSpec` from the assessment response.
- Loading, error, and `result_updating` UX states.
- URL state serialization (`lat`, `lng`, `scenario`, `horizon`, `zoom`).
- Stale request handling via AbortController + TanStack Query key changes.
- Map click handler triggering new assessment when a location is already selected.
- ResetButton clearing all state to `idle`.
- Component integration tests and E2E tests covering the full assessment flow.

### 3.2 Out of Scope

- Search bar and candidate selection (Epic 05).
- Methodology panel content and drawer (Epic 07 or later).
- Analytics event instrumentation (OQ-10).
- Mobile bottom sheet layout (OQ-12).
- Custom domains, CDN, production DNS.

---

## 4  Blocking Open Questions

None. All blocking questions for this epic were resolved in Epic 01 (scenario set, defaults, methodology) and design decisions in the frontend architecture document. OQ-08 (URL sharing) is not blocking — URL state is implemented proactively as a low-cost readiness measure.

---

## 5  Traceability

### 5.1 Product Requirement Traceability

| Requirement | Description                                                    |
| ----------- | -------------------------------------------------------------- |
| FR-014      | Scenario selection control                                     |
| FR-015      | Time horizon control (2030, 2050, 2100)                        |
| FR-016      | Default scenario and horizon on load                           |
| FR-017      | Display all configured scenarios                               |
| FR-018      | Show active selections                                         |
| FR-019      | Assessment trigger on control change                           |
| FR-020      | Result includes scenario, horizon, methodology                 |
| FR-021      | Exposure overlay visible only for ModeledExposureDetected       |
| FR-022      | Exposure overlay removed on non-exposure results               |
| FR-024      | Disclaimer visible on every result                             |
| FR-028      | Location marker visually distinct from overlay                 |
| FR-029      | Legend updates on result change                                |
| FR-030      | Controls visible at all times during result                    |
| FR-031      | Map and result panel synchronized                              |
| FR-032      | Methodology entry point button                                 |
| FR-040      | Only latest result rendered (stale request handling)           |
| FR-041      | Reset to initial state                                         |
| BR-010      | 5 fixed result states                                          |
| BR-014      | No substitution of scenario/horizon                            |
| NFR-004     | Control switch ≤1.5s from cache                                |
| NFR-010     | No blank/broken UI states                                      |
| NFR-015     | WCAG 2.2 AA                                                    |

### 5.2 Architecture Traceability

| Architecture Document                                      | Relevance                                        |
| ---------------------------------------------------------- | ------------------------------------------------ |
| `docs/architecture/03a-frontend-architecture.md`           | Component structure, state machine, map architecture, accessibility |
| `docs/architecture/06-api-and-contracts.md`                | Assess endpoint contract, result state taxonomy, config endpoints |
| `docs/product/CONTENT_GUIDELINES.md`                       | Result state copy, disclaimer, scientific language rules |
| `docs/architecture/13-domain-model.md`                     | ResultState, AssessmentResult types              |
| `docs/architecture/03-component-view.md`                   | ExposureEvaluator, ResultStateDeterminator        |

### 5.3 Mock Visual Specification

The clickable prototype is the authoritative visual specification. Each story must match the corresponding mock screen. See `docs/product/Mock/MOCK_REQUIREMENTS_MAP.md` for the full traceability map.

| Story   | Mock Screen(s) to Match                                    |
| ------- | ---------------------------------------------------------- |
| S06-01  | `06-exposure.html` sidebar (timeline selector with 5 horizons, forecast model list with 3 models) |
| S06-02  | `05-assessing.html` (assessment trigger), `06-exposure.html` (result delivery) |
| S06-03  | `06-exposure.html` (exposure), `07-no-exposure.html` (no exposure), `08-data-unavailable.html` (data unavailable), `09-inland.html` (out of scope), `10-unsupported.html` (unsupported) |
| S06-04  | `06-exposure.html` (exposure polygon overlay, warn marker, gradient bar) |
| S06-05  | `05-assessing.html` (loading), `13-error-assessment.html` (error with retry) |
| S06-06  | All result screens (URL state reflects active scenario/horizon/location) |
| S06-07  | All above screens (integration tests across full assessment cycle) |

---

## 6  Implementation Plan

Work through stories in the following recommended order, chosen to build up from controls to full integration:

1. **S06-01 — Implement ScenarioControl and HorizonControl.** These are prerequisite UI elements that all subsequent stories depend on for triggering assessments.
2. **S06-02 — Implement Assessment API Integration.** The TanStack Query hook and stale request handling must exist before any result can be displayed.
3. **S06-03 — Implement ResultPanel with All 5 Result States.** Depends on S06-02 providing assessment results to render.
4. **S06-04 — Implement ExposureLayer and Legend.** Depends on S06-02 (assessment response provides `layerTileUrlTemplate` and `legendSpec`) and S06-03 (result panel must exist for synchronized display).
5. **S06-05 — Implement Loading, Error, and Result-Updating States.** Can be developed in parallel with S06-03 and S06-04 but is listed after them because the happy path should work first.
6. **S06-06 — Implement URL State Synchronization.** Independent of result rendering; can be parallelized with S06-03 through S06-05.
7. **S06-07 — Assessment Flow Component Integration Tests.** Must be last — tests validate the integrated behavior of all preceding stories.

### Execution Order Map

```
S06-01 (ScenarioControl + HorizonControl)
  │
  └──► S06-02 (Assessment API Integration)
         │
         ├──► S06-03 (ResultPanel — 5 States)     ◄── parallel with S06-06
         │       │
         │       └──► S06-04 (ExposureLayer + Legend)
         │
         ├──► S06-05 (Loading/Error/Updating)      ◄── parallel with S06-03
         │
         └──► S06-06 (URL State Sync)              ◄── parallel with S06-03/S06-05
                │
                └──────────────────────────────────────┐
                                                       ▼
                                              S06-07 (Integration Tests)
```

**Rationale:** S06-01 (controls) and S06-02 (API hook) are strictly sequential — controls trigger assessments, and the hook delivers results. After S06-02, three parallel tracks open: result rendering (S06-03→S06-04), transitional states (S06-05), and URL state (S06-06). S06-07 must be last because it validates the complete integrated assessment cycle.

---

## 7  User Stories

---

### S06-01 — Implement ScenarioControl and HorizonControl

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-01                                             |
| Type           | Feature                                            |
| Effort         | ~1 day                                             |
| Dependencies   | Epic 05 (config query provides scenario/horizon data) |

**Statement**

As a user, I want to select a climate scenario and time horizon from clearly labeled controls, so that I can explore how different futures affect the exposure result for my selected location.

**Why**

The scenario and horizon controls are the primary interaction mechanism for the assessment cycle after a location is selected. Without them, the user sees a single result with no ability to compare across scenarios or time horizons. These controls are what make the product useful beyond a single static lookup.

**Scope Notes**

- ScenarioControl: radio group or tab set rendering all scenarios from the `['config', 'scenarios']` query.
- HorizonControl: visual timeline selector with 5 stops: +10 yr (2036), +20 yr (2046), +30 yr (2056), +50 yr (2076), +100 yr (2126). Implements a horizontal track with gradient fill, dot indicators, and relative/absolute year labels. See mock `06-exposure.html` sidebar for the reference implementation.
- Both controls populated from `GET /v1/config/scenarios` response (fetched and cached in Epic 05).
- Default selections applied from the config `defaults` object on initial load (FR-016).
- Active selection visually indicated at all times (FR-018).
- onChange on either control triggers a new assessment with updated parameters (FR-019).
- Keyboard navigation: Arrow keys to move between options within each control (NFR-015).
- Controls visible at all times when the result panel is shown (FR-030).

**Traceability**

- Requirements: FR-014, FR-015, FR-016, FR-017, FR-018, FR-019, FR-030
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 3 — ResultPanel, section 8 — Accessibility Strategy)

**Implementation Notes**

- ScenarioControl renders scenarios in `sortOrder` from the config response.
- HorizonControl renders horizons in `sortOrder` from the config response.
- Use `role="radiogroup"` with `role="radio"` children for ScenarioControl. Use `role="radiogroup"` with segmented button children for HorizonControl.
- `aria-checked` on the active option. `aria-label` on each control group.
- Store active `scenarioId` and `horizonYear` in appStore or a local assessment params store. On change, the assessment hook (S06-02) picks up the new params.
- Display names and descriptions come from the config response, not hardcoded values.

**Acceptance Criteria**

1. ScenarioControl renders all scenarios from the config query in sort order with display names.
2. HorizonControl renders 5 timeline stops (+10 yr, +20 yr, +30 yr, +50 yr, +100 yr) with gradient fill track matching mock `06-exposure.html`.
3. Default scenario and horizon are pre-selected on initial load per the config `defaults` object.
4. Changing a scenario visually updates the active indicator immediately.
5. Changing a horizon visually updates the active indicator immediately.
6. onChange on either control triggers a new assessment call with the updated parameter.
7. Arrow keys navigate between options within each control.
8. Both controls are visible whenever the result panel is visible.
9. Each control has an `aria-label` and active option has `aria-checked="true"`.

**Definition of Done**

- Both controls render correctly with config data.
- Keyboard navigation works (Arrow keys).
- ARIA attributes are correct.
- onChange integration point is wired (actual assessment call tested in S06-02).

**Testing Approach**

- Unit: RTL test that ScenarioControl renders N scenarios from mock config, default is selected, arrow key changes selection.
- Unit: RTL test that HorizonControl renders 3 horizons, default is selected, click and arrow key change selection.
- Accessibility: axe-core scan on each control.

**Evidence Required**

- RTL test output showing controls render correctly with mock config data.
- axe-core scan passing with no violations on each control.

---

### S06-02 — Implement Assessment API Integration

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-02                                             |
| Type           | Feature                                            |
| Effort         | ~1 day                                             |
| Dependencies   | Epic 04 (assess endpoint), S06-01 (scenario/horizon params) |

**Statement**

As the engineer maintaining delivery quality, I want a TanStack Query hook that calls `POST /v1/assess` with full cache key management and stale request handling, so that the frontend can fetch, cache, and display assessment results correctly and efficiently.

**Why**

The assessment API integration is the bridge between user interaction and result display. The cache key structure (`['assess', lat, lng, scenarioId, horizonYear]`) determines whether switching back to a previously viewed combination returns instantly (NFR-004) or makes a redundant network call. The stale request handling (FR-040) determines whether rapid control changes produce flickering, stale, or incorrect results. Getting this hook right is a prerequisite for every result-rendering story.

**Scope Notes**

- TanStack Query hook wrapping `POST /v1/assess`.
- Query key: `['assess', lat, lng, scenarioId, horizonYear]`.
- `staleTime: 60_000` (60 seconds) to enable cached scenario/horizon switches (NFR-004).
- AbortController integration: TanStack Query's built-in AbortSignal handles query key changes automatically. If a custom fetch flow is used, implement the `requestSeq` pattern from `docs/architecture/03a-frontend-architecture.md` section 4.3.
- On success: transition appPhase to `result` with the `AssessmentResult`.
- On error: transition appPhase to `assessment_error`.
- When a new assessment is triggered while a result is displayed: transition appPhase to `result_updating` before the request completes.
- Map click handler on MapSurface: if `selectedLocation` exists, capture click coordinates and trigger a new assessment with the clicked location (FR-007, FR-008).

**Traceability**

- Requirements: FR-019, FR-020, FR-040, NFR-004, BR-014
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 4.2 — TanStack Query, section 4.3 — Stale Request Handling), `docs/architecture/06-api-and-contracts.md` (POST /v1/assess)

**Implementation Notes**

- The hook should accept `{ lat, lng, scenarioId, horizonYear }` and return TanStack Query's standard `{ data, isLoading, isError, error }` shape.
- `enabled` flag: only fire when all four params are present and `appPhase` warrants an assessment.
- The query function sends a POST request with the params as JSON body and passes `signal` from TanStack Query for abort support.
- On query key change (scenario or horizon switch while in `result` phase), TanStack Query automatically cancels the in-flight request and starts a new one.
- If the new query key matches a cached entry within `staleTime`, the result is returned synchronously from cache — no network request.
- Map click handler: update `selectedLocation` in mapStore with clicked coordinates, which changes the query key and triggers a new assessment.

**Acceptance Criteria**

1. Hook calls `POST /v1/assess` with correct request body matching the API contract.
2. Query key is `['assess', lat, lng, scenarioId, horizonYear]` — all four params included.
3. `staleTime` is 60,000ms.
4. Switching to a previously cached scenario/horizon combination returns the result without a network request.
5. Rapid scenario/horizon changes cancel in-flight requests; only the latest result is applied to state.
6. On success, appPhase transitions to `result` with the full `AssessmentResult`.
7. On error, appPhase transitions to `assessment_error`.
8. When a new assessment triggers from `result` phase, appPhase transitions to `result_updating` before the response arrives.
9. Map click on MapSurface with an existing `selectedLocation` triggers a new assessment with the clicked coordinates.

**Definition of Done**

- TanStack Query hook implemented with correct cache key and stale time.
- Stale request handling verified (rapid switches produce no stale renders).
- AppPhase transitions are correct for success, error, and updating paths.
- Map click triggers a new assessment.

**Testing Approach**

- Unit: test hook with MSW — verify correct request body, verify cache hit on repeated query key.
- Integration: RTL + MSW — trigger assessment, verify appPhase transitions (assessing → result, assessing → assessment_error, result → result_updating → result).
- Stale request: MSW with delayed responses — trigger two rapid scenario changes, verify only the second result is rendered.

**Evidence Required**

- MSW-backed test output showing correct request body, cache behavior, and phase transitions.
- Stale request test showing the first response is discarded when a second request supersedes it.

---

### S06-03 — Implement ResultPanel with All 5 Result States

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-03                                             |
| Type           | Feature                                            |
| Effort         | ~1 day                                             |
| Dependencies   | S06-02 (assessment result data)                    |

**Statement**

As a user, I want to see a clear, well-structured result panel that tells me what the model shows for my selected location, including the scenario, time horizon, and a plain-language summary, so that I can understand the exposure assessment without needing technical expertise.

**Why**

The result panel is the primary communication surface. It is where the product delivers its value. Every result state — from modeled exposure to unsupported geography — must render with specific, accurate, CONTENT_GUIDELINES-compliant copy. A missing state, wrong headline, or absent disclaimer breaks the product's trust contract with the user. This story ensures all 5 result states are handled with the correct text, the disclaimer is always present, and the methodology entry point and reset button are accessible.

**Scope Notes**

- ResultPanel renders when `appPhase` is in `['assessing', 'result', 'result_updating', 'assessment_error']`.
- ResultStateHeader: headline text from `strings.resultStates[resultState]` — exactly one of the 5 values.
- ResultSummary: fills the CONTENT_GUIDELINES section 3 template with location label, scenario `displayName`, and `horizonYear`.
- Disclaimer: exact text from `strings.disclaimer` (CONTENT_GUIDELINES section 4), visible on every result (FR-024).
- MethodologyEntryPoint: button labeled "How to interpret this result" (FR-032). Opens the methodology panel (wired in a later epic; this story renders the button and fires an action).
- ResetButton: clears all state (selectedLocation, assessment result, appPhase) and returns to `idle` (FR-041).
- All 5 result states must render distinct, correct copy:
  1. `ModeledExposureDetected` — exposure headline, full summary template.
  2. `NoModeledExposureDetected` — no-exposure headline, summary acknowledging it is not a safety determination.
  3. `DataUnavailable` — data unavailable headline, summary confirming no substitution, suggesting alternate scenario/horizon.
  4. `OutOfScope` — outside coverage headline, summary explaining coastal-only scope, suggesting a coastal location.
  5. `UnsupportedGeography` — outside supported area headline, summary explaining Europe-only scope.

**Traceability**

- Requirements: FR-020, FR-024, FR-032, FR-041, BR-010, BR-014, NFR-010
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 3 — ResultPanel), `docs/product/CONTENT_GUIDELINES.md` (sections 3 and 4)

**Implementation Notes**

- All copy strings live in `lib/i18n/en.ts`. No hardcoded text in components.
- ResultSummary is a template function that accepts `{ locationLabel, scenarioDisplayName, horizonYear, datasetName, elevationDatasetName }` and returns the filled paragraph.
- For `DataUnavailable`: the summary must explicitly state that no substitution has occurred (BR-014, CONTENT_GUIDELINES section 3.3).
- Disclaimer text must pass a copy review against CONTENT_GUIDELINES section 4 — all mandatory exclusions (engineering assessment, legal determination, insurance evaluation, mortgage guidance, financial advice) must be present.
- `aria-live="polite"` on the result state heading container so screen readers announce state changes.
- ResetButton: calls a `reset()` action on appStore that sets phase to `idle`, clears `selectedLocation` in mapStore, and removes the exposure layer.

**Acceptance Criteria**

1. ResultPanel renders when appPhase is `result` and displays the correct headline for each of the 5 result states.
2. ResultSummary fills the CONTENT_GUIDELINES section 3 template correctly for `ModeledExposureDetected`, including scenario display name and horizon year.
3. ResultSummary for `NoModeledExposureDetected` includes the "does not constitute a safety determination" qualifier.
4. ResultSummary for `DataUnavailable` states that no substitution has occurred.
5. ResultSummary for `OutOfScope` explains coastal-only scope.
6. ResultSummary for `UnsupportedGeography` explains Europe-only scope.
7. Disclaimer text matches `strings.disclaimer` exactly and is visible on every result state.
8. MethodologyEntryPoint button is rendered and fires the `openMethodologyPanel` action on click.
9. ResetButton clears all state and returns appPhase to `idle`.
10. No copy string is hardcoded in a component file; all text comes from `en.ts`.
11. `aria-live="polite"` is set on the result state heading region.

**Definition of Done**

- All 5 result states render with correct, CONTENT_GUIDELINES-compliant copy.
- Disclaimer is visible on every result.
- MethodologyEntryPoint and ResetButton function correctly.
- All strings externalized to `en.ts`.
- Accessibility annotations in place.

**Testing Approach**

- Unit: RTL test per result state — render ResultPanel with a mock `AssessmentResult` for each of the 5 states, assert correct headline, summary content, and disclaimer presence.
- Unit: RTL test that ResetButton dispatches reset action and appPhase returns to `idle`.
- Content: grep `en.ts` strings against CONTENT_GUIDELINES prohibited language list (section 9).

**Evidence Required**

- RTL test output for all 5 result states.
- ResetButton test output.
- Prohibited language grep results (zero matches).

---

### S06-04 — Implement ExposureLayer and Legend

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-04                                             |
| Type           | Feature                                            |
| Effort         | ~1 day                                             |
| Dependencies   | S06-02 (assessment response), Epic 05 (MapSurface with deck.gl overlay) |

**Statement**

As a user, I want to see the exposure overlay on the map when modeled exposure is detected, and a legend explaining what the overlay colors mean, so that I can visually understand the spatial extent of the exposure zone for my selected location.

**Why**

The exposure overlay is the visual proof of the assessment result. Without it, the user reads a text summary but cannot see where the exposure zone is relative to the selected point. The legend is required for the overlay to be interpretable — without it, the colored area on the map is meaningless. Together, the overlay and legend close the gap between a textual result and a spatial understanding of coastal exposure.

**Scope Notes**

- ExposureLayer: deck.gl `TileLayer` reading tiles from `layerTileUrlTemplate` in the assessment response.
- Visible only when `resultState === 'ModeledExposureDetected'` (FR-021).
- Removed (not just hidden) when result state is not `ModeledExposureDetected` (FR-022).
- Opacity: 0.7.
- Legend component reads `legendSpec` from the assessment result (`colorStops` array with `value`, `color`, `label`).
- Legend shown when `layerTileUrlTemplate` is not null.
- Legend includes both color swatches and text labels — non-color-dependent communication (NFR-015).
- Legend updates when the result changes (FR-029, FR-031).
- Location marker remains visually distinct from the exposure overlay (FR-028).

**Traceability**

- Requirements: FR-021, FR-022, FR-028, FR-029, FR-031, NFR-015, NFR-016
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 6 — Map Architecture, section 6.2 — deck.gl Integration, section 6.4 — Legend Synchronization)

**Implementation Notes**

- Use the `MapboxOverlay` adapter from `@deck.gl/mapbox` to integrate deck.gl layers with the MapLibre instance (already set up in Epic 05).
- TileLayer configuration:
  ```tsx
  new TileLayer({
    id: 'exposure',
    data: layerTileUrlTemplate, // from assess response
    visible: resultState === 'ModeledExposureDetected',
    opacity: 0.7,
  })
  ```
- When `resultState` changes to a non-exposure state, set `layers: []` on the overlay or set `visible: false` — either approach satisfies FR-022, but removing the layer entirely is cleaner.
- Legend is a simple presentational component. It receives `legendSpec` as a prop and renders a color swatch + label per `colorStop`.
- Legend placement: overlaid on the map, bottom-left corner (desktop). Positioned via CSS, not MapLibre controls.
- For non-color-dependent communication: each legend entry must have a text label in addition to the color swatch. The text label alone must be sufficient to understand the meaning.

**Acceptance Criteria**

1. ExposureLayer renders tiles from `layerTileUrlTemplate` when `resultState` is `ModeledExposureDetected`.
2. ExposureLayer is not visible when `resultState` is any other value.
3. ExposureLayer opacity is 0.7.
4. Legend renders when `layerTileUrlTemplate` is not null.
5. Legend is not rendered when `layerTileUrlTemplate` is null.
6. Legend displays color swatches and text labels from `legendSpec.colorStops`.
7. Legend text labels are sufficient to understand the meaning without color (NFR-015).
8. Legend updates when the assessment result changes (new scenario/horizon producing a different `legendSpec`).
9. Location marker remains visually distinct from the exposure overlay.
10. Map pan and zoom remain interactive when the exposure layer is displayed.

**Definition of Done**

- ExposureLayer renders tiles correctly for `ModeledExposureDetected` results.
- ExposureLayer is removed for all other result states.
- Legend renders correctly from `legendSpec` and meets non-color-dependent requirement.
- No visual regression on the location marker.

**Testing Approach**

- Unit: RTL test that Legend renders correct number of color stops with labels from mock `legendSpec`.
- Integration: verify ExposureLayer `visible` prop toggles correctly based on `resultState` (mock assessment results with and without `layerTileUrlTemplate`).
- Visual: manual verification of overlay rendering against TiTiler tiles in the Docker Compose environment.
- Accessibility: verify legend text labels are readable without color.

**Evidence Required**

- RTL test output for Legend rendering.
- Screenshot or terminal output showing ExposureLayer visibility toggling correctly.
- Manual visual verification screenshot showing overlay + legend + marker on the map.

---

### S06-05 — Implement Loading, Error, and Result-Updating States

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-05                                             |
| Type           | Feature                                            |
| Effort         | ~0.5 days                                          |
| Dependencies   | S06-02 (appPhase transitions), S06-03 (ResultPanel) |

**Statement**

As a user, I want to see clear feedback when the application is loading a new result, updating an existing result, or when an error occurs, so that I am never left staring at a blank or frozen screen.

**Why**

NFR-010 requires no blank or broken UI states. The `result_updating` phase is particularly important: when a user changes scenario or horizon, the previous result must remain visible with a loading indicator so the user knows the system is responding. Without this, rapid control changes produce a jarring flash of empty content. Error states with retry buttons are the only recovery path when the API fails — without them, the user is stuck.

**Scope Notes**

- `result_updating` state: previous result text remains visible in the ResultPanel; a loading indicator (spinner or progress bar) appears alongside or overlaid. Previous result text must be visually muted or annotated to indicate it is stale (PRD section 10.3).
- `assessment_error` state: ErrorBanner with heading and body from `strings.errors.assessmentFailure`, plus a Retry button that re-triggers the last assessment.
- `assessing` state: LoadingState with "Calculating exposure for [Location]..." copy from `strings.loading.assessing`.
- Map pan/zoom remains interactive during all loading and error states (PRD section 10.3).
- `aria-busy="true"` on the result region during `assessing` and `result_updating`.
- `aria-live="polite"` announces the transition from loading to result.
- ErrorBanner uses `role="alert"` for immediate screen reader announcement.

**Traceability**

- Requirements: FR-039, FR-040, NFR-010, NFR-015
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 3 — LoadingState, ErrorBanner; section 5 — UI State Model)

**Implementation Notes**

- During `result_updating`, apply a CSS opacity reduction (e.g., `opacity-50`) and `pointer-events-none` to the previous result text while showing a spinner in the ResultPanel header area.
- ErrorBanner Retry button: calls the same assessment hook with the last-used params. The hook should expose a `refetch` or `retry` function.
- Do not clear the map marker, exposure layer, or legend during `result_updating` — only the text content in the ResultPanel is visually muted.
- During `assessing` (first assessment, no previous result), show the LoadingState component in the ResultPanel area with the loading copy.

**Acceptance Criteria**

1. During `result_updating`, the previous result text is visible but visually muted.
2. During `result_updating`, a loading indicator is visible in the ResultPanel.
3. During `assessing`, the LoadingState shows "Calculating exposure for [Location]..." with the location label.
4. During `assessment_error`, the ErrorBanner shows the correct heading and body text from `strings.errors`.
5. The ErrorBanner Retry button re-triggers the assessment and transitions to `assessing`.
6. Map pan and zoom remain interactive during `assessing`, `result_updating`, and `assessment_error`.
7. `aria-busy="true"` is set on the result region during `assessing` and `result_updating`.
8. ErrorBanner has `role="alert"`.
9. No blank or broken UI state exists during any phase transition.

**Definition of Done**

- All three states (assessing, result_updating, assessment_error) render correctly.
- ARIA attributes are in place.
- Map remains interactive during all loading/error states.
- No blank frames during transitions.

**Testing Approach**

- Unit: RTL test that LoadingState renders correct copy with location label.
- Unit: RTL test that ErrorBanner renders correct copy and Retry button fires the retry action.
- Integration: RTL + MSW — trigger assessment, verify LoadingState appears, then mock a delayed response and verify result replaces loading. Trigger assessment error, verify ErrorBanner appears, click Retry, verify new request fires.
- Visual: manual check that previous result is visually muted during `result_updating`.

**Evidence Required**

- RTL test output for LoadingState, ErrorBanner, and result_updating visual state.
- Manual verification that no blank frames occur during rapid scenario switching.

---

### S06-06 — Implement URL State Synchronization

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-06                                             |
| Type           | Feature                                            |
| Effort         | ~0.5 days                                          |
| Dependencies   | S06-01 (scenario/horizon state), S06-02 (assessment params) |

**Statement**

As a user, I want the current location, scenario, horizon, and zoom level reflected in the browser URL, so that I can bookmark or share a specific assessment view.

**Why**

URL state serialization is a low-cost feature that prevents deep-linking from becoming a breaking change if OQ-08 resolves to "yes." Even if OQ-08 resolves to "no," URL state still functions as a developer convenience for testing and debugging. The implementation cost is minimal — it is read/write of URL search params on state change — and the cost of retrofitting it later is higher than building it now.

**Scope Notes**

- Serialize to URL search params: `/?lat=52.37&lng=4.90&scenario=ssp2-45&horizon=2050&zoom=10`.
- On app load: parse URL params. If valid (lat/lng within range, scenarioId exists in config, horizonYear is 2030/2050/2100), initialize state from URL and trigger an assessment.
- If URL params are invalid or absent, start in `idle` phase with defaults from the config response.
- On state change (location selected, scenario changed, horizon changed, map zoomed): call `router.replace(url)` to update the URL without a navigation event.
- Do not include address text in the URL (BR-016 — no raw address in URL state).

**Traceability**

- Requirements: BR-016 (no raw addresses in URL)
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 4.4 — URL State)

**Implementation Notes**

- Use Next.js `useSearchParams` and `useRouter` for reading and writing URL params.
- Validation: `lat` must be -90 to 90, `lng` must be -180 to 180, `scenarioId` must exist in the config scenarios array, `horizonYear` must be in `[2030, 2050, 2100]`, `zoom` must be 0 to 22.
- On invalid params: silently ignore them and start in `idle` with defaults. Do not show an error.
- `router.replace` (not `router.push`) to avoid polluting browser history with every scenario change.
- Debounce zoom changes to avoid excessive URL updates during map pan/zoom.

**Acceptance Criteria**

1. Selecting a location updates the URL with `lat` and `lng` params.
2. Changing scenario updates the URL `scenario` param.
3. Changing horizon updates the URL `horizon` param.
4. Zooming the map updates the URL `zoom` param (debounced).
5. Loading the app with valid URL params initializes state from those params and triggers an assessment.
6. Loading the app with invalid or absent URL params starts in `idle` with config defaults.
7. URL never contains raw address text.
8. URL updates use `router.replace`, not `router.push`.

**Definition of Done**

- URL reflects current state after every user interaction.
- App initializes correctly from URL params.
- No raw address text in URL.
- Browser back/forward behavior is not disrupted.

**Testing Approach**

- Unit: test URL parsing logic with valid, invalid, partial, and absent params.
- Integration: RTL test — render app with mock URL params, verify assessment triggers with correct coordinates and scenario/horizon. Render app without params, verify idle state.
- Manual: copy URL from one browser tab, paste into another, verify same state loads.

**Evidence Required**

- Unit test output for URL parsing.
- Integration test output showing initialization from URL params.

---

### S06-07 — Assessment Flow Component Integration Tests

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| ID             | S06-07                                             |
| Type           | Quality Assurance                                  |
| Effort         | ~1 day                                             |
| Dependencies   | S06-01 through S06-06 (all feature stories)        |

**Statement**

As the engineer maintaining delivery quality, I want comprehensive integration and E2E tests covering the full assessment flow, so that regressions in the assessment cycle are caught automatically before they reach users.

**Why**

The assessment flow involves multiple components (controls, API hook, result panel, exposure layer, legend, URL state) interacting through shared state. Unit tests on individual components are necessary but insufficient — they cannot catch integration failures where component A updates state that component B fails to read. Integration and E2E tests validate the assembled behavior and catch the class of bugs that only appear when the full system is wired together.

**Scope Notes**

- RTL + MSW integration tests:
  - Full flow: search → select candidate → result displayed → change scenario → result updates → change horizon → result updates → reset → idle.
  - All 5 result states render correct copy when the mock API returns each state.
  - Stale request handling: rapid scenario changes produce only the final result.
  - Cache behavior: switch to scenario A, switch to scenario B, switch back to scenario A — verify no network request on the third switch (NFR-004).
  - Error and retry: mock API error → ErrorBanner displayed → click Retry → success response → result displayed.
- Authored `@playwright/test` E2E tests:
  - Full assessment flow against local Docker Compose environment.
  - Keyboard-only flow: Tab through controls, Arrow keys to change scenario/horizon, Enter to open methodology entry point, Enter to reset.
  - URL state: navigate to app with URL params, verify result loads.
- Use `playwright-cli` for ad-hoc visual verification of result states and control interactions during development.
- Accessibility: `@axe-core/playwright` scan on result panel in each of the 5 result states.

**Traceability**

- Requirements: FR-014, FR-015, FR-018, FR-019, FR-021, FR-024, FR-029, FR-030, FR-031, FR-040, FR-041, BR-010, NFR-004, NFR-010, NFR-015
- Architecture: `docs/architecture/03a-frontend-architecture.md` (section 13 — Frontend Testing Summary)

**Implementation Notes**

- MSW handlers should return different `resultState` values based on request params (e.g., a specific lat/lng returns `OutOfScope`, another returns `DataUnavailable`). This avoids brittle mocks.
- For cache testing: MSW can count the number of requests received. Assert that the third scenario switch (back to A) does not increment the request count.
- `@playwright/test` tests should use the local Docker Compose environment with seeded data (Epic 02 seed data + Epic 03 COGs).
- axe-core scan: run after each result state renders, assert zero violations at AA level.

**Acceptance Criteria**

1. RTL integration test passes for the full search → result → control change → reset flow.
2. RTL integration test verifies all 5 result states render correct headlines and summaries.
3. RTL integration test verifies stale request handling — only the latest result is rendered after rapid changes.
4. RTL integration test verifies TanStack Query cache — no redundant network request on revisiting a cached scenario/horizon.
5. RTL integration test verifies error → retry → success flow.
6. `@playwright/test` E2E test passes for the full assessment flow in local Docker Compose.
7. `@playwright/test` E2E test passes for keyboard-only assessment flow.
8. `@playwright/test` E2E test passes for URL-initialized assessment.
9. axe-core scan passes with zero AA violations for all 5 result states.

**Definition of Done**

- All integration tests pass in CI.
- All `@playwright/test` E2E tests pass against local Docker Compose.
- axe-core scan shows zero AA violations.
- Test coverage report shows assessment flow hooks and components covered.

**Testing Approach**

- This story is the testing story. Its deliverable is the test suite itself.

**Evidence Required**

- CI output showing all RTL integration tests passing.
- `@playwright/test` run output with screenshots for each result state.
- axe-core violation report (zero violations).

---

## 8  Technical Deliverables

| Deliverable                                | Format                         | Produced By |
| ------------------------------------------ | ------------------------------ | ----------- |
| ScenarioControl component                  | React component (committed)    | S06-01      |
| HorizonControl component                   | React component (committed)    | S06-01      |
| Assessment TanStack Query hook             | TypeScript module (committed)  | S06-02      |
| ResultPanel + ResultStateHeader + ResultSummary | React components (committed) | S06-03  |
| Disclaimer component                       | React component (committed)    | S06-03      |
| MethodologyEntryPoint component            | React component (committed)    | S06-03      |
| ResetButton component                      | React component (committed)    | S06-03      |
| ExposureLayer integration                  | deck.gl TileLayer (committed)  | S06-04      |
| Legend component                           | React component (committed)    | S06-04      |
| LoadingState and ErrorBanner enhancements  | React components (committed)   | S06-05      |
| URL state sync module                      | TypeScript module (committed)  | S06-06      |
| `en.ts` result state strings               | i18n strings (committed)       | S06-03      |
| Integration and E2E test suite             | Test files (committed)         | S06-07      |

---

## 9  Data, API, and Infrastructure Impact

This epic does not modify the backend API, database schema, or infrastructure. It consumes:

- **`POST /v1/assess`** (Epic 04): the primary API call for assessment results.
- **`GET /v1/config/scenarios`** (Epic 04/05): fetched on app load, provides scenario and horizon data for controls.
- **TiTiler tile endpoint** (Epic 02/03): `layerTileUrlTemplate` from the assess response points to TiTiler, which serves COG tiles.

No new API endpoints, database tables, or Azure resources are required.

---

## 10  Security and Privacy

- No raw address text is stored in URL state, localStorage, or analytics events (BR-016).
- URL params contain coordinates only (`lat`, `lng`) — never address strings.
- No new API keys or secrets are introduced.
- All API calls go through the existing backend proxy — no direct browser-to-TiTiler calls except for tile fetching, which uses the domain-restricted TiTiler CORS configuration.

---

## 11  Observability

- `performance.mark('assessment:start')` and `performance.mark('assessment:complete')` in the assessment hook — feeds NFR-003/NFR-004 latency measurement.
- TanStack Query `onError` callbacks capture assessment API failures for error tracking.
- React Error Boundary at AppShell level (established in Epic 05) catches unhandled rendering exceptions in the result panel and exposure layer.

---

## 12  Testing

| Story   | Testing Approach                                                                                       |
| ------- | ------------------------------------------------------------------------------------------------------ |
| S06-01  | RTL unit tests for ScenarioControl and HorizonControl; axe-core accessibility scan                     |
| S06-02  | RTL + MSW — cache behavior, stale request handling, appPhase transitions                               |
| S06-03  | RTL unit tests for all 5 result states; prohibited language grep; ResetButton test                      |
| S06-04  | RTL Legend test; manual visual verification of ExposureLayer; accessibility text-label check            |
| S06-05  | RTL tests for LoadingState, ErrorBanner, result_updating visual state; manual blank-frame check         |
| S06-06  | Unit tests for URL parsing; RTL integration test for URL-initialized state                             |
| S06-07  | Full RTL integration suite; `@playwright/test` E2E; `@axe-core/playwright` AA scan on all 5 result states |

---

## 13  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| TiTiler tile rendering latency causes perceived sluggishness when ExposureLayer loads. | Medium | Medium | deck.gl TileLayer handles progressive tile loading with built-in loading states. Set tile loading priority to viewport center. Validate latency in Docker Compose before production. |
| Rapid scenario/horizon switching exposes race conditions in state updates. | High | Medium | TanStack Query's automatic abort on key change handles the primary case. Add explicit integration tests (S06-07) for rapid switching. The requestSeq guard is a fallback if edge cases emerge. |
| CONTENT_GUIDELINES copy review reveals prohibited language in result templates. | Low | Low | Grep `en.ts` against the prohibited language list (CONTENT_GUIDELINES section 9) as part of the testing approach in S06-03. Automate this check in CI. |
| deck.gl and MapLibre version incompatibility causes rendering artifacts. | Medium | Low | Pin exact versions in `package.json`. Test overlay rendering in Docker Compose before merging. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| Epic 04 `POST /v1/assess` endpoint is complete and returns all fields specified in the API contract. | ResultPanel and ExposureLayer cannot function. Blocked until Epic 04 delivers the endpoint. |
| Epic 05 MapSurface with deck.gl overlay infrastructure is in place. | ExposureLayer (S06-04) cannot be integrated. Blocked until Epic 05 delivers the map shell. |
| Config scenarios query (`GET /v1/config/scenarios`) is available and cached from Epic 05. | ScenarioControl and HorizonControl (S06-01) cannot populate. Blocked until config endpoint is available. |
| TiTiler is accessible from the browser via the `layerTileUrlTemplate` with CORS configured. | ExposureLayer tiles will fail to load. Requires CORS configuration from Epic 02. |

---

## 14  Epic Acceptance Criteria

1. ScenarioControl renders all scenarios from config, shows active selection, and triggers new assessment on change.
2. HorizonControl renders 2030, 2050, 2100, shows active selection, and triggers new assessment on change.
3. All 5 result states render with correct, CONTENT_GUIDELINES-compliant headlines and summaries.
4. Disclaimer is visible on every result.
5. ExposureLayer displays tiles when `resultState` is `ModeledExposureDetected` and is hidden for all other states.
6. Legend renders from `legendSpec` with non-color-dependent labels.
7. `result_updating` shows previous result with loading indicator; no blank frames.
8. `assessment_error` shows ErrorBanner with Retry button; retry re-triggers the assessment.
9. Switching to a previously viewed scenario/horizon returns a cached result within 1.5 seconds (NFR-004).
10. Rapid control changes render only the latest result (FR-040).
11. ResetButton returns the app to `idle` state.
12. URL reflects current state; app initializes from valid URL params.
13. Keyboard-only navigation through the full assessment flow works (NFR-015).
14. axe-core scan passes with zero WCAG 2.2 AA violations on all 5 result states.

---

## 15  Definition of Done

- All 7 user stories completed with evidence committed to the repository.
- All 5 result states render with correct copy verified against CONTENT_GUIDELINES.
- Stale request handling verified by integration test.
- TanStack Query cache verified — no redundant requests on revisited scenario/horizon.
- `@playwright/test` E2E test passes the full assessment flow in local Docker Compose.
- axe-core scan shows zero WCAG 2.2 AA violations.
- No prohibited language from CONTENT_GUIDELINES section 9 appears in any committed string.
- No unresolved blocker remains within this epic's scope.

---

## 16  Demo and Evidence Required

| Evidence                                                       | Location (expected)                                      |
| -------------------------------------------------------------- | -------------------------------------------------------- |
| ScenarioControl and HorizonControl RTL test output             | CI test run artifacts                                    |
| Assessment hook MSW test output (cache, stale, transitions)    | CI test run artifacts                                    |
| RTL test output for all 5 result states                        | CI test run artifacts                                    |
| ExposureLayer + Legend visual verification screenshot           | Linked from S06-04 evidence                              |
| `@playwright/test` E2E full assessment flow recording          | CI test run artifacts or linked video                    |
| `@playwright/test` keyboard-only flow recording                | CI test run artifacts or linked video                    |
| axe-core AA violation report (zero violations)                 | CI test run artifacts                                    |
| Prohibited language grep result (zero matches)                 | CI test run artifacts                                    |
| URL state round-trip verification (paste URL → result loads)   | `@playwright/test` or manual screenshot                  |
