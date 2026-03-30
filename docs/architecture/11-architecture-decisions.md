# 11 — Architecture Decisions (ADRs)

> **Status:** Confirmed (decisions made) | Proposed Architecture (implementation detail)
> **Format:** Lightweight ADR — Context / Decision / Consequences

---

## ADR-001: Frontend Framework — Next.js App Router

**Status:** Confirmed

**Context:**
The frontend requires server-side rendering for initial HTML delivery (NFR-001: 4s shell), TypeScript support, a strong component model, and ecosystem compatibility with MapLibre GL JS and TanStack Query. The product is a public read-only application with no authentication.

**Decision:**
Use **Next.js 14+ with App Router** as the frontend framework.

**Consequences:**
- `+` Server Components deliver the HTML shell and critical CSS without JavaScript loading
- `+` MapLibre (large bundle, ~500 KB) deferred via `dynamic(() => import(...), { ssr: false })` — does not block initial render
- `+` TanStack Query v5 caches config data (scenarios, methodology) session-wide
- `+` Strong TypeScript support; route-based code splitting built-in
- `-` App Router is newer; some patterns (especially for client-side-only components with `useSearchParams`) require `Suspense` boundaries
- `-` More complex than a pure SPA (Vite/React) — justified by NFR-001 shell loading requirement

---

## ADR-002: State Management — Zustand (not Redux / Context)

**Status:** Confirmed

**Context:**
The application has a clear multi-phase UI state machine (AppPhase) and a map state (selected location, viewport) that must be accessible from multiple components without prop drilling. The state is client-side only.

**Decision:**
Use **Zustand** for client-side global state, split into `useAppStore` (AppPhase state machine) and `useMapStore` (map location, viewport).

**Consequences:**
- `+` Minimal boilerplate; no actions/reducers/selectors ceremony
- `+` Direct subscription to specific store slices prevents unnecessary re-renders
- `+` Works seamlessly with Next.js App Router Client Components
- `+` Easy to test — stores are plain JavaScript modules
- `-` Less explicit than Redux for large teams — acceptable for a single-engineer project
- **Not chosen:** React Context — too prone to over-rendering; Redux Toolkit — overkill for this scope

---

## ADR-003: Server-State — TanStack Query v5

**Status:** Confirmed

**Context:**
The application makes three types of server requests: config fetch (on load, session-cached), geocoding (per-search), and assessment (per-location+scenario+horizon). Each has different caching semantics.

**Decision:**
Use **TanStack Query v5** for all data fetching with purpose-specific `staleTime` configuration.

**Caching strategy:**
| Query | staleTime | Rationale |
|---|---|---|
| `/v1/config/scenarios` | `Infinity` | Scenarios don't change during a session |
| `/v1/config/methodology` | `Infinity` | Static methodology content |
| `/v1/assess` | 60 seconds | Cache recent assessments for back-navigation; stale after 60s |
| `/v1/geocode` | 0 (no cache) | Search queries are ephemeral |

**Consequences:**
- `+` Scenario change from SSP2 → SSP5 → SSP2 reuses cached assessment result (NFR-004: 1.5s target)
- `+` Deduplicates simultaneous requests (e.g., double-click)
- `+` Integrates with AbortController for request cancellation (FR-040)
- `-` Additional dependency (~12 KB gzipped)

---

## ADR-004: Backend Framework — ASP.NET Core Minimal API

**Status:** Confirmed

**Context:**
The backend exposes 5 endpoints (geocode, assess, config/scenarios, config/methodology, health). The domain logic is pure C# with no web framework coupling required.

**Decision:**
Use **ASP.NET Core .NET 8 Minimal API** (not MVC controllers).

**Consequences:**
- `+` Minimal API is lightweight and explicit — no convention magic
- `+` Clean separation between endpoint registration and business logic
- `+` Excellent performance characteristics (ranked top tier in TechEmpower benchmarks)
- `+` Built-in FluentValidation endpoint filters
- `+` Native JSON serialization via `System.Text.Json`
- `-` Less scaffolding/generators than MVC — requires more manual setup (acceptable trade-off)

---

## ADR-005: Geography Validation — PostGIS ST_Within (not client-side)

**Status:** Confirmed

**Context:**
FR-009–FR-012 require that geography validation (Is it in Europe? Is it in the coastal zone?) be server-side and authoritative. A client-side JavaScript polygon check would be a UX convenience only, not a correctness guarantee.

**Decision:**
All geography validation is performed server-side via **PostGIS `ST_Within` queries** against geometries stored in `geography_boundaries`.

