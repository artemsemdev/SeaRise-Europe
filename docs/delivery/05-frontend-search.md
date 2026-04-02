# Epic 05 — Frontend Shell and Search Flow

| Field          | Value                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Epic ID        | E-05                                                                                               |
| Phase          | 1 — MVP                                                                                            |
| Status         | Not Started                                                                                        |
| Effort         | ~6 days                                                                                            |
| Dependencies   | Epic 04 (geocode + config endpoints available)                                                     |
| Stories        | 8 (S05-01 through S05-08)                                                                          |
| Produces       | First user-interactive surface — the Next.js app with map, search, and candidate selection          |

---

## 1  Objective

Deliver the Next.js 14+ App Router frontend shell with a working search-to-candidate-selection flow, interactive map, state management, and all conditional UI states, producing the first surface a user can interact with.

---

## 2  Why This Epic Exists

The frontend is the only delivery vehicle for the product's value. Every prior epic — infrastructure, pipeline, API — exists to support what the user sees and touches here. Without this epic, the API has no consumer, the precomputed COG layers have no renderer, and the project has no demonstrable product. This epic establishes the application shell, the state machine that governs all UI transitions, the map surface, and the complete search-to-candidate-selection flow. It is the first point at which the system becomes interactive.

---

## 3  Scope

### 3.1 In Scope

- Next.js 14+ App Router project scaffold with TailwindCSS, Dockerfile, and responsive layout.
- Server Components for static shell (`layout.tsx`, `page.tsx`); Client Component boundary at `AppShell.tsx`.
- Zustand stores: `appStore` (discriminated union phase state machine), `mapStore` (viewport + selectedLocation), `uiStore` (panel visibility).
- TanStack Query v5 integration for config fetch and geocoding.
- MapLibre GL JS map surface with dynamic import (SSR: false), Europe-centered initial view, pan/zoom, location marker, attribution control.
- SearchBar with validation (empty blocked, max 200 chars), ARIA role="search".
- CandidateList with keyboard-navigable listbox, up to 5 candidates, label + displayContext.
- EmptyState, LoadingState, ErrorBanner components for all conditional UI phases.
- Localization-ready string file (`lib/i18n/en.ts`) with all UI copy externalized.
- Config fetch on app load (`GET /v1/config/scenarios`, staleTime: Infinity).
- Vitest + React Testing Library unit tests, authored `@playwright/test` smoke test, `playwright-cli` exploratory validation, bundle size baseline.

### 3.2 Out of Scope

- ResultPanel, ScenarioControl, HorizonControl (Epic 06).
- ExposureLayer (deck.gl TileLayer) and Legend rendering (Epic 06).
- MethodologyPanel (Epic 06).
- Production geocoding provider integration (API-side; this epic consumes the existing `POST /v1/geocode` endpoint).
- Custom domain, CDN, or production DNS.
- Analytics instrumentation (OQ-10).
- URL state serialization (OQ-08).
- Tablet/mobile visual parity polish (OQ-12).

---

## 4  Traceability

### 4.1 Product Requirement Traceability

| Requirement | Description                                           |
| ----------- | ----------------------------------------------------- |
| FR-001      | Landing page with search bar and map                  |
| FR-002      | Free-text search input                                |
| FR-003      | Empty search blocked (AC-001)                         |
| FR-004      | Geocoding API call and candidate return               |
| FR-005      | Candidate selection triggers assessment               |
| FR-006      | Map marker on selected location                       |
| FR-007      | Map click triggers new assessment                     |
| FR-008      | Map click captures coordinates                        |
| FR-026      | Europe-centered map on load                           |
| FR-027      | Pan and zoom enabled                                  |
| FR-028      | Visually distinct location marker                     |
| FR-034      | Attribution control on map                            |
| FR-038      | No geocoding results state                            |
| FR-039      | Error state with retry                                |
| FR-041      | Reset to initial state                                |
| BR-006      | Preserve geocoding provider rank order                |
| BR-007      | Maximum 5 geocoding candidates                        |
| BR-008      | Maximum 200 character input                           |
| BR-009      | displayContext for disambiguation                     |
| BR-016      | No raw address persistence                            |
| NFR-001     | First meaningful paint <=4s cold load                 |
| NFR-006     | No secrets in client-side code                        |
| NFR-010     | No blank or broken UI states                          |
| NFR-015     | WCAG 2.2 AA                                           |
| NFR-018     | English only; all copy externalized                   |

### 4.2 Architecture Traceability

| Architecture Document                              | Relevance                                          |
| -------------------------------------------------- | -------------------------------------------------- |
| `docs/architecture/03a-frontend-architecture.md`   | Primary reference — component tree, state machine, rendering strategy, responsive layout, performance targets |
| `docs/architecture/03-component-view.md`           | API contracts consumed by frontend                 |
| `docs/architecture/06-api-and-contracts.md`        | Endpoint contracts for geocode and config           |
| `docs/architecture/07-security-architecture.md`    | Basemap key management, no secrets in client       |
| `docs/architecture/10-testing-strategy.md`         | Frontend testing patterns                          |

### 4.3 Mock Visual Specification

The clickable prototype is the authoritative visual specification. Each story must match the corresponding mock screen. See `docs/product/Mock/MOCK_REQUIREMENTS_MAP.md` for the full traceability map.

| Story   | Mock Screen(s) to Match                                    |
| ------- | ---------------------------------------------------------- |
| S05-01  | `01-landing.html` (shell layout, responsive skeleton)      |
| S05-03  | `01-landing.html`, `06-exposure.html` (map surface, dark tiles, markers, overlays) |
| S05-04  | `01-landing.html` (search input), `02-search-loading.html` (loading state) |
| S05-05  | `03-candidates.html` (candidate dropdown)                  |
| S05-06  | All screens (localized strings, config-driven labels)      |
| S05-07  | `01-landing.html` (empty), `02-search-loading.html` (loading), `04-no-results.html` (no results), `12-error-geocoding.html` (error) |
| S05-08  | All above screens (smoke tests across all states)          |

