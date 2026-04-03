# 12 — Risks, Assumptions, and Open Questions

> **Status:** Confirmed (known state) | Proposed Architecture (mitigations)
> **Note:** This document consolidates all blocking open questions from the PRD with their architectural impact, tracks working assumptions that must be validated before Phase 1 launch, and documents risks with mitigations.
> **Companion document:** For the closure proposal and rationale, see [17-open-question-closure-proposal.md](17-open-question-closure-proposal.md)
> **Update 2026-04-03:** OQ-02 through OQ-07 resolved and converted to ADRs (ADR-015 through ADR-020). See [11-architecture-decisions.md](11-architecture-decisions.md).

---

## 1. Blocking Open Questions

These must be resolved before Phase 1 (MVP) launch. Architecture structure is ready; specific values and decisions are pending.

### OQ-02 — Scenario Set Definition (RESOLVED)

**Resolution:** ADR-016 (S01-01, approved 2026-04-03)

Three scenarios confirmed: `ssp1-26` / "Lower emissions (SSP1-2.6)", `ssp2-45` / "Intermediate emissions (SSP2-4.5)", `ssp5-85` / "Higher emissions (SSP5-8.5)". IDs are stable keys across database, API, and blob paths. See seed data specification: [`docs/delivery/artifacts/seed-data-spec.sql`](../delivery/artifacts/seed-data-spec.sql).

---

### OQ-03 — Default Scenario and Horizon (RESOLVED)

**Resolution:** ADR-017 (S01-02, approved 2026-04-03)

Default scenario: `ssp2-45` (middle-of-the-road). Default horizon: `2050` (mid-century). `is_default = true` set on the corresponding rows in `scenarios` and `horizons` tables.

---

### OQ-04 — Coastal Analysis Zone Definition (RESOLVED)

**Resolution:** ADR-018 (S01-03, approved 2026-04-03)

Source: Copernicus Land Monitoring Service — Coastal Zones 2018 dataset, dissolved into a single multipolygon, ~10 km inland extent. Validated against 10 reference coordinates (5 coastal, 5 inland). Geometry file: `data/geometry/coastal_analysis_zone.geojson` (produced during pipeline bootstrap). Source documented in `geography_boundaries.source` column.

---

### OQ-05 — Exposure Threshold Methodology (RESOLVED)

**Resolution:** ADR-015 (S01-04, approved 2026-04-03)

Binary exposure methodology confirmed for v1.0. Pixel value `1` = modeled exposure (SLR >= DEM within coastal analysis zone), `0` = no exposure, `NoData` = outside zone. No runtime threshold — exposure is precomputed offline. Full specification: [`docs/delivery/artifacts/methodology-spec.md`](../delivery/artifacts/methodology-spec.md).

---

### OQ-06 — Production Geocoding Provider (RESOLVED)

**Resolution:** ADR-019 (S01-05, approved 2026-04-03)

Azure Maps Search selected as production geocoder. Nominatim retained for development only. Field mapping to `GeocodingCandidate` model documented in ADR-019. API key stored server-side in Key Vault as `geocoding-provider-api-key`. Fallback: HERE Geocoding if European coverage proves insufficient.

---

### OQ-07 — Basemap Tile Provider (RESOLVED)

**Resolution:** ADR-020 (S01-06, approved 2026-04-03)

Azure Maps selected with Light vector style, CORS origin-restricted subscription key, and MapLibre GL JS rendering. Attribution: "© Microsoft, © OpenStreetMap contributors". Style URL via `NEXT_PUBLIC_BASEMAP_STYLE_URL` environment variable. Key management: CORS origin-restricted (production + staging domains). Amended 2026-04-03 from MapTiler to Azure Maps to keep all runtime services under Azure credit coverage.

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

### A-06: COG Files Are Binary (0/1) — Not Continuous (CONFIRMED)

**Confirmed by ADR-015 (2026-04-03).** The exposure layers are pre-computed binary rasters: 1 = exposure zone, 0 = no exposure zone, NoData = outside analysis area. No longer an assumption — this is the approved methodology for v1.0.

---

## 3. Architecture Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | TiTiler `/point` latency too high for assessment p95 target | Medium | High | Phase 0 latency spike (A-01); fallback Option C |
| R-02 | Azure Maps (ADR-019) doesn't return `displayContext`-equivalent field | Medium | Medium | Map `locality` + admin fields to `displayContext`; accept degraded disambiguation |
| R-03 | Azure Container Apps cold start breaks demo | Medium | High | Warm up containers before demo; set `minReplicas: 1` as fallback |
| R-04 | Coastal zone geometry (ADR-018: Copernicus Coastal Zones) is too large / too small | Medium | High | ~10 km inland extent is conservative; iterate after Phase 0 data review |
| R-05 | COG files too large for acceptable tile serving speed | Low | Medium | Ensure correct COG tiling and overview levels during pipeline (see doc 16) |
| R-06 | Basemap provider attribution requirements missed | Low | Medium | ADR-020: Azure Maps + OSM attribution required; add before Phase 1 launch |
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
| OQ-10 | Analytics provider and consent model (see also §1 OQ-10 above) | Phase 2 |
| OQ-11 | Multi-language support (i18n)? | Not in scope for MVP (BR-003 — English only) |
| OQ-12 | Mobile-first vs desktop-first priority for responsive layout? | Phase 1 (UX decision) |

---

## 5. Dependency Map

The following diagram shows which Phase 0 / Phase 1 tasks are blocked by each open question:

```
OQ-02 (Scenarios) ──► RESOLVED (ADR-016): ssp1-26, ssp2-45, ssp5-85
OQ-03 (Defaults)  ──► RESOLVED (ADR-017): ssp2-45, 2050
OQ-04 (Coastal)   ──► RESOLVED (ADR-018): Copernicus Coastal Zones 2018
OQ-05 (Threshold) ──► RESOLVED (ADR-015): Binary, SLR >= DEM
OQ-06 (Geocoding) ──► RESOLVED (ADR-019): Azure Maps Search
OQ-07 (Basemap)   ──► RESOLVED (ADR-020): Azure Maps Light

All blocking questions resolved 2026-04-03. Downstream implementation unblocked.
```
