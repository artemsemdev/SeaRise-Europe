# Delivery Audit — ROADMAP.md vs. Reality

**Audit date:** 2026-04-13
**Audited against:** [ROADMAP.md](ROADMAP.md) (last updated 2026-04-03, claims 47/58 stories delivered, Waves 3–7 at 100%)
**Method:** Direct verification against source code, configs, CI, SQL seed, pipeline artifacts, unit test runs, **and a live `docker compose up --build` probe of the running stack** — health endpoints, config endpoints, real geocode call, real assessment call, direct SQL against the running PostGIS instance, and in-container port checks.
**Verdict:** **Status in ROADMAP.md is overstated and the stack does not currently come up end-to-end.** The project is a strong foundation plus a partially assembled MVP — not 7 closed waves. Two live-confirmed container-level bugs prevent `docker compose up` from ever reaching a healthy state.

---

## Summary Verdict by Wave

| Wave | Epic | ROADMAP claim | Audit status | One-line gap |
|---|---|---|---|---|
| 1 | Decision Closure | 7/7 DONE | **Mostly done** | S01-05 ADR says Azure Maps; production geocoder in code is Nominatim |
| 2 | Local Dev Environment | 3/3 DONE | **Partial** | Individual services start, but `docker compose up` never becomes healthy: API Dockerfile has no `curl` so its healthcheck always fails, and tiler port mapping is wrong (`8000:8000` while TiTiler listens on port 80). Frontend never starts because it depends on `api: service_healthy`. |
| 3 | Geospatial Pipeline | 8/8 DONE | **Not done** | No coastal zone geometry bootstrap; DB seeds `MULTIPOLYGON EMPTY`; `europe_geojson` never wired through `run_pipeline.py` |
| 4 | Backend API Core | 7/7 DONE | **Mostly done** | Code and unit tests green; 12/26 integration tests fail when Docker/Testcontainers is unavailable in the audit environment |
| 5 | Frontend Search | 8/8 DONE | **Partial** | Geocoding via `useMutation` (not query-based); click-to-assess short-circuits when no prior location |
| 6 | Assessment UX | 7/7 DONE | **Partial** | `useAssessment` staleTime is 5 min, ROADMAP says `60_000`; methodology API ↔ UI contract broken |
| 7 | Transparency & A11y | 7/7 DONE | **Partial** | i18n/content lint is toothless; responsive tablet/mobile layouts not in code; hardcoded strings remain |
| 8 | Azure Release | 0/11 PLANNED | **Not started** | Accurate; note HSTS is already implemented locally, contrary to ROADMAP remark |

**Honest counts:** documentation and local foundation real; backend core substantially real; frontend shell real but untested in a running stack because the stack does not come up; transparency/compliance significantly overstated; operational geospatial baseline not real; production geocoder not real.

---

## Runtime Reality Check (Live Stack Probe)

This section captures findings from a live `docker compose up --build` run performed at audit time. Every claim here is backed by observed output from the running stack, not code inspection.

### What actually works (live-verified)

These components start and respond correctly when probed directly, bypassing compose healthchecks.

