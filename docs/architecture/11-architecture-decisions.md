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
- **Tradeoff noted:** Option B (direct GDAL in API) eliminates the TiTiler dependency for point queries but adds a raster processing library to the .NET API container. Binary methodology confirmed (ADR-015); Option A validated as sufficient.

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

---

## ADR-015: Exposure Methodology — Binary (v1.0)

**Status:** Approved (S01-04, OQ-05)

**Context:**
The exposure methodology determines how raw sea-level rise projection data is translated into user-facing results. It affects COG pixel value semantics, the `ExposureEvaluator` component logic, the `ResultState` domain model, and the methodology panel displayed to users. The methodology must be locked before pipeline code is written.

**Decision:**
Adopt a **binary** exposure methodology for v1.0. A grid cell is classified as exposed (`1`) when projected mean sea-level rise >= terrain elevation within the coastal analysis zone. No separate runtime threshold is applied. Exposure is precomputed offline and published as binary COGs.

Pixel semantics:
- `1` = modeled exposure detected (SLR >= DEM within coastal analysis zone)
- `0` = no modeled exposure (inside coastal analysis zone, condition not met)
- `NoData` = outside coastal analysis zone or missing source data

**Consequences:**
- `+` Simplest pipeline logic — direct comparison, no threshold tuning
- `+` TiTiler `/point` evaluation returns 0 or 1 — no runtime interpretation needed
- `+` Reproducible: same inputs always produce the same binary output
- `+` Aligns with existing architecture across COG storage, API contracts, and result-state determination
- `-` No graduated risk scale — future enhancement via `v1.1` or `v2.0`
- `-` Static inundation model may produce inland false positives where water cannot physically reach
- **Safeguard:** If Phase 0 validation reveals obvious false positives, promote a `v1.1` methodology with a coastal-connectivity screen while keeping binary COG output

**Full specification:** [`docs/delivery/artifacts/methodology-spec.md`](../delivery/artifacts/methodology-spec.md)

---

## ADR-016: MVP Scenario Set — Three AR6 Scenarios

**Status:** Approved (S01-01, OQ-02)

**Context:**
The scenario set is the primary dimension in the data model. Scenario IDs appear in database rows, blob storage paths (`layers/v1.0/{scenarioId}/{year}.tif`), API response payloads, and frontend dropdown controls. Changing them after implementation has begun triggers rework across every layer. The IPCC AR6 core set contains five illustrative SSP scenarios, but a consumer-facing MVP does not benefit from showing all five.

**Decision:**
Use exactly three scenarios:

| id | display_name | description | sort_order |
|---|---|---|---:|
| `ssp1-26` | Lower emissions (SSP1-2.6) | Lower-emissions AR6 pathway used as the lower-bound scenario in MVP. | 1 |
| `ssp2-45` | Intermediate emissions (SSP2-4.5) | Mid-range AR6 pathway used as the default reference scenario in MVP. | 2 |
| `ssp5-85` | Higher emissions (SSP5-8.5) | Higher-emissions AR6 pathway used as the upper-bound scenario in MVP. | 3 |

**Consequences:**
- `+` Three evenly spaced scenarios give a clear lower / middle / upper range
- `+` Manageable UI — three options in a selector control without overloading users
- `+` Covers the scientifically meaningful range from ambitious mitigation to high emissions
- `-` Omits SSP1-1.9 (too close to SSP1-2.6 for a three-option control) and SSP3-7.0 (limited incremental value above SSP5-8.5)
- **Wording rule:** Do not use IPCC storyline labels such as "fossil-fuelled development" in primary UI labels. Use emissions-framing only ("Lower emissions", "Intermediate emissions", "Higher emissions").
- **Stability rule:** The three `id` values above are stable keys across the database, API contract, and blob layout. They must not change after layers are generated.

---

## ADR-017: Default Scenario and Time Horizon

**Status:** Approved (S01-02, OQ-03)

**Context:**
The application must render a meaningful initial state on first load without requiring user interaction. The config API endpoint returns defaults that the frontend uses to populate controls and trigger the first exposure query. Without confirmed defaults, the config API contract cannot be finalized.

