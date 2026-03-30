# 12 — Risks, Assumptions, and Open Questions

> **Status:** Confirmed (known state) | Proposed Architecture (mitigations)
> **Note:** This document consolidates all blocking open questions from the PRD with their architectural impact, tracks working assumptions that must be validated before Phase 1 launch, and documents risks with mitigations.

---

## 1. Blocking Open Questions

These must be resolved before Phase 1 (MVP) launch. Architecture structure is ready; specific values and decisions are pending.

### OQ-02 — Scenario Set Definition (BLOCKING)

**Question:** What are the exact scenario IDs, display names, descriptions, and sort order for the climate scenarios?

**Current illustrative values (NOT confirmed):**
- `ssp1-26` / "Low (SSP1-2.6)"
- `ssp2-45` / "Intermediate (SSP2-4.5)"
- `ssp5-85` / "High (SSP5-8.5)"

**Architectural impact:**
- Scenario IDs are used as `scenarioId` in `POST /v1/assess` — client and server must agree
- Scenario IDs are part of the COG blob path (`layers/v1.0/{scenarioId}/{year}.tif`)
- Scenario IDs are stored as primary keys in the `scenarios` table — changing them later requires data migration
- **CORS and API contract:** once API is deployed, scenario ID changes are breaking

**Action needed:** Confirm exact scenario IDs, display names, and CONTENT_GUIDELINES-compliant descriptions. Seed into `scenarios` table before Phase 1.

---

### OQ-03 — Default Scenario and Horizon (BLOCKING)

**Question:** Which scenario and horizon are pre-selected on application load?

