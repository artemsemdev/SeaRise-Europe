# 04 — Runtime Sequences

> **Status:** Proposed Architecture
> Participants: **Browser** (frontend), **API** (ASP.NET Core), **Geocoder** (external geocoding provider), **Postgres** (PostgreSQL+PostGIS), **Tiler** (TiTiler), **Blob** (Azure Blob Storage)

---

## Sequence 1: Application Load

What happens when a user first opens the application.

```mermaid
sequenceDiagram
    participant B as Browser
    participant FE as Frontend (Next.js)
    participant API as API

    B->>FE: GET /
    FE-->>B: HTML shell + critical CSS (Server Component render)
    B->>FE: GET /_next/static/... (JS chunks)
    FE-->>B: JS bundles (MapLibre lazy — deferred)
    Note over B: AppShell mounts, MapLibre initialized (dynamic import)
    B->>API: GET /v1/config/scenarios
    API-->>B: scenarios + horizons + defaults
    Note over B: ScenarioControl and HorizonControl populated
    Note over B: EmptyState displayed, map renders Europe view
```

**Notes:**
- MapLibre is loaded via `dynamic(() => import('./MapSurface'), { ssr: false })` — defers the large bundle until after the page shell is interactive (NFR-001)
- `/v1/config/scenarios` is cached indefinitely for the session (TanStack Query `staleTime: Infinity`)
- No geocoding or assessment occurs on load

---

## Sequence 2: Happy Path — Valid Coastal Location

Full flow from search to result display.

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant GC as Geocoder
    participant PG as Postgres
    participant Tiler as Tiler
    participant Blob as Blob

    B->>API: POST /v1/geocode {query: "Amsterdam"}
    API->>GC: geocode("Amsterdam")
    GC-->>API: [{label, lat, lng, country, rank}, ...]
    API-->>B: {requestId, candidates: [...]} (up to 5, BR-007)
    Note over B: CandidateList shown (or auto-select if 1 result)
    B->>B: User selects candidate
    Note over B: appPhase → assessing, marker placed

    B->>API: POST /v1/assess {lat, lng, scenarioId, horizonYear}
    API->>PG: ST_Within(point, europe_boundary)
    PG-->>API: true
    API->>PG: ST_Within(point, coastal_analysis_zone)
    PG-->>API: true
    API->>PG: SELECT layer WHERE scenario+horizon+active_version
    PG-->>API: ExposureLayer {blobPath, legendSpec}
    API->>Tiler: GET /point/{lng},{lat}?url={blobPath}
    Tiler->>Blob: HTTP range request (GDAL VSIAZ)
    Blob-->>Tiler: COG byte range
    Tiler-->>API: {value: 1}
    Note over API: ResultStateDeterminator → ModeledExposureDetected
    API-->>B: {resultState: "ModeledExposureDetected", methodologyVersion, layerTileUrlTemplate, legendSpec, ...}

    Note over B: appPhase → result
    B->>Tiler: XYZ tile requests using layerTileUrlTemplate
    Tiler->>Blob: COG range requests
    Blob-->>Tiler: tile data
    Tiler-->>B: tile PNGs
    Note over B: ExposureLayer visible, ResultPanel shown, Legend updated (FR-031)
```

**Key FR compliance:** FR-020 (result includes location + scenario + horizon + state), FR-021 (overlay shown for ModeledExposureDetected), FR-029 (legend updated), FR-031 (map and summary synchronized), FR-035 (methodologyVersion in response).

---

## Sequence 3: Ambiguous Geocoding — Multiple Candidates

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant GC as Geocoder

    B->>API: POST /v1/geocode {query: "Valencia"}
    API->>GC: geocode("Valencia")
    GC-->>API: [Valencia Spain, Valencia Venezuela, ...]
    API-->>B: {candidates: [Valencia, North Holland (rank 1), Valencia, Venezuela (rank 2), ...]}
    Note over B: CandidateList shown with up to 5 items
    Note over B: Each candidate shows label + displayContext (BR-009)
    B->>B: User selects "Valencia, Spain"
    Note over B: CandidateList dismissed, assessment starts (→ Sequence 2 step 6+)
```