**Consequences:**
- `+` Single source of truth for geography rules — impossible to bypass via direct API calls
- `+` Geometry updates (e.g., coastal zone boundary refinement) require only a DB update, not a code or client deploy
- `+` GIST-indexed geometry queries: ~20ms per check (acceptable within 3.5s budget)
- `-` Two additional DB round-trips per assessment request
- **Tradeoff:** Client-side early return (hiding the assess button for non-European locations) is a UX enhancement only, not a security or correctness control

---

## ADR-006: Tile Serving — TiTiler (off-the-shelf, not custom)

**Status:** Confirmed

**Context:**
The system needs to serve XYZ map tiles from Cloud-Optimized GeoTIFF files stored in Azure Blob Storage. Building a custom tile server is significant engineering effort.

**Decision:**
Use **TiTiler** (open-source FastAPI tile server from Development Seed) as an off-the-shelf solution. Configure it via environment variables only — no application-layer customization.

**Consequences:**
- `+` Zero custom code for tile serving
- `+` Native COG support via GDAL; HTTP range requests minimise data transfer
- `+` `/point/{lng},{lat}` endpoint enables pixel value extraction (used by `ExposureEvaluator` Option A)
- `+` Well-maintained by active community; used in production at multiple climate data organisations
- `-` TiTiler is a Python/FastAPI application; the team's primary expertise is TypeScript/C# — requires basic Python ops knowledge
- `-` GDAL VSIAZ driver requires correct environment configuration for Azure Blob access
- `-` Assessment point queries (`/point`) go through TiTiler — adds a network hop compared to direct raster query
- **Tradeoff noted:** Option B (direct GDAL in API) eliminates the TiTiler dependency for point queries but adds a raster processing library to the .NET API container. Deferred to Phase 0 spike (OQ-05).

---

## ADR-007: COG Format for Geospatial Layers

**Status:** Confirmed (NFR-020)

**Context:**
Geospatial layers must be served as map tiles by TiTiler. The data is static (computed offline). Tile serving performance depends on whether data can be read with minimal I/O.

**Decision:**
All geospatial layers are stored as **Cloud-Optimized GeoTIFF (COG)** with binary pixel values (0 = no exposure, 1 = exposure, NoData = outside analysis zone).

**Consequences:**
- `+` TiTiler reads COGs efficiently via HTTP range requests — only the tile-relevant bytes are fetched
- `+` Standard format; tooling support from GDAL, rasterio, rio-cogeo
- `+` Spatial indexing built into COG structure (internal overviews)
- `-` Requires offline pipeline step to convert raw GeoTIFF → COG (see [16-geospatial-data-pipeline.md](16-geospatial-data-pipeline.md))
- `-` Binary pixel format loses intermediate exposure values — acceptable because the result states (Detected / Not Detected) are binary by definition (BR-010)

---

## ADR-008: Database — PostgreSQL with PostGIS

**Status:** Confirmed

**Context:**
The system needs to store scenario/methodology configuration, layer metadata, and perform spatial queries (ST_Within). Options considered: SQLite (too lightweight for spatial queries), MongoDB (no PostGIS equivalent), PostgreSQL+PostGIS (standard for GIS applications).

**Decision:**
Use **Azure Database for PostgreSQL Flexible Server** with **PostGIS extension**.

**Consequences:**
- `+` PostGIS is the industry standard for server-side spatial queries in production systems
- `+` `ST_Within` with GIST index provides ~20ms query performance on polygon containment checks
- `+` Flexible Server supports burstable SKU (cost-effective for low-traffic portfolio)
- `+` Managed service: automatic backups, patching, HA optionality
- `-` Requires PostGIS extension activation at provisioning time (`CREATE EXTENSION postgis`)
- `-` PostgreSQL Flexible Server doesn't support scale-to-zero (minimum ~$15/month regardless of traffic) — accepted cost

---

## ADR-009: API Authentication Model — Anonymous Public Access

**Status:** Confirmed (BR-001)

**Context:**
SeaRise Europe is a public educational tool. The PRD explicitly states no user accounts, no authentication, no rate limiting at MVP. All data is public climate science.

**Decision:**
**No authentication** on any API endpoint. All endpoints are publicly accessible.

**Consequences:**
- `+` Zero authentication infrastructure complexity (no OAuth, no JWT, no session management)
- `+` Maximises accessibility for the target audiences (P-01 Marina, P-02 Tobias, P-03 Yuki)
- `-` No rate limiting means the geocoding provider API key is indirectly exposed to abuse (mitigated by server-side key storage + provider quota limits)
- `-` Cannot distinguish individual users for analytics purposes (mitigated: METRICS_PLAN.md uses session-level anonymous events, not user-level)
- **Revisit:** If OQ-10 (analytics) requires per-user event attribution, this decision may need revision for Phase 2

---

## ADR-010: Result State Taxonomy — 5 Fixed States (not HTTP error codes)

**Status:** Confirmed (BR-010)