**Architectural impact:**
- `defaults.scenarioId` and `defaults.horizonYear` returned by `GET /v1/config/scenarios`
- `is_default` field in `scenarios` and `horizons` tables
- Affects the first result a user sees (P-01 Marina's first impression)

**Action needed:** Product decision (PRD §3 or §10 may have guidance). Set `is_default = true` on the chosen rows after OQ-02 is resolved.

---

### OQ-04 — Coastal Analysis Zone Definition (BLOCKING)

**Question:** What is the exact geometry of the `coastal_analysis_zone` used to determine `OutOfScope` vs. `InEuropeAndCoastalZone`?

**Architectural impact:**
- Stored as a `GEOMETRY(MULTIPOLYGON, 4326)` row in `geography_boundaries` table
- `PostGisGeographyRepository.IsWithinCoastalZoneAsync` queries this geometry
- Definition directly determines which locations get an assessment vs. "Outside MVP Coverage Area"
- Amsterdam (coastal) should return `InCoastalZone`; Prague (inland) should return `OutOfScope`
- The boundary is inherently ambiguous near transition zones (50 km from coast? EEA coastal zone definition?)

**Action needed:** Select a source geometry (Natural Earth 10m coastline buffer? EEA coastal zone shapefile?) and seed into database. Document source in `geography_boundaries.source` column.

---

### OQ-05 — Exposure Threshold Methodology (BLOCKING)

**Question:** What is the exact methodology for determining whether a point is "exposed"? Specifically: is the pixel value threshold binary (0/1), and what does value 1 mean precisely?

**Architectural impact:**
- Determines `ExposureEvaluator` implementation
- Determines whether COG pixel values are binary (0/1) or continuous (sea-level rise in meters)
- If binary: `pixelValue == 1` → `ModeledExposureDetected` (simple, current assumption)
- If continuous: needs threshold comparison against `exposure_threshold` in `methodology_versions`
- `CONTENT_GUIDELINES.md §3` interpretation text depends on this definition

**Current assumption:** Binary COG (0 = no exposure, 1 = exposure, NoData = outside zone). This drives the entire pipeline design. If the answer is continuous, significant pipeline rework is needed.

**Action needed:** Confirm binary vs continuous approach with whoever is defining the methodology. Document in `methodology_versions.exposure_threshold_desc`.

---

### OQ-06 — Production Geocoding Provider (BLOCKING)

**Question:** Which geocoding provider is used in production? Nominatim is dev-only (acceptable use policy prohibits high-volume use).

**Candidate providers:** Pelias, Mapbox Geocoding API, HERE Geocoding, Azure Maps Search, Photon

**Architectural impact:**
- Provider is encapsulated behind `IGeocodingService` — code change required only in the Infrastructure layer
- Provider response format must be normalized to `GeocodingCandidate` (Rank, Label, Country, DisplayContext)
- `displayContext` availability varies by provider — some return admin hierarchy, some do not
- API key must be stored in Key Vault and injected as `GEOCODING_API_KEY`
- Provider selection affects candidate quality for European place names (P-01 Marina's primary use case)

**Action needed:** Select provider. Implement `[Provider]GeocodingClient` replacing `NominatimGeocodingClient` placeholder.

---

### OQ-07 — Basemap Tile Provider (BLOCKING for visual output)

**Question:** Which provider serves the background map tiles?

**Candidate providers:** Mapbox, MapTiler, Stadia Maps, OpenFreeMap (OSM-based, free)

**Architectural impact:**
- Basemap URL template is `NEXT_PUBLIC_BASEMAP_TILE_URL` in frontend environment
- Provider key may need domain restriction (see [07-security-architecture.md](07-security-architecture.md) §3.3)
- Map style (light/dark/satellite) is configured via this URL — affects visual design
- Some providers (MapTiler, Mapbox) require attribution in the map UI (legal requirement)

**Action needed:** Select provider. Configure URL template. Add attribution element to MapSurface component.

---

### OQ-10 — Analytics Implementation (Non-blocking for MVP, blocking for metrics)

**Question:** Should product analytics be implemented? If yes, which provider and what consent model?

**Architectural impact:**
- If enabled: analytics event calls added to frontend for key interactions (see METRICS_PLAN.md §6)
- Privacy: only `country_code` allowed in events — no coordinates, no query strings, no user identifiers (GDPR)
- Consent: if using cookies, ePrivacy consent banner required for EU visitors
- Provider options: Plausible (GDPR-friendly, no cookies), Fathom, Posthog, custom
- If server-side events only (via API logs + KQL): no consent required

**Action needed:** Product decision on analytics. Architecture is ready to accommodate either path.

---

## 2. Working Assumptions

These are architectural decisions made based on incomplete information. Each must be validated before Phase 1.

### A-01: TiTiler `/point` Latency is Acceptable

**Assumption:** TiTiler's `/point/{lng},{lat}` endpoint responds in ≤ 200ms for a warm COG (already cached in GDAL's VSI cache).

**Risk if wrong:** Assessment p95 latency exceeds NFR-003 (3.5s). TiTiler `/point` has variable latency depending on COG spatial indexing, GDAL cache state, and Azure Blob I/O.

**Validation:** Phase 0 spike — measure `/point` latency against real COG files on Azure Blob Storage from the API container.

**Fallback:** Implement Option C (pre-materialized point lookup in PostGIS raster table) if TiTiler `/point` latency is insufficient.

---

### A-02: PostGIS ST_Within Performance is ≤ 20ms

**Assumption:** With GIST index, `ST_Within` against the Europe boundary geometry completes in ≤ 20ms.

**Risk if wrong:** Two `ST_Within` checks at 50ms each would consume 100ms of the 3.5s assessment budget.

**Validation:** Benchmark `ST_Within` against the actual Europe boundary geometry (Natural Earth or EEA) in the target PostgreSQL SKU (Burstable B1ms).

**Fallback:** Simplify geometry (reduce polygon vertices), upgrade PostgreSQL SKU, or cache geography results per coordinate.

---

### A-03: Container Apps Cold Start is Acceptable for Demo

**Assumption:** Scale-to-zero cold starts (typically 10–30s for .NET containers) are acceptable because the demo will have the app warmed up before presentation.

**Risk if wrong:** If P-03 Yuki opens the app without prior warm-up, the first request may time out or appear slow.

**Validation:** Measure cold start times for API and TiTiler containers on Azure Container Apps Consumption plan.

**Fallback:** Set `minReplicas: 1` on API and TiTiler containers to prevent scale-to-zero (adds ~$10–20/month).

---

### A-04: Europe Boundary Geometry is Correct and Complete

**Assumption:** The `europe` geometry in `geography_boundaries` correctly classifies all intended European countries as in-scope.

**Risk if wrong:** Edge cases: Kosovo, Russia-in-Europe, Kaliningrad, Cyprus, Canary Islands, Azores. Classification errors could produce confusing results for users.

**Validation:** Manual spot-check of 20 representative coordinates against the seeded geometry.

---

### A-05: Single TiTiler Instance Handles Both Tile and Point Requests

**Assumption:** A single TiTiler container serves both browser tile requests (`/{z}/{x}/{y}.png`) and assessment point queries (`/point/{lng},{lat}`) without performance interference.

**Risk if wrong:** A burst of tile requests (user panning the map) could starve assessment point queries, increasing assessment latency.

**Validation:** Load test with concurrent tile and point requests.

**Fallback:** Deploy two TiTiler instances (one internal-only for assessment, one public for tiles).

---

### A-06: COG Files Are Binary (0/1) — Not Continuous

**Assumption:** The exposure layers are pre-computed binary rasters: 1 = exposure zone, 0 = no exposure zone, NoData = outside analysis area.

**Risk if wrong (see OQ-05):** If the layers are continuous (sea-level rise in meters), the `ExposureEvaluator` must compare pixel values against a threshold rather than checking `pixelValue == 1`.

**Validation:** Resolve OQ-05 with the methodology team.

---

## 3. Architecture Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | TiTiler `/point` latency too high for assessment p95 target | Medium | High | Phase 0 latency spike (A-01); fallback Option C |
| R-02 | Geocoding provider (OQ-06) doesn't return `displayContext`-equivalent field | Medium | Medium | Map provider's admin hierarchy fields to `displayContext`; accept degraded disambiguation |
| R-03 | Azure Container Apps cold start breaks demo | Medium | High | Warm up containers before demo; set `minReplicas: 1` as fallback |
| R-04 | Coastal zone geometry (OQ-04) is too large / too small | Medium | High | Define zone conservatively; plan to iterate after Phase 0 data review |
| R-05 | COG files too large for acceptable tile serving speed | Low | Medium | Ensure correct COG tiling and overview levels during pipeline (see doc 16) |
| R-06 | Basemap provider attribution requirements missed | Low | Medium | Review OQ-07 provider license; add attribution before Phase 1 launch |
| R-07 | GDAL VSIAZ driver not configured correctly for Azure Blob | Medium | High | Phase 0 spike: verify TiTiler can read COG from Azure Blob with managed identity |
| R-08 | `results` cache (60s TanStack Query) serves stale data after methodology version change | Low | Medium | Methodology version changes are rare + manual; acceptable to restart containers to clear in-process cache |
| R-09 | DB connection pool exhaustion at concurrent demo traffic | Low | Medium | Monitor `active_connections`; set Npgsql `Maximum Pool Size = 20` per API instance |
| R-10 | MapLibre `unsafe-eval` CSP requirement blocked by hosting security policy | Low | Low | MapLibre requires `unsafe-eval`; document explicitly in security checklist |

---

## 4. Non-Blocking Open Questions

These don't block MVP but must be addressed before or during Phase 2.

| OQ | Question | Phase |
|---|---|---|
| OQ-01 | What is the supported browser matrix? (NFR-022) | Phase 1 |
| OQ-08 | Should a CDN be used for frontend assets? | Phase 3 |
| OQ-09 | Is server-side rendering required for SEO? (Note: `noindex` is default for portfolio demos) | Phase 2 |
| OQ-10 | Analytics provider and consent model | Phase 2 |
| OQ-11 | Multi-language support (i18n)? | Not in scope for MVP (BR-003 — English only) |
| OQ-12 | Mobile-first vs desktop-first priority for responsive layout? | Phase 1 (UX decision) |

---

## 5. Dependency Map

The following diagram shows which Phase 0 / Phase 1 tasks are blocked by each open question:

```
OQ-02 (Scenarios) ──► Seed scenarios table
                  ──► Generate COG paths (scenario IDs in blob paths)
                  ──► Test data for E2E tests

OQ-03 (Defaults) ──► GET /v1/config/scenarios response
                 ──► Initial UI state on load

OQ-04 (Coastal zone) ──► Seed coastal_analysis_zone geometry
                     ──► IsWithinCoastalZone integration tests
                     ──► OutOfScope vs. coastal test cases

OQ-05 (Threshold) ──► ExposureEvaluator implementation
                  ──► COG pipeline design (binary vs continuous)
                  ──► CONTENT_GUIDELINES interpretation text

OQ-06 (Geocoding) ──► Production GeocodingClient implementation
                  ──► API key procurement
                  ──► displayContext field availability

OQ-07 (Basemap) ──► MapSurface tile URL configuration
               ──► Attribution requirements
               ──► Map visual style
```