**Key BR compliance:** BR-006 (provider rank preserved), BR-007 (max 5 candidates), BR-009 (enough context to distinguish).

---

## Sequence 4: Map Refinement (FR-007, FR-008)

User already has a result; refines location by clicking map.

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API

    Note over B: Result displayed for location A
    B->>B: User clicks map at location B
    Note over B: appPhase → result_updating (old result still visible)
    Note over B: Previous abortController.abort() called (FR-040)
    B->>API: POST /v1/assess {lat: B.lat, lng: B.lng, scenarioId, horizonYear}
    API-->>B: new AssessmentResult
    Note over B: Marker moved to B, result panel + overlay updated
    Note over B: appPhase → result (new result)
```

**Notes:**
- The old result remains visible during loading (prevents blank state — PRD §10.3)
- The map click handler only fires when `selectedLocation` is already set; first location selection comes via CandidateList

---

## Sequence 5: Scenario Change (FR-017, FR-031)

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant PG as Postgres
    participant Tiler as Tiler

    Note over B: Result shown: SSP2-4.5, 2050 → ModeledExposureDetected
    B->>B: User selects SSP5-8.5 from ScenarioControl
    Note over B: Previous abortController.abort() (FR-040)
    Note over B: appPhase → result_updating
    B->>API: POST /v1/assess {lat, lng, scenarioId: "ssp5-85", horizonYear: 2050}
    API->>PG: (geography already known — Assumption: re-validate each request)
    API->>PG: SELECT layer WHERE scenarioId="ssp5-85" AND horizonYear=2050
    PG-->>API: ExposureLayer (different blobPath)
    API->>Tiler: GET /point/{lng},{lat}?url={new blobPath}
    Tiler-->>API: {value: 1}
    API-->>B: {resultState, methodologyVersion, layerTileUrlTemplate (new URL), legendSpec}
    Note over B: ResultPanel, ExposureLayer URL, Legend all update atomically (FR-031)
```

**Note on cached results:** If the user previously viewed SSP5-8.5 / 2050 for this location, TanStack Query returns the cached result instantly (NFR-004, staleTime 60s). No API call occurs.

---

## Sequence 6: Rapid Control Changes — Stale Response Handling (FR-040)

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API

    Note over B: Result shown
    B->>API: POST /v1/assess (request A: horizon 2030)
    Note over B: requestSeq = 1
    B->>B: User changes horizon to 2050 immediately
    B->>B: abort() request A
    B->>API: POST /v1/assess (request B: horizon 2050)
    Note over B: requestSeq = 2
    B->>B: User changes scenario immediately
    B->>B: abort() request B
    B->>API: POST /v1/assess (request C: new scenario, horizon 2050)
    Note over B: requestSeq = 3

    Note over API: Request A returns (ignored — already aborted)
    Note over API: Request B returns (ignored — already aborted)
    API-->>B: Response C
    Note over B: seq === requestSeqRef.current (3) → apply result C
    Note over B: Only request C result rendered
```

**How it works:** AbortController cancels HTTP requests. The requestSeq counter guards against race conditions where two responses arrive nearly simultaneously. Only the response matching the current sequence number is applied to the UI.

---

## Sequence 7: Out of Scope — Inland European Location

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant PG as Postgres

    B->>API: POST /v1/assess {lat: 50.07, lng: 14.43, ...}  %% Prague coordinates
    API->>PG: ST_Within(point, europe_boundary)
    PG-->>API: true  (Prague is in Europe)
    API->>PG: ST_Within(point, coastal_analysis_zone)
    PG-->>API: false  (Prague is inland)
    Note over API: ResultStateDeterminator → OutOfScope
    API-->>B: {resultState: "OutOfScope", methodologyVersion, scenario, horizon}
    Note over B: ResultPanel shows "Outside MVP Coverage Area"
    Note over B: No exposure overlay, no legend for coverage layer (FR-022 does not apply)
```

**Key rule:** `OutOfScope` is a 200 OK response — it is a valid result state, not an error (BR-010). No assessment is run for inland locations (FR-012, FR-013).

---

