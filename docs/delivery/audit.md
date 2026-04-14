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

## Progress Update — 2026-04-13 (post-audit execution)

Between the audit ("2026-04-13 morning") and this update ("2026-04-14 late evening"), a subset of the re-plan was executed in four blocks. An earlier version of this section overstated progress; the table below is the corrected status after direct file and test verification, including the **Block A + Block B + Block C + Block D** work from the late-evening sessions on 2026-04-13 and 2026-04-14.

**Block A — regression + documentation honesty (complete):**
- **P1.5 regression fixed.** [TestDbFixture.cs:174](../../src/api/SeaRise.Api.Tests/Integration/TestDbFixture.cs#L174) now uses `INSERT ... ON CONFLICT (scenario_id, horizon_year, methodology_version) DO NOTHING`. `dotnet test --filter Category=Integration` → **26 passed / 0 failed** (previously 14 passed / 12 failed). Wave 4 is green again.
- **ROADMAP.md drift corrected.** Added a prominent audit notice ([ROADMAP.md:9-17](ROADMAP.md#L9)), reclassified Wave 3 and Wave 7 as **PARTIAL** in both the wave bar and the epic completion table, dropped the "HSTS pending Azure" clause from S08-06 (HSTS is already emitted by both [Program.cs:177](../../src/api/SeaRise.Api/Program.cs#L177) and `next.config.js`), flagged the S01-05 Nominatim / Azure Maps drift, and updated the test totals line to 145 (39 .NET unit + 26 .NET integration + 80 frontend vitest).

**Block B — Phase 2 tail (complete):**
- **P2.4 completed.** `SearchBar.tsx` clear button now uses `strings.search.clearLabel` for both `title` and `aria-label`; the string lives at [en.ts:109](../../src/frontend/src/lib/i18n/en.ts#L109).
- **P2.5a completed — lint scanner rewritten.** [lint-i18n-externalization.ts](../../src/frontend/scripts/lint-i18n-externalization.ts) now scans **every** `.tsx` file (no more "skip if file imports `strings`" bypass), and additionally scans user-facing HTML attributes (`title=`, `aria-label=`, `aria-description=`, `alt=`, `placeholder=`). The new scanner immediately flagged one pre-existing hit — `Legend.tsx aria-label="Map legend"` — which has been externalized to `strings.accessibility.legendLabel`.
- **P2.5b completed — `PROHIBITED_TERMS` reconciled with content-audit-log.md.** The term list grew from 12 to 18 entries, adding `no risk`, `100%`, `certain`, `definite`, `proven`, `absolute`. Word-boundary matching was added for single-word bans so `certain` does not false-positive on `uncertainty`. `APPROVED_EXCEPTIONS` remains deleted. With the expanded list, `en.ts:34` and `en.ts:35` had to be rewritten: `"Risk detected"` → `"Modeled exposure detected"`, `"No risk detected"` → `"No modeled exposure"`. These satisfy CG-3 (no alarmist framing, no false assurance) and pass the scanner.
- **P2.7 completed — focus restoration implemented.** [MethodologyPanel.tsx:14-30](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L14-L30) captures `document.activeElement` on mount and restores focus to it in the effect's cleanup function. The loading and error strings (previously hardcoded `"Loading methodology…"` and `"Could not load methodology information…"`) are now `strings.methodology.loading` and `strings.methodology.error`. [a11y-audit-report.md](artifacts/a11y-audit-report.md) has been dated `2026-04-13` and a "Changes since the 2026-04-03 version" section explicitly calls out the focus-restoration fix, the contrast fix, the headline rewrites, and the Legend/SearchBar a11y externalization. The report is no longer contradicted by the code.

**Block C — infra hygiene (complete):**
- **P0.3 completed — compose smoke CI job added.** New script [scripts/compose-smoke.sh](../../scripts/compose-smoke.sh) runs `docker compose up -d --wait --wait-timeout 240 --build`, then probes `api /health`, `frontend /api/health`, and `tiler /healthz` with `curl -w '%{http_code}'`, failing fast on any non-2xx. On failure it dumps `docker compose ps` and `logs --tail=80` for diagnosis before teardown. A new `compose-smoke` job in [.github/workflows/ci.yml:164-174](../../.github/workflows/ci.yml#L164-L174) runs after `frontend`, `api`, `docker-build`, and `docker-build-tiler`, so the full stack is health-gated on every PR. **Verified end-to-end locally:** `WAIT_TIMEOUT=300 bash scripts/compose-smoke.sh` brought up all 5 services to `Healthy` and all 3 probes returned `200 OK`. This is the regression guard that would have caught P0.1 (missing `curl`) and P0.2 (tiler port drift) in minutes.
- **P3.4 completed — pipeline Python deps pinned.** [src/pipeline/pyproject.toml](../../src/pipeline/pyproject.toml) and [src/pipeline/requirements-pipeline.txt](../../src/pipeline/requirements-pipeline.txt) now pin every runtime and dev dependency with both lower **and** upper bounds (`numpy>=1.26,<2.0`, `xarray>=2024.1,<2025.0`, `rasterio>=1.3,<2.0`, `rio-cogeo>=5.0,<6.0`, `netcdf4>=1.6,<2.0`, `shapely>=2.0,<3.0`, `geopandas>=0.14,<2.0`, `psycopg2-binary>=2.9,<3.0`, `azure-storage-blob>=12.19,<13.0`, plus `pytest<9`, `ruff<1`, `mypy<2`). Upper bounds exist specifically to block the NumPy 2.0 / xarray collection failure the audit observed. **Verified end-to-end:** fresh venv on Python 3.12 → `pip install -e ".[dev]"` resolved to `numpy 1.26.4` + `xarray 2024.11.0` → `pytest tests/ -q` → **36 / 36 passed in 33.34s**. Pipeline CI collection is no longer blocked.

**Block D — real geometries (complete):**
- **P1.1 completed — [data/geometry/europe.geojson](../../data/geometry/europe.geojson) (164 KB).** Built from `ne_10m_admin_0_countries.shp` (Natural Earth 1:10m, public domain). Filter: `CONTINENT == 'Europe' AND NAME != 'Russia'` → 50 countries. Processing: `intersection(bbox(-30,30,45,75))` to drop French overseas departments, `unary_union`, `buffer(0.02)` to pad coasts, `simplify(0.02)`, `make_valid`, round coordinates to 4 decimals. Resulting MultiPolygon has 237 parts, 9,181 PostGIS-counted points, and is `ST_IsValid = true`. Containment verified for 15 points: Amsterdam / Barcelona / Copenhagen / Lisbon / Venice / Prague / Zurich / Vienna / Munich / Bratislava / Reykjavik / Malta are IN; New York / Moscow / Istanbul are OUT.
- **P1.2 completed — [data/geometry/coastal_analysis_zone.geojson](../../data/geometry/coastal_analysis_zone.geojson) (184 KB).** Local approximation of Copernicus Coastal Zones 2018 (the canonical source sits behind an EEA login and cannot be downloaded non-interactively). Built from `ne_10m_ocean.shp` ∪ `europe.geojson`: reproject ocean to EPSG:3035 (ETRS89 / LAEA Europe), `buffer(25_000)` in metric space, intersect with europe, reproject back to EPSG:4326, `simplify(0.02)`, round to 4 decimals. **Why 25 km and not the Copernicus 10 km:** Natural Earth 10m ocean is too coarse to model estuaries and tidal waterways (Rotterdam measures ~24 km from the nearest NE ocean edge even though it is a major maritime port). 25 km is the smallest buffer that correctly includes Amsterdam and Rotterdam while keeping Utrecht (~50 km), Berlin (~143 km), and all inland capitals out. Rationale documented in [data/geometry/README.md](../../data/geometry/README.md). Containment verified for 16 points.
- **P1.3 completed — pipeline wired to europe.geojson.** Added `get_europe_path()` at [src/pipeline/config.py:75](../../src/pipeline/config.py#L75); threaded through [run_pipeline.py:121](../../src/pipeline/run_pipeline.py#L121) and [run_pipeline.py:135](../../src/pipeline/run_pipeline.py#L135) so `seed_all(...)` now receives both `coastal_zone_geojson` and `europe_geojson`. `register.seed_geography_boundaries` already accepted `europe_geojson` since Epic 03; this completes the previously-dangling half. **Pipeline pytest: 36 / 36 passed** after the wiring change.
- **P1.4 completed — init.sql replaced; TestDbFixture repaired.** The synthetic bbox INSERTs at the old [infra/db/init.sql:183-203](../../infra/db/init.sql#L183) are gone. Real geometries now load through a new [infra/db/init-geography.sql](../../infra/db/init-geography.sql) file which uses `\set europe_geojson `cat /geometry/europe.geojson`` + `ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON((:'...'::jsonb -> 'features' -> 0 -> 'geometry')::text), 4326))` to inline the GeoJSON files mounted at `/geometry/`. [docker-compose.yml:105-107](../../docker-compose.yml#L105-L107) mounts `init.sql` → `01-init.sql` and `init-geography.sql` → `02-init-geography.sql` so the postgres entrypoint runs schema first, geography second. The split was required because `TestDbFixture.cs` executes init.sql through **Npgsql**, which is a plain SQL driver and does not understand psql meta-commands; keeping `\set` out of `init.sql` lets the fixture continue to read schema + scenarios + horizons + methodology + layers via Npgsql and seed its own synthetic bbox geometries afterward. [TestDbFixture.cs:146-186](../../src/api/SeaRise.Api.Tests/Integration/TestDbFixture.cs#L146-L186) was also flipped from `UPDATE` to `INSERT ... ON CONFLICT (name) DO UPDATE` because init.sql no longer pre-seeds the geography rows.

**Runtime Reality Check vs. Block D (the centerpiece of this update):**
Before Block D, the live `/v1/assess` endpoint returned **only `UnsupportedGeography`** for every real-world query because both bboxes were coarse synthetic rectangles that no Europe-specific containment logic could differentiate. After a clean `docker compose down -v && compose-smoke.sh` cycle with only the committed files, six representative cities produced **four distinct result states** for the first time:

| City | Lat, Lon | Result state (before) | Result state (after Block D) |
|---|---|---|---|
| Amsterdam | 52.37, 4.90 | UnsupportedGeography | **ModeledExposureDetected** |
| Barcelona | 41.39, 2.17 | UnsupportedGeography | **ModeledExposureDetected** |
| Munich | 48.14, 11.58 | UnsupportedGeography | **OutOfScope** |
| Prague | 50.08, 14.43 | UnsupportedGeography | **OutOfScope** |
| New York | 40.71, -74.01 | UnsupportedGeography | **UnsupportedGeography** (correct) |
| Reykjavik | 64.15, -21.94 | UnsupportedGeography | **NoModeledExposureDetected** |

Reykjavik landing on `NoModeledExposureDetected` is emergent and correct: it sits in Europe **and** in the coastal zone, but the synthetic demo COG from the `blob-seed` container does not cover Iceland at longitude -21.94, so the raster lookup returns 0 and the evaluator correctly classifies it as "no modeled exposure." The `DataUnavailable` state is still reserved for the `(ssp5-85, 2100)` layer row which is deliberately marked `layer_valid = false` by init.sql. All five documented result states (`ModeledExposureDetected`, `NoModeledExposureDetected`, `DataUnavailable`, `OutOfScope`, `UnsupportedGeography`) are now reachable in the live local stack.

**Verification after Blocks A + B + C + D:**
- `dotnet test --filter Category=Integration` → **26 / 26 passed** (Wave 4 regression from P1.5 is gone).
- `dotnet test --filter Category=Unit` → **39 / 39 passed**.
- `npx tsc --noEmit` → clean.
- `npm run lint` → 0 warnings, 0 errors.
- `npx tsx scripts/lint-i18n-externalization.ts` → **passes with the tightened scanner** (no more blind spots on `title=` attributes or files-importing-`strings`).
- `npx tsx scripts/lint-prohibited-language.ts` → **passes with 18 terms** (previously 12).
- `npx vitest run` → **14 files / 80 tests passed**.
- `WAIT_TIMEOUT=300 bash scripts/compose-smoke.sh` → all 5 services `Healthy`, all 3 probes `200 OK`, clean teardown.
- `pytest src/pipeline/tests/ -q` (fresh venv, pinned deps) → **36 / 36 passed in 33.34s** (NumPy 2.0 collection failure gone).

---

### Earlier state, corrected — the table below is the status *before* Blocks A + B, kept for traceability against the earlier narrative.

| # | Task | Status | Notes |
|---|---|---|---|
| P0.1 | API Dockerfile `curl` install | ✅ Done | `curl` installed in runtime image; container reaches `healthy`. |
| P0.2 | TiTiler port mapping | ✅ Done | `docker-compose.yml` aligned so exposure evaluator can actually reach the tiler. |
| P0.3 | Compose smoke CI step | ✅ Done (completed in Block C) | [scripts/compose-smoke.sh](../../scripts/compose-smoke.sh) + new `compose-smoke` job at [.github/workflows/ci.yml:164-174](../../.github/workflows/ci.yml#L164-L174). Verified end-to-end locally: 5/5 services `Healthy`, 3/3 probes `200 OK`. Regressions of the P0.1 / P0.2 class are now CI-gated. |
| P1.1 | `europe.geojson` | ✅ Done (Block D) | [data/geometry/europe.geojson](../../data/geometry/europe.geojson) (164 KB) committed. Dissolved Natural Earth 1:10m Admin 0 countries, continent=Europe minus Russia, clipped to (-30,30,45,75). 237 MultiPolygon parts, 9,181 PostGIS-counted points, `ST_IsValid = true`. 15-point containment verified. |
| P1.2 | `coastal_analysis_zone.geojson` | ✅ Done (Block D) | [data/geometry/coastal_analysis_zone.geojson](../../data/geometry/coastal_analysis_zone.geojson) (184 KB) committed. Local approximation of Copernicus Coastal Zones 2018: europe ∩ 25 km metric buffer of `ne_10m_ocean` in EPSG:3035. 25 km chosen to compensate for NE 10m coarseness; rationale in [data/geometry/README.md](../../data/geometry/README.md). 16-point containment verified. Still needs to be replaced by canonical Copernicus Coastal Zones 2018 when that data becomes accessible. |
| P1.3 | Pipeline wiring (`europe_geojson` through `run_pipeline.py`) | ✅ Done (Block D) | `get_europe_path()` added at [src/pipeline/config.py:75](../../src/pipeline/config.py#L75); threaded through `run_pipeline.py` at [line 121](../../src/pipeline/run_pipeline.py#L121) and [line 135](../../src/pipeline/run_pipeline.py#L135) so `seed_all(...)` now passes both `coastal_zone_geojson` and `europe_geojson`. Pipeline pytest: **36 / 36 passed**. |
| P1.4 | Bake real geometries into `init.sql` | ✅ Done (Block D) | Synthetic bboxes at the old [infra/db/init.sql:183-203](../../infra/db/init.sql#L183) removed; replaced by a second seed file [infra/db/init-geography.sql](../../infra/db/init-geography.sql) which uses `\set europe_geojson \`cat /geometry/europe.geojson\`` + `ST_GeomFromGeoJSON(...)` to inline the GeoJSON files mounted at `/geometry/`. [docker-compose.yml:105-107](../../docker-compose.yml#L105-L107) mounts both files as `01-init.sql` / `02-init-geography.sql` so the postgres entrypoint runs schema first, geography second. The split was required because `TestDbFixture.cs` executes init.sql through **Npgsql**, which does not understand psql meta-commands; [TestDbFixture.cs:146-186](../../src/api/SeaRise.Api.Tests/Integration/TestDbFixture.cs#L146-L186) was flipped from `UPDATE` to `INSERT ... ON CONFLICT (name) DO UPDATE` to seed its own synthetic bboxes after the schema loads. |
| P1.5 | Seed `layers` table | ✅ Done (regression closed in Block A) | Seed itself was done earlier; the Block A fix at [TestDbFixture.cs:174](../../src/api/SeaRise.Api.Tests/Integration/TestDbFixture.cs#L174) added `ON CONFLICT (scenario_id, horizon_year, methodology_version) DO NOTHING`, which restored Wave 4 to **26 / 26 integration tests passing**. The row is still synthetic data — real layer pointers depend on P1.1–P1.4. |
| P1.6 | MethodologyPanel API contract rewrite | ✅ Done | Frontend types + panel aligned to real `/v1/config/methodology` shape. Verified by P1.7 contract test. |
| P1.7 | Methodology contract test | ✅ Done | `src/frontend/src/__tests__/api/methodology.contract.test.ts` with live fixture + runtime validator (5 cases, all passing). |
| P2.1 | MapSurface click-to-assess early return | ✅ Done | Removed; fresh map click starts a new assessment when `selectedLocation` is null. |
| P2.2 | Assessment `staleTime` reconciliation | ✅ Done | Code now uses `60_000` to match ROADMAP S06-02 and `06-assessment-ux.md` lines 249/267/274. |
| P2.3 | Geocoding `useMutation` → `useQuery` | ✅ Done | `useGeocodeQuery` with cache key `['geocode', normalized]` and `staleTime: 5 * 60 * 1000`; SearchOverlay drives the phase machine via an effect. Verified end-to-end in Playwright: re-submitting "Amsterdam" returned the cached 5 candidates with **0 new `/v1/geocode` calls**. |
| P2.4 | Hardcoded user-facing strings → `en.ts` | ✅ Done (completed in Block B) | `title="Clear search"` externalized to `strings.search.clearLabel` at [SearchBar.tsx:82-83](../../src/frontend/src/app/components/search/SearchBar.tsx#L82-L83), now bound to both `title` and `aria-label`. Two more hardcoded strings discovered during the Block B lint tightening — `Legend.tsx aria-label="Map legend"` and `MethodologyPanel.tsx` loading/error messages — were also externalized. |
| P2.5 | Lint gates actually fail | ✅ Done (completed in Block B) | Both gates are now actually tight. (a) `lint-i18n-externalization.ts` was rewritten to scan every `.tsx` file (no "file-imports-strings" bypass) and additionally scans user-facing HTML attributes (`title`, `aria-label`, `aria-description`, `alt`, `placeholder`) — immediately flagged one real pre-existing issue in `Legend.tsx` which was fixed. (b) `lint-prohibited-language.ts` grew from 12 to **18** terms (adding `no risk`, `100%`, `certain`, `definite`, `proven`, `absolute`), added word-boundary matching so single-word bans don't false-positive on `uncertainty`. `en.ts:34-35` rewritten: `"Risk detected"` → `"Modeled exposure detected"`, `"No risk detected"` → `"No modeled exposure"`. Both scanners pass. |
| P2.6 | Responsive tablet/mobile layouts | ✅ Done | `AppShell` main-content uses `flex-col-reverse lg:flex-row`; Sidebar is `w-full max-h-[50vh]` below `lg` and `w-[280px]` at `lg+`; ResultPanel clamps to `w-[calc(100vw-3rem)] max-w-[320px]` below `lg`. Verified in Playwright at 375 / 768 / 1280. |
| P2.7 | Axe-core re-run on running app + focus restoration | ✅ Done (completed in Block B) | Focus restoration actually implemented: [MethodologyPanel.tsx:14-30](../../src/frontend/src/app/components/assessment/MethodologyPanel.tsx#L14-L30) now stores `document.activeElement` on mount in `previouslyFocusedRef` and calls `previouslyFocusedRef.current?.focus()` in the effect's cleanup, so Escape/close returns focus to the trigger that opened the drawer. [a11y-audit-report.md](artifacts/a11y-audit-report.md) re-dated to `2026-04-13` with an explicit "Changes since the 2026-04-03 version" section listing the focus-restoration fix, the disclaimer contrast fix (earlier in the session), the result-state headline rewrites, and the Legend/SearchBar a11y externalization. The earlier axe-core contrast fix (EmptyState disclaimer `text3 → text2`) was already in place from the morning session. |

**Status of the earlier corrections (after Blocks A + B + C + D):**
1. **P1.1–P1.4 — all closed in Block D.** Real `europe.geojson` (164 KB, 237 parts, 9,181 npoints) and `coastal_analysis_zone.geojson` (184 KB) are committed under `data/geometry/`; `run_pipeline.py` wires both through `seed_all(...)`; `init.sql` has been split and the new `init-geography.sql` loads real geometries via `\set` + `ST_GeomFromGeoJSON`. `ST_IsEmpty` is `false` for both rows in a clean `docker compose up` build. "R3–R5" of the Runtime Reality Check no longer applies: six cities now produce four distinct result states on a cold boot (Amsterdam / Barcelona `ModeledExposureDetected`, Munich / Prague `OutOfScope`, Reykjavik `NoModeledExposureDetected`, New York `UnsupportedGeography`).
2. **P1.5 — closed in Block A.** `TestDbFixture.cs:174` now uses `ON CONFLICT DO NOTHING`. Integration suite: **26 / 26 passing**.
3. **P2.4 — closed in Block B.** `SearchBar.tsx` clear button now uses `strings.search.clearLabel` for both `title` and `aria-label`.
4. **P2.5 — closed in Block B.** `PROHIBITED_TERMS` now has all 18 entries with word-boundary matching; `lint-i18n-externalization.ts` was rewritten to scan attributes and every `.tsx` file; `en.ts:34-35` result-state headlines rewritten to "Modeled exposure detected" / "No modeled exposure".
5. **P2.7 — closed in Block B.** `MethodologyPanel.tsx` now captures and restores focus via `previouslyFocusedRef`; `a11y-audit-report.md` re-dated and annotated with a changelog.

**Still outstanding after Blocks A + B + C + D:**
- **Block E / Phase 3** — P3.1 Azure Maps geocoder (Program.cs still registers Nominatim), P3.2 Key Vault / HTTPS enforcement / TiTiler CORS for staging, P3.3 Wave 8 cloud items (provisioning, CI/CD, COG upload, NFR checks, release readiness). These are gated on Azure target and are explicitly post-MVP for a local demo.
- **Canonical Copernicus Coastal Zones 2018.** The committed coastal zone is a local 25 km approximation derived from `ne_10m_ocean`. The canonical ADR-018 source sits behind an EEA login and could not be downloaded non-interactively; replacing the approximation with the canonical data is a separate follow-up item tracked in [data/geometry/README.md](../../data/geometry/README.md).
- **Real IPCC AR6 + Copernicus DEM pipeline output.** The live stack now differentiates result states using the synthetic demo COG produced by the `blob-seed` container. Running the full pipeline end-to-end against real NASA / Copernicus inputs and re-seeding `layers` remains future work (it does not block the Honest Local MVP exit bar because the exit bar only requires that the result states are reachable, not that the raster itself is scientifically calibrated).

**Verification at time of this update (post Blocks A + B + C + D):**
- `npm run lint` — 0 warnings, 0 errors.
- `npx tsx scripts/lint-prohibited-language.ts` — **passes with the tightened 18-term list and word-boundary matching.**
- `npx tsx scripts/lint-i18n-externalization.ts` — **passes with the rewritten scanner** (scans every `.tsx`, scans `title`/`aria-label`/`aria-description`/`alt`/`placeholder` attributes).
- `npx tsc --noEmit` — clean.
- `npx vitest run` — **14 files / 80 tests passed** (frontend).
- `dotnet test --filter Category=Unit` — **39 / 39 passed**.
- `dotnet test --filter Category=Integration` — **26 / 26 passed** against the post-Block-D split `init.sql` + `init-geography.sql` (Npgsql still parses schema + reference data cleanly; fixture seeds its own synthetic bboxes via `INSERT ... ON CONFLICT`).
- `pytest src/pipeline/tests/ -q` — **36 / 36 passed in 33.34s** after the Block C pin (`numpy 1.26.4`, `xarray 2024.11.0`). Collection failure is gone.
- `docker compose down -v --remove-orphans && WAIT_TIMEOUT=300 bash scripts/compose-smoke.sh` — **all 5 services `Healthy`, 3/3 probes `200 OK`**, clean teardown. Fresh volume exercised the new `02-init-geography.sql` entrypoint.
- `SELECT name, ST_IsValid(geom), ST_NPoints(geom) FROM geography_boundaries;` against the running Postgres → `europe | t | 9181`, `coastal_analysis_zone | t | 10266`. Both rows are real MultiPolygons; `ST_IsEmpty` is `false` for both.
- Six-city `/v1/assess` probe against the running API → **4 distinct result states** (see the Reality Check table above).

The "Honest Local MVP" exit bar at the bottom of this document is **now met on the engineering side** for every item that does not require a public cloud environment:
- **Items 1–3** — compose up reaches all-healthy; frontend renders; "Amsterdam" returns candidates. (Unchanged from Block C; verified again after Block D against a clean volume.)
- **Items 4–6** — `ModeledExposureDetected` / `NoModeledExposureDetected` / `OutOfScope` / `UnsupportedGeography` are all reachable for real cities now that `europe` and `coastal_analysis_zone` carry real geometries. Reykjavik exercises `NoModeledExposureDetected` as an emergent result (inside europe, inside the coastal zone, but the synthetic demo COG does not cover Iceland at -21.94). `DataUnavailable` remains reserved for the `(ssp5-85, 2100)` layer row which `init.sql` deliberately marks `layer_valid = false`.
- **Item 7** — methodology drawer renders every section without a TypeError (Block B / earlier session).
- **Item 8** — at least one scenario × horizon combination returns a real result with a real legend-compatible raster through the live tiler (verified by the `ModeledExposureDetected` responses above; the raster is the synthetic demo COG, which is documented behavior until the full pipeline is run).
- **Items 9–10** — lint gates are tight and no user-facing string lives outside `en.ts` (Block B).

The only remaining paths explicitly called "post-MVP" in this audit are **Phase 3** (Azure Maps geocoder, Key Vault / HTTPS enforcement, Wave 8 cloud deployment) and the two data-quality follow-ups noted in "Still outstanding" above (canonical Copernicus Coastal Zones 2018 and a real IPCC AR6 / Copernicus DEM pipeline run).

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