| Component | Evidence | Status |
|---|---|---|
| **Postgres + PostGIS** | `postgres` container reaches `healthy` state. `init.sql` runs cleanly: 3 scenarios, 3 horizons, 1 methodology version, 2 geography rows inserted. PostGIS extensions created. | ✅ Starts and seeds reference data |
| **Azurite** | Starts and listens on `10000` (Blob), `10001` (Queue), `10002` (Table). Container reaches `healthy`. | ✅ Fully functional |
| **API process** | `dotnet SeaRise.Api.dll` starts inside container, logs `Application started. Press Ctrl+C to shut down.`, listens on `http://[::]:8080`. All endpoints tested below respond. | ✅ Process is fine; container healthcheck is not |
| **`GET /health`** | `curl http://localhost:8080/health` → `HTTP 200 {"status":"healthy",...}`. With `X-Health-Detail: 1`: `{"postgres":"healthy","blobStorage":"unknown"}`. | ✅ Responds 200; postgres check real; blob check skipped because `AZURE_STORAGE_CONNECTION_STRING` is not set for the API in compose |
| **`GET /v1/config/scenarios`** | Returns all 3 scenarios (`ssp1-26`, `ssp2-45`, `ssp5-85`), all 3 horizons (2030, 2050, 2100), defaults `ssp2-45` / `2050`. Matches ADR-016 / ADR-017. | ✅ Correct |
| **`GET /v1/config/methodology`** | Returns the real API shape: `seaLevelProjectionSource`, `elevationSource`, `whatItDoes`, `whatItDoesNotAccountFor[5]`, `resolutionNote`, `interpretationGuidance`, `updatedAt`. | ✅ API works — but this is exactly the shape the frontend type does NOT match (Finding #2 earlier). |
| **`POST /v1/geocode`** | Query `"Amsterdam"` returns 5 candidates (Amsterdam NL at 52.3730796, 4.8924534; also Île Amsterdam FR, Amsterdam NY, Amsterdam MO). Call goes out to Nominatim from inside the API container. | ✅ Geocoding pipeline is fully functional against Nominatim |
| **`POST /v1/assess`** | Endpoint responds 200 with a well-formed `AssessResponse` payload (see "Broken" below for the content issue). | ✅ Wiring and serialization work |

### What is broken (live-confirmed)

These were not deductions from reading code — they were observed in the running stack.

**R1. API Dockerfile has no `curl`, so its healthcheck is guaranteed to fail.**
Evidence: ran `docker exec seariseeurope-api-1 ls /usr/bin/curl` inside the live container → `No such file or directory`. The compose healthcheck at [docker-compose.yml:58](../../docker-compose.yml#L58) is `curl -f http://localhost:8080/health` and the API image is built from `mcr.microsoft.com/dotnet/aspnet:8.0` (see [src/api/Dockerfile:16](../../src/api/Dockerfile#L16)) without installing `curl`. The API process responds to `/health` with 200 from the host, but the in-container probe fails because the binary does not exist. Result: container is marked `unhealthy` forever. Because the frontend depends on `api: service_healthy` at [docker-compose.yml:32-33](../../docker-compose.yml#L32-L33), the frontend container never leaves the `Created` state. `docker compose up --build` exits with `dependency failed to start: container seariseeurope-api-1 is unhealthy` and code 1. **The stack never comes up via the documented `docker compose up --build` entrypoint.**

**R2. TiTiler port mapping is wrong.** TiTiler listens on port **80** inside the container, not 8000. Evidence from inside the running tiler container:

```
python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1',80)); print('port 80: OPEN')"
  → port 80: OPEN
python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1',8000))"
  → ConnectionRefusedError: [Errno 111] Connection refused
```

Also confirmed by tiler startup log: `[INFO] Listening at: http://0.0.0.0:80 (7)`. But compose maps `"8000:8000"` at [docker-compose.yml:70](../../docker-compose.yml#L70), and the API is told `TILER_BASE_URL: http://tiler:8000` at [docker-compose.yml:51](../../docker-compose.yml#L51). So:
- Host → tiler: `curl http://localhost:8000/healthz` → HTTP 000 (no listener on the container side of the mapping).
- API → tiler: any call to `http://tiler:8000/*` gets `ConnectionRefusedError`.
- Tiler's own compose healthcheck `curl -f http://localhost:8000/healthz` also fails forever, so the tiler container is marked unhealthy (observed: `Up (unhealthy)`).

Consequence: even if R1 is fixed, every exposure evaluation (`TiTilerExposureEvaluator` calls `/point`) and every map raster tile request would fail at the network layer. The exposure layer is **unreachable as configured**.

**R3. DB ships `MULTIPOLYGON EMPTY` for both geography boundaries (live-verified).** Static finding #1 was confirmed by direct SQL against the running Postgres:

```
SELECT name, ST_IsEmpty(geom), ST_AsText(ST_Envelope(geom)) FROM geography_boundaries;
  europe                | t | MULTIPOLYGON EMPTY
  coastal_analysis_zone | t | MULTIPOLYGON EMPTY
```

**R4. `layers` table is empty.** `SELECT COUNT(*) FROM layers;` → `0`. `init.sql` never seeds it, and the pipeline's `register.py` has never been executed against the local DB. Even if geometry were fixed, `LayerRepository` would return `null` for every scenario × horizon combination, driving results into `DataUnavailable`.

**R5. The live app can only produce `UnsupportedGeography` for any location.** Two real POST calls against the running API:

```
POST /v1/assess {lat:52.37, lng:4.90, scenario:ssp2-45, horizon:2050}  // Amsterdam
  → resultState: "UnsupportedGeography"

POST /v1/assess {lat:50.08, lng:14.43, scenario:ssp2-45, horizon:2050}  // Prague
  → resultState: "UnsupportedGeography"
```

Both return `UnsupportedGeography` because the `europe` boundary is empty, so the first `ST_Covers` check in `AssessmentService` short-circuits all requests to that state. **Four of the five advertised result states (`ModeledExposureDetected`, `NoModeledExposureDetected`, `OutOfScope`, `DataUnavailable`) are literally unreachable in the shipped default.** The fifth (`UnsupportedGeography`) is the only output the live app can currently produce. ROADMAP S06-03 claims "ResultPanel with All 5 Result States" is delivered — structurally yes, but the end-to-end system can demonstrate only one of them.

**R6. MethodologyPanel will crash against the live API payload.** I now have the literal JSON returned by the running API (see the "works" table above). The frontend component at [MethodologyPanel.tsx:132](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L132) does `data.models.map(...)`. The live response has no `models` field. Calling `.map` on `undefined` throws `TypeError`. This is a runtime crash waiting to happen — the only reason it has not been seen is that the frontend never actually starts in the current stack (R1).

### What could NOT be tested in this audit

Because R1 prevents the frontend from ever starting, I could not verify any of these at runtime. Their status is "unverified, best-guess from code":

- Frontend shell rendering and navigation
- SearchBar + CandidateList + geocoding flow end to end
- MapSurface pan/zoom/click-to-assess
- ResultPanel visual states (any of the 5)
- MethodologyPanel drawer (but we know it crashes from code — see R6)
- Legend component
- URL state synchronization
- Tablet / mobile responsive behavior
- axe-core / keyboard navigation / focus trap
- Content/i18n behavior in a real browser

These must be re-verified after R1 and R2 are fixed — anything currently marked DONE in Wave 5/6/7 that touches these areas should be considered unverified.

---

## Confirmed Findings

Each finding below was verified directly against source files at audit time. File paths link to the exact line.

### 1. Wave 3 / geospatial pipeline is not closed

The pipeline orchestration runs, but the European geography baseline it depends on was never produced end-to-end.

- **DB still ships `MULTIPOLYGON EMPTY` for both `europe` and `coastal_analysis_zone`.** Concrete SQL at [infra/db/init.sql:184](../../infra/db/init.sql#L184) and [infra/db/init.sql:192](../../infra/db/init.sql#L192). With empty geometries, every PostGIS `ST_Covers` / `ST_Intersects` check against `geography_boundaries` will return false and drive results into `OutOfScope` or `UnsupportedGeography` regardless of input.
- **`coastal_analysis_zone.geojson` is declared Pending.** See [data/geometry/README.md:9](../../data/geometry/README.md#L9): the canonical artifact for S01-03 / S03-04 is not checked in and no generated copy exists.
- **`run_pipeline.py` only passes the coastal path; never passes an europe polygon.** [src/pipeline/run_pipeline.py:134](../../src/pipeline/run_pipeline.py#L134) calls `seed_all(db_conn, coastal_zone_geojson=coastal_zone)` with no `europe_geojson=...` argument. The supporting function at [src/pipeline/register.py:192-229](../../src/pipeline/register.py#L192-L229) accepts an `europe_geojson` parameter but falls back to `MULTIPOLYGON EMPTY` when it is not supplied.
- **`download.py` only fetches IPCC AR6 and Copernicus DEM.** [src/pipeline/download.py:1-11](../../src/pipeline/download.py#L1-L11) documents exactly those two data sources. There is no module that downloads, dissolves, reprojects, and exports the Copernicus Coastal Zones 2018 vector into `coastal_analysis_zone.geojson` — the 6-step recipe in [data/geometry/README.md:20-26](../../data/geometry/README.md#L20-L26) is unimplemented.

**Impact:** S03-01..08 cannot be considered “done” by any honest definition. The pipeline is a tested set of modules; it is not an operational geospatial baseline.

### 2. MethodologyPanel is broken against the real API (runtime gap)

The API and the UI agree on neither field names nor shape. This is a direct runtime break in Wave 6 / Wave 7 functionality.

- **API returns** `seaLevelProjectionSource`, `elevationSource`, `whatItDoes`, `whatItDoesNotAccountFor`, `resolutionNote`, `interpretationGuidance`, `updatedAt`. See [src/api/SeaRise.Api/Dtos/ConfigMethodologyResponse.cs:3-12](../../src/api/SeaRise.Api/Dtos/ConfigMethodologyResponse.cs#L3-L12) and the endpoint body at [src/api/SeaRise.Api/Program.cs:371-388](../../src/api/SeaRise.Api/Program.cs#L371-L388).
- **Frontend type expects** `projectionSource`, `description`, `models: MethodologyModel[]`, `dataUpdated`. See [src/frontend/src/lib/types/index.ts:87-98](../../src/frontend/src/lib/types/index.ts#L87-L98).
- **UI component reads** `data.description`, `data.models.map(...)`, `data.limitations.map(...)`, `data.dataUpdated`. See [src/frontend/src/app/components/assessment/MethodologyPanel.tsx:120](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L120), [MethodologyPanel.tsx:132](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L132), [MethodologyPanel.tsx:163](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L163), [MethodologyPanel.tsx:190](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L190).

**Impact:** Opening the methodology drawer against the real `GET /v1/config/methodology` at best renders missing fields; the `data.models.map(...)` call throws on undefined. S07-01 (“Implement MethodologyPanel”) cannot be considered delivered until either the API is extended or the UI is rewritten against the current response shape. This also blocks the S01-04 methodology-visibility claim.

### 3. Production geocoder per ADR-019 is not implemented

ROADMAP shows S01-05 as DONE with Azure Maps, but the running API uses Nominatim.

- **API registration.** [src/api/SeaRise.Api/Program.cs:47-75](../../src/api/SeaRise.Api/Program.cs#L47-L75) wires `IGeocodingService` to `NominatimGeocodingClient` and defaults `GEOCODING_BASE_URL` to `https://nominatim.openstreetmap.org`.
- **No `AzureMapsGeocodingClient` class exists** in `src/api/SeaRise.Api/Infrastructure/Clients/` (verified: only `NominatimGeocodingClient` and `TiTilerExposureEvaluator` are present).

**Impact:** ADR-019 is a paper decision. This is both a Wave 1 correctness issue (S01-05 not really closed) and a Wave 8 security/privacy issue (Nominatim public tier is not a production geocoder per the NFRs, and has different retention/rate-limit behavior than Azure Maps).

### 4. Wave 7 (transparency / i18n / content compliance) is significantly overstated

The dashboard marks S07-02, S07-03, S07-06 and S07-07 as delivered. The lint scripts enforcing these claims are either permissive or entirely skipped, and the audit artifacts are out of sync with the code.

- **Content audit log contradicts current strings.** The committed report at [docs/delivery/artifacts/content-audit-log.md:21](artifacts/content-audit-log.md#L21) describes one set of result-state labels, while the actual i18n bundle at [src/frontend/src/lib/i18n/en.ts:9-15](../../src/frontend/src/lib/i18n/en.ts#L9-L15) uses `"Risk detected"`, `"No risk detected"`, and summary copy that says `"does not mean it is safe"`. The artifact is a frozen snapshot; it is not a live audit.
- **Prohibited-language scanner whitelists the disputed phrases.** [src/frontend/scripts/lint-prohibited-language.ts:12-32](../../src/frontend/scripts/lint-prohibited-language.ts#L12-L32) lists `"is safe"` as prohibited but then adds `"No risk detected"` and `"does not mean it is safe"` to `APPROVED_EXCEPTIONS`. Net result: a scanner that would otherwise flag the exact strings the CONTENT_GUIDELINES call out explicitly allows them by name. This is a self-defeating gate.
- **i18n externalization lint does not enforce.** The script at [src/frontend/scripts/lint-i18n-externalization.ts:58](../../src/frontend/scripts/lint-i18n-externalization.ts#L58) skips a component if it already imports `strings`, and does not exit non-zero on findings. A component can import `strings` once and keep arbitrary hardcoded English — the lint says nothing.
- **Hardcoded user-facing strings remain.** [src/frontend/src/app/components/AppShell.tsx:39](../../src/frontend/src/app/components/AppShell.tsx#L39) renders literal `"SEARISE EUROPE"`; similar fixed strings appear in SearchBar and ResultPanel. These are real user-visible strings, not code identifiers, and they live outside `en.ts`.
- **Responsive tablet/mobile layouts are not implemented.** [src/frontend/src/app/components/assessment/Sidebar.tsx:39-43](../../src/frontend/src/app/components/assessment/Sidebar.tsx#L39-L43) renders a fixed `w-[280px] min-w-[280px]` left column. There is no tablet collapsible panel and no mobile bottom sheet, which is what S07-06 and [docs/delivery/artifacts/a11y-audit-report.md](artifacts/a11y-audit-report.md) claim was delivered.

**Impact:** S07-02, S07-03, S07-06, S07-07 cannot be considered complete. The axe-core scan result is not in dispute, but the broader story acceptance criteria (content compliance, responsive layout, live lint gates) are not actually enforced in CI today.

### 5. Wave 5/6 behaviors diverge from the ROADMAP wording

These are smaller but real contradictions between dashboard text and code.

- **`useAssessment` staleTime ≠ advertised.** ROADMAP S06-02 says `staleTime: 60_000` (1 minute). Actual code at [src/frontend/src/lib/api/assessment.ts:41](../../src/frontend/src/lib/api/assessment.ts#L41) sets `staleTime: 5 * 60 * 1000` (5 minutes). Either the ROADMAP text or the code needs to change — they cannot both be correct.
- **Geocoding uses `useMutation`, not a query.** S05-04 is described as a TanStack Query flow with caching, but the implementation in `src/frontend/src/lib/api/geocoding.ts` is a mutation — no query key, no `staleTime`, no cache reuse across retries.
- **Click-to-assess short-circuits without a prior location.** [src/frontend/src/app/components/map/MapSurface.tsx:52-56](../../src/frontend/src/app/components/map/MapSurface.tsx#L52-L56): `const currentLocation = useMapStore.getState().selectedLocation; if (!currentLocation) return;`. A fresh visitor who clicks on the map without first searching gets no assessment. The S05-03 description promises click-to-assess as an independent entry path.

**Impact:** These do not block the MVP, but they mean the ROADMAP is not an accurate contract. They should either be reframed as known limitations or fixed.

### 6. HSTS ROADMAP note is self-contradictory

[ROADMAP.md:73](ROADMAP.md#L73) and [ROADMAP.md:94](ROADMAP.md#L94) both say HSTS is “pending Azure.” HSTS is already sent in two places today:

- [src/api/SeaRise.Api/Program.cs:177](../../src/api/SeaRise.Api/Program.cs#L177): `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
- [src/frontend/next.config.js:10](../../src/frontend/next.config.js#L10) (verified separately): same header on the Next.js side.

**Impact:** S08-06 sub-item is more complete than the ROADMAP indicates. This is a benign discrepancy but shows that dashboard text drifts from code.

---

## Live Test Runs (audit environment)

Run verbatim on the current `master`. These are the only test executions I performed.

| Command | Result |
|---|---|
| `cd src/frontend && npm test` | **75 / 75 passed** |
| `dotnet test SeaRise.sln -c Release --filter "Category=Unit"` | **39 / 39 passed** |
| `dotnet test SeaRise.sln -c Release --filter "Category=Integration"` | **14 / 26 passed, 12 / 26 failed** (Testcontainers requires Docker; not available in audit env) |
| `dotnet test SeaRise.sln -c Release` (full) | **53 passed / 12 failed** |
| `cd src/pipeline && pytest tests/ -q` | **Fails on collection** — `xarray` incompatible with installed NumPy 2.0+; dependencies in [src/pipeline/pyproject.toml](../../src/pipeline/pyproject.toml) are not version-pinned |

**Note on integration tests:** the 12 failures are environmental, not logic failures. They still matter because:
- They expose that the pipeline tests have no pinned runtime contract and can silently break on newer numpy.
- They expose that backend integration test verification is only real when Docker is present — ROADMAP counts 12 integration tests as green without noting this dependency.

---

## Re-Plan from Reality — Getting to an Honest MVP

Forget the 58-story roadmap for a moment. Here is the smallest path from the current state to an application that (a) starts via `docker compose up`, (b) returns real results for real European locations, and (c) does not crash on the methodology drawer. The plan is grouped into **phases** — each phase has a single exit criterion and is ordered by dependency: later phases assume earlier ones are done.

### Phase 0 — "Make it start" (blocks everything else)

**Exit criterion:** `docker compose up --build` on a clean machine reaches "all services healthy" and does not exit.

| # | Task | Files | Estimate | Why it blocks everything |
|---|---|---|---|---|
| P0.1 | Install `curl` in the API runtime image **or** rewrite the compose healthcheck to use `wget --spider`/`dotnet SeaRise.Api.dll --health`/a `.NET HealthCheck`-compatible probe | [src/api/Dockerfile:16-26](../../src/api/Dockerfile#L16-L26), [docker-compose.yml:58](../../docker-compose.yml#L58) | trivial | Without this, the API container is always `unhealthy`, so the frontend never leaves `Created`. Nothing downstream can be demonstrated. |
| P0.2 | Fix TiTiler port: either map `8000:80` in compose **or** set `PORT=8000` in tiler env. Correspondingly set `TILER_BASE_URL: http://tiler:80` (or keep 8000 if the env var is used). Update the tiler healthcheck to the matching port. | [docker-compose.yml:51, 70, 83](../../docker-compose.yml#L51) | trivial | TiTiler listens on 80 internally; compose advertises 8000 on both sides. Exposure evaluation cannot work until this is aligned. |
| P0.3 | Add a single "compose smoke" script / CI step that runs `docker compose up -d --wait` and fails if any service is unhealthy after 2 minutes. This is what would have caught P0.1 and P0.2 before they shipped. | new file under `scripts/` or `.github/workflows/ci.yml` | small | Without it, this exact regression returns the next time someone edits the compose file. |

**After Phase 0 the stack is up but still only returns `UnsupportedGeography`.**

### Phase 1 — "Make results real" (core correctness)

**Exit criterion:** A real European coastal location returns a non-`UnsupportedGeography` result, and the methodology drawer opens without crashing.

| # | Task | Files | Estimate | Depends on |
|---|---|---|---|---|
| P1.1 | Produce or obtain `data/geometry/europe.geojson` (dissolved Natural Earth Admin 0 filtered to supported European countries, EPSG:4326) and check it into the repo **or** host it outside. Size is small (a few MB dissolved). | [data/geometry/README.md](../../data/geometry/README.md), new file | small | — |
| P1.2 | Produce or obtain `data/geometry/coastal_analysis_zone.geojson` per the recipe in [data/geometry/README.md:20-26](../../data/geometry/README.md#L20-L26) (Copernicus Coastal Zones 2018, dissolve, clean in EPSG:3035, reproject, clip to europe). Either as a new pipeline step (long term) or a one-time scripted artifact (pragmatic). | new pipeline module or script | medium | P1.1 |
| P1.3 | Pass both geometries through `run_pipeline.py`: add `europe_geojson=...` to the `seed_all(...)` call at [src/pipeline/run_pipeline.py:134](../../src/pipeline/run_pipeline.py#L134), and make sure both files are picked up by `seed_geography_boundaries` at [src/pipeline/register.py:192-229](../../src/pipeline/register.py#L192-L229). | [run_pipeline.py](../../src/pipeline/run_pipeline.py#L134), [register.py](../../src/pipeline/register.py#L192) | small | P1.2 |
| P1.4 | **Alternative quick path** (if you want to skip running the full pipeline): bake the final geometries directly into `init.sql` via `ST_GeomFromGeoJSON` + `pg_read_binary_file`, or via a second init script that loads from mounted `data/geometry/*.geojson`. Drops dependency on a working pipeline run for local demo. | [infra/db/init.sql:181-195](../../infra/db/init.sql#L181) | small | P1.1, P1.2 |
| P1.5 | Seed at least one real layer row per scenario × horizon combo in `layers`, pointing at a COG accessible to the running TiTiler. Two options: (a) run the actual pipeline end-to-end so COGs land in Azurite and `register.py` fills the table, or (b) ship a minimal synthetic COG set and a one-shot SQL seed for local demo. | `layers` table seed, pipeline run or synthetic COG generator | **medium–large** | P0.2, P1.3 or P1.4 |
| P1.6 | Fix the MethodologyPanel contract. Decision: **rewrite the frontend against the real API shape**, because the API shape matches the PRD and the frontend type is the drift. Update [src/frontend/src/lib/types/index.ts:87-98](../../src/frontend/src/lib/types/index.ts#L87-L98) and [MethodologyPanel.tsx](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx) to render `whatItDoes`, `whatItDoesNotAccountFor[]`, `resolutionNote`, `seaLevelProjectionSource`, `elevationSource`, `interpretationGuidance`, `updatedAt`. Delete the `models[]` path entirely. | frontend methodology files | small | — (can run in parallel with the geometry work) |
| P1.7 | Add a contract test that deserializes a real `GET /v1/config/methodology` response into the frontend `MethodologyData` type and fails if any field is missing. This is the guard that stops P1.6 from silently drifting again. | new test file | small | P1.6 |

**After Phase 1 the application honestly demonstrates the methodology — at least one location per scenario × horizon returns `ModeledExposureDetected` or `NoModeledExposureDetected`, and the methodology drawer renders.**

### Phase 2 — "Make it behave like a finished MVP" (UX correctness)

**Exit criterion:** A first-time visitor to `http://localhost:3000` can search for a city, click a candidate, see a result, click the methodology drawer, click on the map to re-assess, and not hit any hardcoded strings or broken responsive states.

| # | Task | Files | Estimate |
|---|---|---|---|
| P2.1 | Remove the early-return in [MapSurface.tsx:52-56](../../src/frontend/src/app/components/map/MapSurface.tsx#L52-L56). A fresh map click should start a new assessment even when `selectedLocation` is null. | MapSurface.tsx | small |
| P2.2 | Reconcile assessment `staleTime`. Pick 60 seconds or 5 minutes based on the actual intended cache semantics, update either the code at [assessment.ts:41](../../src/frontend/src/lib/api/assessment.ts#L41) or the ROADMAP text — they must agree. | assessment.ts OR ROADMAP.md | trivial |
| P2.3 | Rewrite geocoding from `useMutation` to a proper `useQuery` with a cache key, so repeated identical searches reuse results and the cache policy is inspectable. | [src/frontend/src/lib/api/geocoding.ts](../../src/frontend/src/lib/api/geocoding.ts) | small |
| P2.4 | Remove hardcoded user-facing strings: `"SEARISE EUROPE"` in [AppShell.tsx:39](../../src/frontend/src/app/components/AppShell.tsx#L39), and the similar leftovers in SearchBar and ResultPanel. Move them into `en.ts`. | AppShell.tsx, SearchBar.tsx, ResultPanel.tsx, en.ts | small |
| P2.5 | Make the lint gates actually lint. `lint-i18n-externalization.ts` must exit non-zero on findings, not just log. `lint-prohibited-language.ts` must not whitelist its own target phrases — re-discuss which phrases are really allowed with CONTENT_GUIDELINES and remove the `APPROVED_EXCEPTIONS` escape hatch, OR explicitly rewrite CG-3 to permit them and update `content-audit-log.md` to match. | [lint-i18n-externalization.ts](../../src/frontend/scripts/lint-i18n-externalization.ts), [lint-prohibited-language.ts](../../src/frontend/scripts/lint-prohibited-language.ts), CONTENT_GUIDELINES, content-audit-log.md | small |
| P2.6 | Implement the responsive layouts that S07-06 claims: tablet collapsible bottom panel and mobile bottom sheet. [Sidebar.tsx:39-43](../../src/frontend/src/app/components/assessment/Sidebar.tsx#L39-L43) is currently a fixed 280 px column at every breakpoint. | Sidebar.tsx + CSS | medium |
| P2.7 | Re-run axe-core against desktop / tablet / mobile on the now-running app and regenerate `a11y-audit-report.md` from the new run instead of shipping the earlier desktop-only snapshot. | [a11y-audit-report.md](artifacts/a11y-audit-report.md) | small |

### Phase 3 — "Make it production-acceptable" (optional, depends on target)

This phase is only needed if the target is a public Azure release. For a pure portfolio/local demo it can be skipped, but it should be acknowledged as "known deferred".

| # | Task | Files | Estimate | Target |
|---|---|---|---|---|
| P3.1 | Implement `AzureMapsGeocodingClient : IGeocodingService` per ADR-019. Register it behind a config switch (`Geocoding:Provider = azure-maps | nominatim`). Keep Nominatim as the dev-only adapter so local demos do not need a subscription key. Add an ADR addendum explaining the dual setup. | new file in Infrastructure/Clients, [Program.cs:70-75](../../src/api/SeaRise.Api/Program.cs#L70-L75) | medium | Azure release, ADR-019 honesty |
| P3.2 | Close the remaining S08-06 items: HTTPS enforcement, Key Vault `secretref`, TiTiler CORS, CORS staging verification. Strip the ROADMAP's "HSTS pending Azure" note — HSTS already ships. | Program.cs, infra scripts | medium | Azure release |
| P3.3 | Wave 8 as originally scoped (Provisioning / CI/CD / COG upload / NFR checks / release readiness). Only worth starting after Phase 1 is done — otherwise we'd be shipping `UnsupportedGeography` to Azure. | new infra + pipelines | large | Azure release |
| P3.4 | Pin pipeline Python dependencies in [src/pipeline/pyproject.toml](../../src/pipeline/pyproject.toml) so `pytest` stops breaking on collection when a new `numpy` ships. Not blocking any wave, but blocking any honest CI claim. | pyproject.toml | trivial | Hygiene |

### Hard dependency graph

```
P0.1 (curl)  ─┐
              ├─► P0.3 (compose smoke CI) ──► Phase 1 can be verified at all
P0.2 (port)  ─┘

P1.1 (europe geojson) ──► P1.2 (coastal geojson) ──► P1.3 or P1.4 (wiring) ──► non-UnsupportedGeography results
                                                                            │
P0.2 (tiler port) ──────────────────────────────────────────► P1.5 (layers) ┘ ──► ModeledExposureDetected possible

P1.6 (methodology UI rewrite) ──► P1.7 (contract test)     (can run in parallel with P1.1–P1.5)

Phase 2 items are mostly independent of each other and can be parallelized once Phase 1 is done.
Phase 3 is gated on Phase 1 — Azure without real geometries would be worse than local without Azure.
```

### Definition of "Honest Local MVP" (exit bar)

The application reaches "honest local MVP" status when **all of the following are simultaneously true on a fresh `docker compose up --build`:**

1. All five containers reach `healthy` state; compose does not exit.
2. The frontend at `http://localhost:3000` renders without errors.
3. Searching for "Amsterdam" returns at least one candidate.
4. Selecting the top candidate returns `ModeledExposureDetected` under `ssp5-85` / 2100 **and** `NoModeledExposureDetected` under `ssp1-26` / 2030 (or similar — the point is non-`UnsupportedGeography`).
5. Searching for "Prague" returns `OutOfScope` (inland, but inside europe).
6. Searching for "New York" returns `UnsupportedGeography`.
7. The methodology drawer opens and renders every section without a TypeError.
8. At least one scenario × horizon combination has a real legend, and the raster exposure layer renders over the map.
9. `npm run lint` and the prohibited-language scanner do not have whitelists that cover their own target strings.
10. No user-facing string is hardcoded outside `en.ts`.

Anything beyond this list (Azure, CI/CD, full a11y audit, NFR verification) is Phase 3 and should be called "post-MVP" until Phase 1 is demonstrably done.

### Order I would execute this in

If I were doing this solo tomorrow morning with no existing context: **P0.1 → P0.2 → P0.3 → P1.1 → P1.4 → P1.6 → P1.7 → P1.5 → P2.1 → P2.4 → P2.5 → P2.6 → P2.7 → P2.2 → P2.3**, then revisit Phase 3.

Rationale: P0 first because nothing else can be verified. Within Phase 1, use the "bake geometries into init.sql" shortcut (P1.4) before tackling the real pipeline run (P1.5) — that gets to `OutOfScope`/non-UnsupportedGeography fastest. Methodology rewrite (P1.6) happens in parallel because it does not depend on geometry. Full `layers` seed (P1.5) is the biggest item and sits later because everything else can be verified before real COGs exist. Phase 2 UX items are mostly independent so order them by visible impact.

---

## What This Audit Does Not Cover

- Azure staging environment (Wave 8) is out of scope — ROADMAP already marks it as planned.
- Performance NFRs (NFR-001 shell load ≤4s, NFR-003 p95 ≤3.5s) were not measured; they require the full Docker stack and real data.
- Security review beyond the S08-06 header snapshot.
- Cross-browser compatibility and real-device a11y testing.
- Accuracy of the scientific methodology itself — this audit assumes ADR-015 is correct and only checks whether it is implemented as stated.