---

## 5  Implementation Plan

Work through stories in the following order, chosen to build the dependency chain from shell outward:

1. **S05-01 — Initialize Next.js Project and App Shell.** Everything depends on the project existing.
2. **S05-02 — Implement Zustand State Stores.** State machine must exist before any component can read or write phase transitions.
3. **S05-06 — Implement Config Fetch and Localization Setup.** Strings and config are consumed by every subsequent component.
4. **S05-03 — Implement MapSurface with MapLibre.** Map is the largest visual surface and has the longest integration lead time.
5. **S05-04 — Implement SearchBar and Geocoding Integration.** Depends on appStore (S05-02) and strings (S05-06).
6. **S05-05 — Implement CandidateList and Location Selection.** Depends on SearchBar flow and mapStore.
7. **S05-07 — Implement EmptyState, LoadingState, ErrorBanner.** Depends on appStore phases and strings.
8. **S05-08 — Frontend Smoke Tests and Performance Baseline.** Must be last; tests everything above.

### Execution Order Map

```
S05-01 (Next.js Project + App Shell)
  │
  └──► S05-02 (Zustand State Stores)
         │
         └──► S05-06 (Config Fetch + i18n Strings)
                │
                ├──► S05-03 (MapSurface + MapLibre)    ◄── parallel with S05-04
                │
                ├──► S05-04 (SearchBar + Geocoding)     ◄── parallel with S05-03
                │       │
                │       └──► S05-05 (CandidateList + Location Selection)
                │
                └──► S05-07 (EmptyState, Loading, Error) ◄── parallel with S05-03/S05-04
                       │
                       └──► S05-08 (Smoke Tests + Perf Baseline)
```

**Rationale:** S05-01 and S05-02 are strictly sequential foundations. S05-06 (strings + config) comes next because every component consumes it. After that, three parallel tracks open: map initialization (S05-03), search flow (S05-04→S05-05), and conditional UI states (S05-07). S05-08 must be last because it tests the integrated frontend.

---

## 6  User Stories

---

### S05-01 — Initialize Next.js Project and App Shell

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-01                                                          |
| Type           | Platform                                                        |
| Effort         | ~1 day                                                          |
| Dependencies   | None                                                            |

**Statement**

As the engineer, I want the Next.js 14+ App Router project scaffolded with TailwindCSS, the root layout, page, and AppShell client boundary in place, so that all subsequent frontend stories have a working project to build into.

**Why**

Every frontend component needs a project to live in. The rendering strategy — Server Components for the static shell, a single Client Component boundary at AppShell — is an architectural decision that must be established first. Getting it wrong means refactoring every component that comes after.

**Scope Notes**

- Initialize Next.js 14+ with App Router (`app/` directory), TypeScript strict mode.
- Install and configure TailwindCSS with build-time purge.
- Create `app/layout.tsx` (Server Component): HTML skeleton, `<head>` metadata, global CSS import, `next/font` for web font loading.
- Create `app/page.tsx` (Server Component): renders `<AppShell />`.
- Create `app/components/AppShell.tsx` with `'use client'` directive: root of the interactive tree. Initially renders a placeholder layout structure.
- Implement responsive layout skeleton using TailwindCSS:
  - Desktop (>=1024px): split-pane — left panel ~360px + map area fills remaining width.
  - Tablet (768-1023px): map full width, bottom panel area.
  - Mobile (<768px): map full viewport, bottom sheet area.
- Create `Dockerfile` for the frontend container (multi-stage: build + production `next start`).
- Create `.env.local.example` documenting required environment variables (`NEXT_PUBLIC_BASEMAP_STYLE_URL`, `NEXT_PUBLIC_API_BASE_URL`).
- Confirm `next build` completes without errors and `next start` serves the page.

**Traceability**

- Requirements: FR-001, NFR-001, NFR-006
- Architecture: `docs/architecture/03a-frontend-architecture.md` sections 2, 7, 9

**Implementation Notes**

- Use `next/font/google` or `next/font/local` to avoid layout shift on font load.
- TailwindCSS responsive prefixes (`md:`, `lg:`) for breakpoints — no JavaScript-driven breakpoints.
- The Dockerfile should produce a minimal production image (`node:20-alpine` base).
- Do not install MapLibre, deck.gl, Zustand, or TanStack Query yet — those belong to their respective stories.

**Acceptance Criteria**

1. `next build` completes with zero errors and zero warnings.
2. `next start` serves the page at `localhost:3000` with the AppShell client boundary rendering.
3. `layout.tsx` and `page.tsx` are Server Components (no `'use client'` directive).
4. `AppShell.tsx` has `'use client'` directive.
5. Responsive layout renders correctly at desktop (>=1024px), tablet (768-1023px), and mobile (<768px) widths — verified by browser dev tools resize.
6. `Dockerfile` builds successfully and `docker run` serves the page.
7. `.env.local.example` exists with all required variable names documented.
8. No hardcoded UI copy strings exist in any component (placeholder text is acceptable at this stage, sourced from a temporary constant).

**Definition of Done**

- Project scaffold committed with all files listed above.
- `next build` and Docker build both succeed in CI.
- Responsive layout verified at three breakpoints.

**Testing Approach**

- Build verification: `next build` exits 0.
- Docker verification: `docker build` and `docker run` succeed, `curl localhost:3000` returns HTML.
- Manual visual verification at three viewport widths.

**Evidence Required**

- `next build` output (clean).
- Docker build output (clean).
- Screenshot or terminal evidence of page serving at `localhost:3000`.