**Context:**
Geography validation produces semantically meaningful results (InEurope, OutOfScope, UnsupportedGeography) that are not errors — they are valid outcomes of a correct assessment. Using HTTP 4xx status codes for these would conflate "user input error" with "valid result the user should understand."

**Decision:**
All 5 result states (`ModeledExposureDetected`, `NoModeledExposureDetected`, `DataUnavailable`, `OutOfScope`, `UnsupportedGeography`) are returned as HTTP **200 OK** with a `resultState` string enum.

**Consequences:**
- `+` Frontend logic is uniform: always process a 200 response; the `resultState` determines display
- `+` Aligns with the product intent: "OutOfScope" is informative, not an error
- `+` TanStack Query cache key includes `(lat, lng, scenarioId, horizonYear)` — all result states are cached equally
- `-` HTTP 200 for "outside supported area" is non-standard; developers integrating the API must read the response body, not just the status code
- **Note:** HTTP errors (400, 500) are reserved for input validation failures and server errors — clearly distinguishable from result states

---

## ADR-011: Methodology Versioning — Immutable History

**Status:** Confirmed (NFR-021)

**Context:**
The exposure methodology may change (new data sources, revised thresholds). Users who saw a previous result should be able to understand what methodology produced it. Old methodology versions must not be deleted.

**Decision:**
Every `AssessmentResult` carries a `methodologyVersion` string. Past `methodology_versions` rows and their associated `layers` are **never deleted**. A single `is_active` flag determines which version serves current requests.

**Consequences:**
- `+` Full auditability: any past result can be reconstructed by knowing the version string
- `+` Safe rollback: reactivating a previous version requires only a database flag change
- `+` No code changes required to activate a new methodology version
- `-` Storage grows over time (accepted: COG files are cheap; methodology versions change rarely)
- **Invariant enforced by:** atomic `BEGIN/UPDATE is_active/COMMIT` SQL transaction (never two active versions simultaneously)

---

## ADR-012: Stale Request Handling — AbortController + Sequence Number

**Status:** Confirmed (FR-040)

**Context:**
Users may rapidly change scenario/horizon controls, triggering multiple concurrent assess requests. Without cancellation, a slow earlier response could overwrite a newer result.

**Decision:**
Each new assess request (a) calls `abortController.abort()` on the previous request, and (b) increments a `requestSeqRef`. The response handler applies the result only if the sequence number matches the current `requestSeqRef.current`.

**Consequences:**
- `+` Prevents stale responses from overwriting current results (FR-040)
- `+` Reduces server load from abandoned requests
- `+` AbortController is a native browser API — no additional dependency
- `-` Two-layer defence is slightly redundant; single `AbortController` is usually sufficient — the sequence number guard is cheap insurance
- **Note:** TanStack Query manages AbortController automatically when `queryKey` changes — the sequence number guard is belt-and-suspenders for edge cases where two requests have identical query keys but different in-flight timing

---

## ADR-013: No CDN for Map Tiles at MVP

**Status:** Proposed Architecture (Tradeoff)

**Context:**
Map tiles served by TiTiler are static for a given methodology version. A CDN would dramatically improve tile loading performance globally. However, CDN configuration adds operational complexity and cost.

**Decision:**
For MVP, **no CDN** in front of TiTiler. Tiles are served directly from the Azure Container Apps endpoint.

**Consequences:**
- `-` Global latency for tile requests (200–400ms from distant regions vs 50–100ms with CDN)
- `+` Zero CDN configuration complexity
- `+` Cost reduction at low traffic volumes
- `+` Acceptable for portfolio demo: primary audience is likely in Western Europe (close to West Europe Azure region)
- **Revisit in Phase 3:** Add Azure CDN or Cloudflare in front of TiTiler if tile load time becomes a performance concern

---

## ADR-014: Frontend URL State — Shallow Routing for Assessment Parameters

**Status:** Proposed Architecture

**Context:**
The user's scenario, horizon, and possibly location should be shareable (e.g., to send a specific assessment result to a colleague). URL state enables this and also supports browser back/forward navigation.

**Decision:**
Assessment parameters are reflected in the URL as query parameters via Next.js `useSearchParams` + `useRouter().push()`. URL is updated on: location selection, scenario change, horizon change. The app hydrates from URL on load.

**URL format:**
```
/?lat=52.37&lng=4.90&scenario=ssp2-45&horizon=2050
```

**Consequences:**
- `+` Shareable URLs for specific assessment results (portfolio demonstration value)
- `+` Browser back button works as expected
- `-` URL state and Zustand store state must be kept in sync — adds complexity
- `-` SSR + useSearchParams requires Suspense boundary in Next.js App Router
- **Tradeoff:** If URL state proves complex to implement correctly, fall back to in-memory state only for MVP and add URL persistence in Phase 2