## Sequence 8: Unsupported Geography

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant PG as Postgres

    B->>API: POST /v1/assess {lat: 40.71, lng: -74.00, ...}  %% New York
    API->>PG: ST_Within(point, europe_boundary)
    PG-->>API: false
    Note over API: Early exit — no further queries needed
    API-->>B: {resultState: "UnsupportedGeography", methodologyVersion, scenario, horizon}
    Note over B: ResultPanel shows "Location Outside Supported Area"
```

**Note:** Geography validation is always server-side (FR-009). Even if a geocoding provider theoretically filters to European results, the API must always validate — the client can call `/v1/assess` with any coordinates.

---

## Sequence 9: Data Unavailable (BR-014)

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant PG as Postgres

    B->>API: POST /v1/assess {lat, lng, scenarioId: "ssp1-26", horizonYear: 2030}
    API->>PG: ST_Within(point, europe_boundary) → true
    API->>PG: ST_Within(point, coastal_zone) → true
    API->>PG: SELECT layer WHERE scenarioId="ssp1-26" AND horizonYear=2030 AND layer_valid=true
    PG-->>API: (no rows — layer not yet generated for this combination)
    Note over API: ResultStateDeterminator → DataUnavailable
    API-->>B: {resultState: "DataUnavailable", methodologyVersion, scenario, horizon}
    Note over B: "Data Unavailable" state — guidance to try different scenario/horizon
    Note over B: No substitution of another combination (BR-014)
```

---

## Sequence 10: Recoverable Request Failure (FR-039)

**10A — Geocoding failure:**

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API
    participant GC as Geocoder

    B->>API: POST /v1/geocode {query: "Lisbon"}
    API->>GC: geocode("Lisbon")
    GC-->>API: 503 Service Unavailable (provider down)
    API-->>B: 500 {error: {code: "GEOCODING_PROVIDER_ERROR"}}
    Note over B: appPhase → geocoding_error
    Note over B: ErrorBanner: "Search temporarily unavailable" + Retry button
    B->>B: User clicks Retry
    B->>API: POST /v1/geocode {query: "Lisbon"}  (same request repeated)
```

**10B — Assessment failure:**

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API

    B->>API: POST /v1/assess {lat, lng, scenarioId, horizonYear}
    API-->>B: 500 {error: {code: "INTERNAL_ERROR"}}
    Note over B: appPhase → assessment_error
    Note over B: ErrorBanner: "Result temporarily unavailable" + Retry
    B->>B: User clicks Retry
    B->>API: POST /v1/assess (same params)
```

---

## Sequence 11: Methodology Panel Access (FR-032, FR-033)

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API

    Note over B: Result displayed
    B->>B: User clicks "How to interpret this result" (MethodologyEntryPoint)
    Note over B: Check TanStack Query cache for ['config', 'methodology']
    alt Cache miss (first open)
        B->>API: GET /v1/config/methodology
        API-->>B: {methodologyVersion, seaLevelSource, elevationSource, whatItDoes, ...}
        Note over B: Cache stored for session
    end
    Note over B: MethodologyPanel opens (dynamic import completes)
    Note over B: Focus moves to panel heading (accessibility)
    B->>B: User closes panel (Escape or close button)
    Note over B: Focus returns to MethodologyEntryPoint button
```

---

## Sequence 12: Reset (FR-041)

```mermaid
sequenceDiagram
    participant B as Browser

    Note over B: Result displayed
    B->>B: User clicks Reset button
    Note over B: appStore.reset() called
    Note over B: appPhase → idle
    Note over B: mapStore.setSelectedLocation(null)
    Note over B: Marker removed from map
    Note over B: ExposureLayer hidden (visible: false)
    Note over B: Legend hidden
    Note over B: ResultPanel hidden
    Note over B: EmptyState shown
    Note over B: TanStack Query assess cache cleared for previous key
    Note over B: Map viewport resets to Europe default (optional — mark as to-decide)
```

**Note:** The TanStack Query cache for config (scenarios, methodology) is NOT cleared on reset — those are session-level caches that survive resets. Only the specific assessment result for the current location is cleared.