---

### S05-02 — Implement Zustand State Stores

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-02                                                          |
| Type           | Technical Enabler                                               |
| Effort         | ~0.5 days                                                       |
| Dependencies   | S05-01 (project exists)                                         |

**Statement**

As the engineer, I want the Zustand state stores implemented with the AppPhase discriminated union, map state, and UI state, so that all components have a shared, type-safe state machine to read and write.

**Why**

The AppPhase state machine is the central coordination mechanism for the entire frontend. It is a discriminated union that prevents impossible UI combinations — you cannot show a result panel during geocoding, or a candidate list during assessment. Every conditional render in AppShell depends on the current phase. Without the state machine, components have no way to know what to render.

**Scope Notes**

- Install Zustand.
- Create `lib/store/appStore.ts`:
  - `AppPhase` discriminated union type with all phases: `idle`, `geocoding`, `geocoding_error`, `no_geocoding_results`, `candidate_selection`, `assessing`, `result`, `result_updating`, `assessment_error`.
  - Each phase variant carries its required payload (e.g., `candidate_selection` carries `candidates: GeocodingCandidate[]`; `result` carries `location` and `result`).
  - Transition actions: `startGeocoding()`, `setGeocodingError(error)`, `setNoResults()`, `setCandidates(candidates)`, `selectCandidate(location)`, `setResult(result)`, `setResultUpdating()`, `setAssessmentError(error)`, `reset()`.
  - `reset()` transitions from any phase to `idle`.
- Create `lib/store/mapStore.ts`:
  - `viewport: { center: [number, number]; zoom: number }` — initial: `{ center: [10, 54], zoom: 4 }`.
  - `selectedLocation: SelectedLocation | null` — initial: `null`.
  - Actions: `setViewport()`, `setSelectedLocation()`.
- Create `lib/store/uiStore.ts`:
  - `isMethodologyPanelOpen: boolean` — initial: `false`.
  - Actions: `openMethodologyPanel()`, `closeMethodologyPanel()`.
- Create `lib/types/index.ts` with shared types: `GeocodingCandidate`, `SelectedLocation`, `AssessmentResult`, `GeocodingError`, `AssessmentError`.

**Traceability**

- Requirements: NFR-010 (no impossible UI states)
- Architecture: `docs/architecture/03a-frontend-architecture.md` sections 4.1, 4.5, 4.6

**Implementation Notes**

- The discriminated union should use a `phase` string literal discriminator so that TypeScript's control flow analysis narrows the type in `switch` statements.
- Keep Zustand stores as thin coordination layers — no API call logic belongs here. API calls live in TanStack Query hooks.
- Export selectors for each store to avoid unnecessary re-renders (e.g., `useAppPhase()` reads only the phase, not the entire store).

**Acceptance Criteria**

1. `appStore` exports the `AppPhase` discriminated union type with all 9 phase variants and their payloads.
2. All transition actions enforce valid transitions (e.g., `setCandidates` is only callable and sets phase to `candidate_selection`).
3. `reset()` transitions from any phase to `idle`.
4. `mapStore` initializes with `center: [10, 54], zoom: 4` and `selectedLocation: null`.
5. `uiStore` initializes with `isMethodologyPanelOpen: false`.
6. All stores are fully typed — no `any` types.
7. Unit tests verify every valid transition in the appStore state machine.

**Definition of Done**

- All three stores committed with TypeScript types.
- Unit tests pass for all state transitions.

**Testing Approach**

- Vitest unit tests: create the store, call each transition action, assert resulting phase and payload. Test `reset()` from every phase.

**Evidence Required**

- Vitest test output showing all transition tests passing.

---

### S05-03 — Implement MapSurface with MapLibre

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-03                                                          |
| Type           | Feature                                                         |
| Effort         | ~1 day                                                          |
| Dependencies   | S05-01 (project), S05-02 (mapStore)                             |

**Statement**

As a user, I want to see an interactive map of Europe when I open the application, so that I have a geographic context for searching and viewing coastal exposure results.

**Why**

The map is the largest visual element in the application and the primary spatial context for every result. It must be present on initial load, centered on Europe, and responsive to user interaction (pan, zoom, click). MapLibre GL JS requires browser APIs (WebGL, `window`) and cannot be server-side rendered, so it must be dynamically imported with SSR disabled.

**Scope Notes**

- Install MapLibre GL JS.
- Create `app/components/map/MapSurface.tsx`:
  - Dynamic import in AppShell with `{ ssr: false }` and a loading placeholder.
  - MapLibre map instance created in `useEffect`, stored in `useRef` (not React state).
  - Initial view: `center: [10, 54], zoom: 4` (FR-026).
  - Basemap style URL from `process.env.NEXT_PUBLIC_BASEMAP_STYLE_URL` (OQ-07).
  - Pan and zoom enabled (FR-027).
  - Attribution control enabled, bottom-right corner (FR-034).
  - `move` event syncs viewport to `mapStore.setViewport()`.
  - Click handler: if `selectedLocation` is already set, capture click coordinates and dispatch new assessment via appStore transition (FR-007, FR-008). If no location selected, click is a no-op.
- Create `app/components/map/LocationMarker.tsx`:
  - MapLibre `Marker` placed at `selectedLocation` coordinates when set (FR-006).
  - Visually distinct from any future exposure overlay — use a contrasting color or custom icon (FR-028).
  - Marker position updates when `selectedLocation` changes (map flies to new coordinates).
- Map container has `role="img"` and dynamically updated `aria-label` (e.g., "Interactive map of Europe" initially, "Interactive map showing selected location at [label]" after selection).
- Map container fills available space in the responsive layout (right pane on desktop, full width on tablet/mobile).

**Traceability**