**Decision:**
- Default scenario: **`ssp2-45`** (Intermediate emissions)
- Default time horizon: **`2050`**

**Rationale:**
- `ssp2-45` is the least opinionated default — it neither front-loads the most alarming scenario nor minimizes the signal.
- `2050` is the strongest MVP default horizon because `2030` risks under-showing differences, `2100` is too distant for a first interaction, and `2050` is close enough to feel relevant while revealing meaningful change.

**Consequences:**
- `+` Middle-of-the-road first impression — neutral starting point for exploration
- `+` Deterministic initial UI state — no guesswork in frontend implementation
- `+` `is_default = true` on exactly one scenario and one horizon — simple config query
- `-` Any default carries implicit editorial weight — documented and accepted

**Implementation:**
- Set `is_default = true` only on `ssp2-45` in `scenarios` table
- Set `is_default = true` only on `2050` in `horizons` table

---

## ADR-018: Coastal Analysis Zone — Copernicus Coastal Zones 2018

**Status:** Approved (S01-03, OQ-04)

**Context:**
The application must determine whether a queried location is within the coastal analysis zone (eligible for exposure assessment) or inland (returns "OutOfScope"). This boundary is a core data dependency for the `CoastalZoneValidator` component and the `geography_boundaries` table. Options considered: Natural Earth 10m coastline buffered to N km, EEA coastal zone shapefile, or Copernicus Coastal Zones 2018.

**Decision:**
Define `coastal_analysis_zone` from the **Copernicus Land Monitoring Service Coastal Zones 2018** dataset:

1. Download the vector Coastal Zones dataset from Copernicus Land Monitoring Service.
2. Dissolve all coastal-land polygons into a single multipolygon geometry.
3. Clean topology in a projected CRS (EPSG:3035 for Europe).
4. Reproject to EPSG:4326.
5. Clip to the `europe` support geometry before seeding PostGIS.

**Source:**
- Dataset: Copernicus Land Monitoring Service — Coastal Zones 2018
- URL: https://land.copernicus.eu/en/products/coastal-zones
- License: Copernicus Land Monitoring Service license (free, open, attribution required)
- Inland extent: ~10 km (defined by the dataset, not an arbitrary buffer)

**Consequences:**
- `+` Official Europe-wide coastal product — more defensible than an arbitrary engineering heuristic
- `+` Reproducible: another engineer can rebuild the same geometry from a named source dataset
- `+` 10 km inland extent is conservative and easy to explain to users
- `-` Some estuarine or lagoon cases beyond the 10 km inland extent may remain out of scope for MVP
- `-` This is a product-scope boundary, not a hydrodynamic truth boundary — documented explicitly

**Validation set (10 coordinates — must all pass before seeding):**

| Location | Coordinates (approx.) | Expected | Rationale |
|---|---|---|---|
| Amsterdam | 52.37, 4.90 | In coastal zone | Major coastal city |
| Barcelona | 41.39, 2.17 | In coastal zone | Mediterranean coast |
| Copenhagen | 55.68, 12.57 | In coastal zone | Baltic coast |
| Lisbon | 38.72, -9.14 | In coastal zone | Atlantic coast |
| Venice | 45.44, 12.34 | In coastal zone | Adriatic lagoon |
| Prague | 50.08, 14.43 | Out of scope | Inland, ~300 km from coast |
| Zurich | 47.38, 8.54 | Out of scope | Inland, ~200 km from coast |
| Vienna | 48.21, 16.37 | Out of scope | Inland, ~300 km from coast |
| Munich | 48.14, 11.58 | Out of scope | Inland, ~250 km from coast |
| Bratislava | 48.15, 17.11 | Out of scope | Inland, ~300 km from coast |

**Geometry file:** `data/geometry/coastal_analysis_zone.geojson` (produced during pipeline bootstrap, Epic 03)

---

## ADR-019: Production Geocoding Provider — Azure Maps Search

**Status:** Approved (S01-05, OQ-06)