- Requirements: FR-001, FR-006, FR-007, FR-008, FR-026, FR-027, FR-028, FR-034
- Architecture: `docs/architecture/03a-frontend-architecture.md` sections 3 (MapSurface), 6 (Map Architecture)

**Implementation Notes**

- Use `next/dynamic` for the SSR-false import. Provide a `loading` prop that renders a gray placeholder with `animate-pulse` to avoid layout shift.
- The map `useRef` pattern avoids React re-renders on every frame during pan/zoom. Only write to mapStore on `moveend` (not `move`) to throttle store updates.
- `map.flyTo()` when `selectedLocation` changes to animate the transition.
- Destroy the map instance on component unmount (`map.remove()` in cleanup function).
- Do not implement the ExposureLayer (deck.gl) in this story — that belongs to Epic 06.

**Acceptance Criteria**

1. MapSurface renders a MapLibre GL JS map centered on Europe (`center: [10, 54], zoom: 4`) on initial load.
2. Map is loaded via dynamic import with `ssr: false` — no server-side rendering errors.
3. Map supports pan and zoom interaction.
4. Attribution control is visible in the bottom-right corner.
5. Clicking the map when a location is already selected captures coordinates and triggers the assessment flow via appStore.
6. LocationMarker appears at the correct coordinates when `selectedLocation` is set.
7. Map flies to the selected location when `selectedLocation` changes.
8. Map container has `role="img"` and a descriptive `aria-label`.
9. Map fills available space in the layout at all three breakpoints.

**Definition of Done**

- MapSurface and LocationMarker committed.
- Map renders in the browser without console errors.
- Click handler, marker, and flyTo behavior verified manually.

**Testing Approach**

- Vitest + RTL: verify the dynamic import renders the loading placeholder, then the map container element.
- Manual verification: open in browser, pan/zoom, confirm attribution, confirm marker placement on simulated selection.
- `@playwright/test` smoke test (deferred to S05-08): page loads without errors, map canvas is present. Use `playwright-cli` for ad-hoc visual verification during development.

**Evidence Required**

- Screenshot of map rendering at Europe view.
- Screenshot of LocationMarker at a test coordinate.
- Browser console showing no errors on load.

---

### S05-04 — Implement SearchBar and Geocoding Integration

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-04                                                          |
| Type           | Feature                                                         |
| Effort         | ~1 day                                                          |
| Dependencies   | S05-02 (appStore), S05-06 (strings)                             |

**Statement**

As a user, I want to type a European location into a search bar and submit it, so that the application can find matching locations for me to choose from.

**Why**

Search is the primary entry point into the application. Every user journey begins with a text query. The SearchBar must validate input (block empty submissions, enforce the 200-character limit), trigger the geocoding API call, and transition the application through the correct phases. If this component is wrong, the user cannot start the flow.

**Scope Notes**

- Install TanStack Query v5.
- Configure `QueryClientProvider` in AppShell with default options.
- Create `lib/api/geocoding.ts`: TanStack Query mutation hook wrapping `POST /v1/geocode`. Query key: `['geocode', query]`. Stale time: 30 seconds.
- Create `app/components/search/SearchBar.tsx`:
  - Free-text `<input>` with `maxLength={200}` (BR-008).
  - Inline validation: empty submission blocked with no API call (FR-003/AC-001).
  - Submit on Enter key or button click.
  - On valid submit: call `appStore.startGeocoding()`, fire geocoding mutation.
  - On mutation success with >=2 candidates: `appStore.setCandidates(candidates)`.
  - On mutation success with 1 candidate: `appStore.selectCandidate(location)` (auto-select, set selectedLocation in mapStore).
  - On mutation success with 0 candidates: `appStore.setNoResults()`.
  - On mutation error: `appStore.setGeocodingError(error)`.
  - Does NOT store or log raw input text to any persistent medium (BR-016).
  - ARIA: `role="search"` on the form, `aria-label="Search for a European location"` on the input.
- All user-visible text sourced from `lib/i18n/en.ts`.

**Traceability**

- Requirements: FR-001, FR-002, FR-003, FR-004, BR-006, BR-007, BR-008, BR-016, NFR-015
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 3 (SearchBar), `docs/architecture/06-api-and-contracts.md` (POST /v1/geocode contract)

**Implementation Notes**

- TanStack Query's `useMutation` is the appropriate pattern for geocoding since it is user-triggered and not idempotent across different queries.
- The API base URL comes from `NEXT_PUBLIC_API_BASE_URL` environment variable.
- Preserve the geocoding provider's rank order in the candidate list (BR-006) — do not re-sort results.
- The 1-candidate auto-select behavior is marked as "proposed" in the architecture doc. Implement it, but keep the logic isolated so it can be toggled.

**Acceptance Criteria**

1. SearchBar renders with a text input and submit button.
2. Empty submission is blocked — no API call fires, no phase transition occurs.
3. Input longer than 200 characters is prevented (`maxLength` attribute).
4. On valid submit, appPhase transitions to `geocoding`.
5. On successful geocoding with >=2 candidates, appPhase transitions to `candidate_selection` with candidates array.
6. On successful geocoding with 1 candidate, appPhase transitions to `assessing` and selectedLocation is set in mapStore.
7. On successful geocoding with 0 candidates, appPhase transitions to `no_geocoding_results`.
8. On geocoding failure, appPhase transitions to `geocoding_error`.
9. SearchBar has `role="search"` and input has `aria-label="Search for a European location"`.
10. No raw input text is written to localStorage, sessionStorage, or any persistent store.

**Definition of Done**

- SearchBar component and geocoding hook committed.
- TanStack Query configured in AppShell.
- All phase transitions verified by unit tests.

**Testing Approach**

- Vitest + RTL: render SearchBar, simulate empty submit (verify no API call), simulate valid submit with mocked API responses for each candidate count (0, 1, >=2), verify appStore phase after each.
- Vitest: geocoding hook unit test with MSW mock for `POST /v1/geocode`.

**Evidence Required**

- Vitest test output showing all SearchBar and geocoding hook tests passing.

---

### S05-05 — Implement CandidateList and Location Selection

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-05                                                          |
| Type           | Feature                                                         |
| Effort         | ~1 day                                                          |
| Dependencies   | S05-04 (SearchBar populates candidates), S05-03 (map for flyTo) |

**Statement**

As a user, I want to see a list of matching locations after searching and select the correct one, so that the application can assess coastal exposure for my intended location.

**Why**

Geocoding frequently returns multiple matches for ambiguous queries (e.g., "Barcelona" matches Spain and Venezuela). The CandidateList is the disambiguation surface. It must show enough context for the user to distinguish candidates (label + displayContext), respect the provider's rank order, and transition the application to the assessment phase on selection. If this component is missing or broken, the user is stuck after searching.

**Scope Notes**

- Create `app/components/search/CandidateList.tsx`:
  - Rendered when `appPhase.phase === 'candidate_selection'`.
  - Displays up to 5 candidates (BR-007) from `appPhase.candidates`.
  - Each candidate shows `label` and `displayContext` (BR-009).
  - Candidates appear in provider rank order (BR-006) — no re-sorting.
  - `role="listbox"` on the container, `role="option"` on each candidate (NFR-015).
  - Keyboard navigable: arrow keys move focus between options, Enter/Space selects (NFR-015).
  - On selection:
    - Set `selectedLocation` in mapStore (coordinates + label).
    - Transition appPhase to `assessing`.
    - Map flies to selected coordinates (consumed by MapSurface from mapStore).
  - CandidateList is dismissed after selection.
- All user-visible text sourced from `lib/i18n/en.ts`.

**Traceability**

- Requirements: FR-005, BR-006, BR-007, BR-009, NFR-015
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 3 (CandidateList)

**Implementation Notes**

- Use `aria-activedescendant` for keyboard navigation rather than moving DOM focus, as this keeps the input focused while allowing screen readers to announce the active option.
- When the candidate list appears, focus the first option (or announce it via `aria-live`).
- The selection action is the bridge between search and assessment. It writes to both `appStore` (phase) and `mapStore` (selectedLocation). Keep these two writes in a single handler to avoid intermediate inconsistent states.

**Acceptance Criteria**

1. CandidateList renders only when `appPhase.phase === 'candidate_selection'`.
2. Up to 5 candidates are displayed, each showing `label` and `displayContext`.
3. Candidates appear in the order received from the API (provider rank preserved).
4. Container has `role="listbox"`; each candidate has `role="option"`.
5. Arrow keys navigate between candidates; Enter or Space selects the focused candidate.
6. On selection, `selectedLocation` is set in mapStore with correct coordinates and label.
7. On selection, appPhase transitions to `assessing`.
8. CandidateList is no longer rendered after selection.
9. Screen reader announces the candidate list when it appears.

**Definition of Done**

- CandidateList committed with keyboard navigation and selection logic.
- Unit tests pass for rendering, keyboard navigation, and selection behavior.

**Testing Approach**

- Vitest + RTL: render CandidateList with mock candidates, verify correct number of items rendered, verify `role` attributes, simulate keyboard navigation (arrow keys), simulate selection (Enter), assert appStore and mapStore state after selection.
- Accessibility: axe-core scan on the rendered CandidateList (no violations).

**Evidence Required**

- Vitest test output showing all CandidateList tests passing.
- axe-core scan result (zero violations).

---

### S05-06 — Implement Config Fetch and Localization Setup

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-06                                                          |
| Type           | Technical Enabler                                               |
| Effort         | ~0.5 days                                                       |
| Dependencies   | S05-01 (project exists)                                         |

**Statement**

As the engineer, I want all UI strings externalized into a localization file and the config/scenarios endpoint fetched on app load, so that no component contains hardcoded copy and the scenario data is available before controls render.

**Why**

NFR-018 requires all copy to be externalized for future localization. CONTENT_GUIDELINES mandates specific language for result states, disclaimers, and error messages. Hardcoding these strings into components makes compliance unverifiable and future translation impossible. The config fetch is equally foundational — scenario data drives the ScenarioControl in Epic 06 and must be cached before the user reaches the result state.

**Scope Notes**

- Create `lib/i18n/en.ts` with the full `strings` object covering:
  - `emptyState`: heading, body, subtext.
  - `resultStates`: all 5 result state headings.
  - `loading`: geocoding and assessing messages.
  - `errors`: geocodingFailure, assessmentFailure, unexpected — each with heading and body.
  - `disclaimer`: full disclaimer text from CONTENT_GUIDELINES section 4.
  - `noResults`: heading and body (body accepts query parameter).
  - `search`: placeholder text, submit button label.
  - `candidateList`: heading (e.g., "Select a location").
- Create `lib/api/config.ts`: TanStack Query hook for `GET /v1/config/scenarios` with `staleTime: Infinity`. Query key: `['config', 'scenarios']`.
- Fire the config query on app load (in AppShell or a top-level provider).
- Export a typed `ConfigData` type matching the API response shape.

**Traceability**

- Requirements: NFR-018, FR-016
- Architecture: `docs/architecture/03a-frontend-architecture.md` sections 4.2, 11

**Implementation Notes**

- Use `as const` on the strings object for maximum type safety.
- The config query uses `staleTime: Infinity` because scenario data does not change during a user session. It is fetched once and never refetched.
- The body function for `noResults` and `loading.assessing` accept string parameters — implement as arrow functions returning strings.
- Do not fetch `GET /v1/config/methodology` here — that is deferred until the methodology panel is opened (Epic 06).