**Context:**
The geocoding provider is a runtime external dependency. The `IGeocodingService` interface defines a contract, but the concrete implementation depends on the selected provider's response format, authentication model, rate limits, and pricing. Nominatim is dev-only (usage policy). Candidates evaluated: Pelias (self-hosted), Mapbox Geocoding, HERE Geocoding, Azure Maps Search, Photon.

**Decision:**
Use **Azure Maps Search** as the production geocoder. Keep `NominatimGeocodingClient` for local development only.

**Rationale:**
- The project already deploys on Azure — procurement, secrets, and operations stay within one platform
- Azure Maps documents broad European geocoding coverage including strong address and house-number support
- The response shape maps cleanly to the internal `GeocodingCandidate` model
- The API key stays server-side because all geocoding happens behind the backend API

**Field mapping:**

| Azure Maps Field | Internal Field | Notes |
|---|---|---|
| Provider result order | `Rank` | 1-based, preserves provider ranking |
| `formattedAddress` | `Label` | Full place label |
| `countryRegion.ISO` | `Country` | ISO 3166-1 alpha-2 |
| Coordinate pair | `Latitude`, `Longitude` | From `position` object |
| `locality` + first relevant admin field + country name | `DisplayContext` | Disambiguates duplicate place names |

**Behavioral rules:**
- Post-filter results to a Europe allowlist before returning candidates to the client (critical for BR-003)
- Keep `limit = 5` at the app boundary even if the provider returns more (BR-007)

**Key management:**
- API key stored in Azure Key Vault as `geocoding-provider-api-key`
- Injected into API container as `GEOCODING_API_KEY` environment variable
- Never exposed to the browser

**Fallback position:**
- If Phase 0 spike shows weak European coverage, the best fallback is **HERE Geocoding**, not a self-hosted geocoder

**Consequences:**
- `+` Single-platform operations — Azure Maps fits the Azure deployment stack
- `+` Server-side only — no browser key exposure
- `+` Clean field mapping to `GeocodingCandidate` model
- `-` Vendor lock-in to Azure Maps pricing — mitigated by `IGeocodingService` abstraction
- `-` Requires Azure Maps account provisioning during infrastructure setup (Epic 02)

---

## ADR-020: Basemap Tile Provider — MapTiler (Dataviz Light)

**Status:** Approved (S01-06, OQ-07)

**Context:**
The basemap is the visual foundation of the map interface. Provider selection determines the style URL format used by the `MapSurface` component, the attribution text required in the UI, and the key management approach. Candidates evaluated: Mapbox, MapTiler, Stadia Maps, OpenFreeMap.

**Decision:**
Use **MapTiler** as the basemap provider with:
- A light, overlay-friendly **Dataviz** vector style
- A browser-exposed **origin-restricted API key**
- MapLibre GL JS as the rendering library (already planned in frontend architecture)

**Rationale:**
- MapTiler explicitly documents MapLibre usage — straightforward integration path
- Dataviz Light style is designed for data overlays — better default for exposure visualization than a busy streets map
- Origin-restricted API keys match the security architecture for browser-visible basemap credentials
- Keeps basemap choice decoupled from geocoding; avoids Mapbox-specific library coupling

**Configuration:**
- `NEXT_PUBLIC_BASEMAP_STYLE_URL` = MapTiler Dataviz Light `style.json` URL with key parameter
- Key protection: production domain + staging domain restricted; optional localhost dev key kept separate

**Attribution requirements:**
- Keep the MapLibre attribution control enabled
- Visible attribution must satisfy both MapTiler and OpenStreetMap requirements
- Attribution text: "© MapTiler © OpenStreetMap contributors"

**Key management:**
- Origin-restricted browser key (not secret — visible in tile URLs, protected by domain restriction)
- Production and staging domains registered in MapTiler dashboard
- Separate localhost key for development

**Consequences:**
- `+` Best MapLibre fit — documented integration, no GL JS license coupling
- `+` Overlay-friendly cartography — Dataviz Light designed for data visualization
- `+` Straightforward key protection via origin restriction
- `+` Free tier covers expected portfolio traffic levels
- `-` Browser key is visible in network requests — accepted risk with domain restriction
- `-` Dependency on commercial provider — mitigated by MapLibre + standard vector tile protocol (can switch providers without code changes)