**Acceptance Criteria**

1. `lib/i18n/en.ts` exports a `strings` object containing all UI copy categories listed above.
2. No component in the codebase contains hardcoded English text (all copy reads from `strings`).
3. `lib/api/config.ts` exports a TanStack Query hook that calls `GET /v1/config/scenarios`.
4. The config query fires on app load and caches with `staleTime: Infinity`.
5. `ConfigData` type matches the expected API response shape (scenarios array with id, displayName, description, sortOrder, isDefault).
6. The `strings` object uses `as const` for literal type inference.

**Definition of Done**

- `en.ts` and `config.ts` committed.
- Grep of codebase confirms no hardcoded UI strings in components (excluding the strings file itself).

**Testing Approach**

- Vitest: config hook unit test with MSW mock for `GET /v1/config/scenarios` — verify data shape and cache behavior.
- Code review: verify no hardcoded strings in components.

**Evidence Required**

- Vitest test output for config hook.
- Grep result confirming no hardcoded UI strings in component files.

---

### S05-07 — Implement EmptyState, LoadingState, ErrorBanner

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-07                                                          |
| Type           | Feature                                                         |
| Effort         | ~0.5 days                                                       |
| Dependencies   | S05-02 (appStore), S05-06 (strings)                             |

**Statement**

As a user, I want to see clear feedback at every stage — an invitation to search when the app loads, a loading indicator during processing, and a helpful error message if something fails — so that the application never appears blank or broken.

**Why**

NFR-010 prohibits blank or broken UI states. Every phase of the AppPhase state machine that does not render a search result or candidate list must still render something meaningful. These three components cover the idle, loading, and error phases. Without them, the user sees an empty panel or no feedback, which damages trust and makes the application appear broken.

**Scope Notes**

- Create `app/components/shared/EmptyState.tsx`:
  - Rendered when `appPhase.phase === 'idle'`.
  - Heading and body from `strings.emptyState`.
  - `aria-live="polite"` on the container.
- Create `app/components/shared/LoadingState.tsx`:
  - Rendered when `appPhase.phase === 'geocoding'` or `appPhase.phase === 'assessing'`.
  - Copy from `strings.loading.geocoding` or `strings.loading.assessing(locationLabel)` depending on phase.
  - `aria-busy="true"` on the loading region.
  - Visual loading indicator (spinner or skeleton — keep simple).
  - Map remains interactive during loading (no overlay blocking map interaction).
- Create `app/components/shared/ErrorBanner.tsx`:
  - Rendered when `appPhase.phase === 'geocoding_error'` or `appPhase.phase === 'assessment_error'`.
  - Copy from `strings.errors.geocodingFailure` or `strings.errors.assessmentFailure` depending on phase.
  - `role="alert"` for immediate screen reader announcement.
  - Retry button: on click, re-dispatches the failed request (calls `appStore.startGeocoding()` or transitions back to `assessing`).
- Create no-results variant (can be part of EmptyState or a separate small component):
  - Rendered when `appPhase.phase === 'no_geocoding_results'`.
  - Copy from `strings.noResults`.
- Wire all four components into AppShell's conditional rendering based on `appPhase.phase`.

**Traceability**

- Requirements: FR-038, FR-039, FR-041, NFR-010, NFR-015
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 3 (EmptyState, LoadingState, ErrorBanner), section 5 (UI State Model)

**Implementation Notes**

- The `role="alert"` on ErrorBanner causes screen readers to announce the error immediately without the user needing to navigate to it. Use sparingly — only on actual error states.
- The retry button must re-trigger the original request. For geocoding errors, this means re-submitting the last query. Store the last query in appStore (or pass it as part of the error phase payload) so retry has access to it.
- LoadingState should not block map interaction — render it in the panel area, not as a full-screen overlay.

**Acceptance Criteria**

1. EmptyState renders when appPhase is `idle`, with correct heading and body from strings.
2. EmptyState container has `aria-live="polite"`.
3. LoadingState renders when appPhase is `geocoding`, showing geocoding loading text.
4. LoadingState renders when appPhase is `assessing`, showing assessment loading text with location label.
5. LoadingState region has `aria-busy="true"`.
6. Map remains interactive (pannable, zoomable) while LoadingState is visible.
7. ErrorBanner renders on `geocoding_error` with geocoding error copy and a retry button.
8. ErrorBanner renders on `assessment_error` with assessment error copy and a retry button.
9. ErrorBanner has `role="alert"`.
10. Retry button on ErrorBanner re-triggers the failed request and transitions back to the loading phase.
11. No-results state renders on `no_geocoding_results` with correct copy.
12. No appPhase results in a blank or empty panel area.

**Definition of Done**

- All four components committed and wired into AppShell.
- Unit tests pass for each component rendering in the correct phase.
- Manual verification that no phase produces a blank panel.

**Testing Approach**

- Vitest + RTL: for each conditional component, set appStore to the relevant phase, render AppShell (or the component directly), assert correct text content and ARIA attributes.
- Vitest + RTL: simulate retry button click on ErrorBanner, assert appStore phase transitions back to loading.
- Manual walkthrough: cycle through all appPhase values and confirm no blank states.

**Evidence Required**

- Vitest test output showing all conditional rendering tests passing.
- Manual walkthrough log confirming no blank phases.

---

### S05-08 — Frontend Smoke Tests and Performance Baseline

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ID             | S05-08                                                          |
| Type           | Quality Assurance                                               |
| Effort         | ~0.5 days                                                       |
| Dependencies   | S05-01 through S05-07 (all components exist)                    |

**Statement**

As the engineer, I want a Vitest + RTL test suite covering store transitions and component renders, an authored `@playwright/test` smoke test for the critical search flow, and a bundle size measurement, so that quality and performance baselines are established before Epic 06 builds on top. Additionally, `playwright-cli` should be available for ad-hoc visual verification during development.

**Why**

This epic produces the foundation that all subsequent frontend work builds on. Without a test suite, regressions in state transitions or component rendering will go undetected during Epic 06 development. Without a bundle size baseline, there is no way to detect performance regressions against NFR-001. Establishing these baselines now is cheap; detecting regressions later is expensive.

**Scope Notes**

- Configure Vitest with React Testing Library and jsdom environment.
- Write unit tests for:
  - `appStore`: all phase transitions (already started in S05-02 — consolidate and complete).
  - `mapStore`: setViewport, setSelectedLocation.
  - `uiStore`: open/close methodology panel.
- Write component render tests:
  - SearchBar: renders input and button; empty submit blocked; ARIA attributes present.
  - CandidateList: renders correct number of items; keyboard navigation works; selection updates stores.
  - EmptyState: renders correct text when phase is `idle`.
  - LoadingState: renders correct text for `geocoding` and `assessing` phases.
  - ErrorBanner: renders correct text and retry button for error phases.
- Configure `@playwright/test` (the authored test runner).
- Write an authored `@playwright/test` smoke test:
  - Load page.
  - Verify map canvas is present.
  - Type a query into SearchBar, submit.
  - Verify CandidateList appears (with MSW or API stub).
- Verify `playwright-cli` works against the local Docker Compose environment for ad-hoc exploration:
  ```bash
  npx playwright-cli goto http://localhost:3000
  npx playwright-cli screenshot homepage.png
  ```
- Measure and record bundle size:
  - Run `next build` and extract the route-level JS sizes from build output.
  - Assert initial JS (critical path, before lazy chunks) is under 300KB gzipped.
  - Record total JS budget (<800KB gzipped including lazy-loaded MapLibre + deck.gl).

**Traceability**

- Requirements: NFR-001, NFR-010, NFR-015
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 9, `docs/architecture/10-testing-strategy.md`

**Implementation Notes**

- Use MSW (Mock Service Worker) to stub API responses in both Vitest (for integration-level component tests) and `@playwright/test` (for authored smoke tests).
- The bundle size assertion should be a script or CI step that parses `next build` output — not a manual check. This becomes a regression gate in CI.
- `@playwright/test` needs a running `next dev` or `next start` server. Use `webServer` config in `playwright.config.ts` to start the dev server automatically. The `baseURL` should default to `http://localhost:3000` (local Docker Compose).
- `playwright-cli` (`npx playwright-cli`) is available for ad-hoc visual verification but does not replace the authored test. Use it to quickly check UI states, capture screenshots, or debug rendering issues during development.

**Acceptance Criteria**

1. Vitest runs with zero failures across all store and component tests.
2. appStore tests cover every valid phase transition and the `reset()` from every phase.
3. Each conditional component (EmptyState, LoadingState, ErrorBanner, CandidateList) has at least one render test verifying correct text and ARIA attributes.
4. SearchBar test verifies empty submit is blocked.
5. Authored `@playwright/test` smoke test loads the page, confirms map canvas element exists, types a query, submits, and verifies candidate list renders.
6. `next build` output shows initial route JS under 300KB gzipped.
7. Total JS (including lazy chunks) is under 800KB gzipped.
8. Bundle size measurement is recorded and committed (as a CI step or documented baseline).

**Definition of Done**

- All Vitest tests pass.
- Authored `@playwright/test` smoke test passes against local Docker Compose.
- Bundle size baseline recorded and committed.
- CI configuration updated to run Vitest, `@playwright/test` smoke test, and bundle size check on PR.

**Testing Approach**

- This story is itself the testing story. Evidence is the test results.

**Evidence Required**

- Vitest test run output (all pass).
- `@playwright/test` smoke test run output (pass).
- `next build` output showing bundle sizes.
- Documented bundle size baseline.

---

## 7  Technical Deliverables

| Deliverable                           | Format                                | Produced By |
| ------------------------------------- | ------------------------------------- | ----------- |
| Next.js project scaffold              | TypeScript + App Router               | S05-01      |
| Dockerfile (frontend)                 | Dockerfile                            | S05-01      |
| `.env.local.example`                  | Environment variable documentation    | S05-01      |
| Zustand stores (appStore, mapStore, uiStore) | TypeScript modules              | S05-02      |
| Shared TypeScript types               | `lib/types/index.ts`                  | S05-02      |
| MapSurface + LocationMarker           | React components                      | S05-03      |
| SearchBar                             | React component                       | S05-04      |
| TanStack Query geocoding hook         | TypeScript module                     | S05-04      |
| CandidateList                         | React component                       | S05-05      |
| UI strings file                       | `lib/i18n/en.ts`                      | S05-06      |
| TanStack Query config hook            | TypeScript module                     | S05-06      |
| EmptyState, LoadingState, ErrorBanner | React components                      | S05-07      |
| Vitest test suite                     | TypeScript test files                 | S05-08      |
| `@playwright/test` smoke test         | TypeScript test file                  | S05-08      |
| Bundle size baseline                  | Documented measurement                | S05-08      |

---

## 8  Data, API, and Infrastructure Impact

This epic consumes two API endpoints built in Epic 04:

| Endpoint                     | Method | Consumed By         | Notes                                  |
| ---------------------------- | ------ | ------------------- | -------------------------------------- |
| `/v1/geocode`                | POST   | SearchBar (S05-04)  | Geocoding query; returns candidates    |
| `/v1/config/scenarios`       | GET    | Config hook (S05-06)| Scenario list; cached for session      |

No database writes. No Blob Storage access. No infrastructure provisioning. The frontend container will be added to the existing Docker Compose configuration (Epic 02, S02-01) and the basic CI pipeline (Epic 02, S02-03). CI/CD deployment to Azure is deferred to Epic 08.

---

## 9  Security and Privacy

- **No secrets in client code (NFR-006).** The geocoding API key lives server-side in the API container. The basemap style URL is a public, domain-restricted key exposed via `NEXT_PUBLIC_BASEMAP_STYLE_URL` — acceptable per the security architecture.
- **No raw address persistence (BR-016).** SearchBar does not write query text to localStorage, sessionStorage, cookies, or any persistent medium. The URL state (if implemented per OQ-08) uses coordinates, not address strings.
- **CORS.** The frontend calls the API at `NEXT_PUBLIC_API_BASE_URL`. The API's CORS configuration (Epic 04) must allow the frontend's origin.

---

## 10  Observability

- React Error Boundary at AppShell level catches unhandled rendering exceptions and logs to console (analytics integration deferred to OQ-10).
- TanStack Query `onError` callbacks log API errors to console.
- No production analytics instrumentation in this epic.

---

## 11  Testing

| Story   | Testing Approach                                                                   |
| ------- | ---------------------------------------------------------------------------------- |
| S05-01  | Build verification (`next build`, Docker build), manual responsive layout check    |
| S05-02  | Vitest unit tests — all state transitions                                          |
| S05-03  | Vitest + RTL render test, manual map interaction verification                      |
| S05-04  | Vitest + RTL — SearchBar validation, geocoding hook with MSW mock                  |
| S05-05  | Vitest + RTL — rendering, keyboard navigation, selection; axe-core accessibility   |
| S05-06  | Vitest — config hook with MSW mock; code review for hardcoded strings              |
| S05-07  | Vitest + RTL — each component renders in correct phase with correct ARIA           |
| S05-08  | Vitest full suite, `@playwright/test` smoke test, `playwright-cli` verification, bundle size measurement |

---

## 12  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| MapLibre GL JS bundle size exceeds budget, pushing initial JS above 300KB gzipped | Medium | Medium | MapLibre is dynamically imported (deferred). Measure in S05-08 and split further if needed. The 300KB target is for the critical path before MapLibre loads. |
| Basemap provider decision (OQ-07) is not yet resolved, blocking MapSurface development | High | Low | Use a free OpenStreetMap raster style as a placeholder. The style URL is externalized via environment variable, so swapping providers is a config change. |
| Geocoding API (Epic 04) is not yet deployed when frontend development begins | Medium | Medium | Use MSW to mock all API responses during development. The TanStack Query hooks are tested against mocks regardless. |
| CandidateList keyboard navigation has cross-browser inconsistencies | Low | Medium | Test in Chrome, Firefox, and Safari. Use `aria-activedescendant` pattern which has broad support. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| Epic 04 delivers `POST /v1/geocode` and `GET /v1/config/scenarios` before this epic completes. | Frontend can be developed and tested entirely against mocks, but integration testing and the `@playwright/test` smoke test against a real local API are blocked. |
| MapLibre GL JS works with the selected basemap provider's style URL without additional configuration. | May require adapter configuration or a different tile source format. Low risk — MapLibre supports all common vector and raster tile formats. |
| The 300KB initial JS budget is achievable with Next.js 14 + TailwindCSS + Zustand + TanStack Query (before MapLibre lazy load). | If exceeded, investigate tree-shaking, dependency analysis, and further code splitting. |

---

## 13  Epic Acceptance Criteria

1. Next.js 14+ App Router application loads at `localhost:3000` with the responsive split-pane layout.
2. MapLibre map renders centered on Europe at `[10, 54]`, zoom 4, with pan/zoom and attribution control.
3. SearchBar accepts a query, validates input (blocks empty, enforces 200-char max), and triggers geocoding.
4. CandidateList appears with up to 5 candidates showing label + displayContext; keyboard navigable.
5. Selecting a candidate sets the location marker on the map and transitions to the assessing phase.
6. EmptyState, LoadingState, and ErrorBanner render in their respective phases with correct copy and ARIA attributes.
7. No appPhase produces a blank or broken UI state.
8. All UI strings are sourced from `lib/i18n/en.ts` — no hardcoded copy in components.
9. Config scenarios are fetched on app load and cached for the session.
10. Vitest test suite passes with coverage of all store transitions and component renders.
11. `@playwright/test` smoke test passes against local Docker Compose (load, search, candidate list appears).
12. Initial JS bundle (critical path) is under 300KB gzipped.

---

## 14  Definition of Done

- All 8 user stories completed with evidence.
- `next build` and Docker build succeed in CI.
- Vitest and `@playwright/test` suites pass against local Docker Compose.
- Bundle size baseline recorded and within budget.
- No blank or broken UI states across any appPhase.
- All UI copy sourced from the localization file.
- Responsive layout verified at desktop, tablet, and mobile widths.
- Code committed and passing CI pipeline.

---

## 15  Demo / Evidence

| Evidence                                              | Location (expected)                              |
| ----------------------------------------------------- | ------------------------------------------------ |
| Running application at localhost:3000                  | Docker Compose or `next start`                   |
| Map rendering at Europe view                          | Screenshot or screen recording                   |
| Search flow: query -> candidates -> selection -> marker | Screen recording, `@playwright/test` trace, or `playwright-cli` screenshots |
| EmptyState, LoadingState, ErrorBanner renders         | Screenshots per phase                            |
| Responsive layout at 3 breakpoints                    | Screenshots at 1280px, 900px, 375px widths       |
| Vitest test results                                   | CI output or terminal screenshot                 |
| `@playwright/test` smoke test results                 | CI output or Playwright HTML report              |
| Bundle size baseline                                  | `next build` output showing route-level JS sizes |
