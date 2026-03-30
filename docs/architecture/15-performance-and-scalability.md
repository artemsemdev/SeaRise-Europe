# 15 — Performance and Scalability

> **Status:** Proposed Architecture
> **References:** NFR-001 (shell 4s), NFR-002 (geocoding 2.5s), NFR-003 (assessment 3.5s), NFR-004 (control switch 1.5s), NFR-012 (99.5% availability), NFR-018 (concurrent users target)

---

## 1. Performance Targets

| NFR | Target | Measurement Point | Notes |
|---|---|---|---|
| NFR-001 | First meaningful paint ≤ 4s (cold load) | Browser — LCP | Includes DNS, TLS, server, JS hydration |
| NFR-002 | Geocoding response ≤ 2.5s p95 | Browser — network | Round trip to `/v1/geocode` |
| NFR-003 | Full assessment ≤ 3.5s p95 | Browser — network | Round trip to `/v1/assess` (includes DB + TiTiler) |
| NFR-004 | Control switch re-assessment ≤ 1.5s p95 (cached) | Browser | From cached TanStack Query result |
| NFR-012 | 99.5% monthly uptime | Azure Monitor availability | Excludes planned maintenance |
| NFR-018 | ≥ 10 concurrent users without degradation | Load test | Portfolio demo scale |

---

## 2. Latency Budget — Full Assessment (NFR-003: 3.5s)

The assessment endpoint is the most latency-sensitive path. It involves: network, validation, two DB round-trips, one TiTiler call, and response serialization.

```
Browser → API (network, TLS overhead)                ~50ms
API: request parsing + FluentValidation               ~5ms
API → PostgreSQL: ST_Within europe check              ~20ms   (GIST indexed)
API → PostgreSQL: ST_Within coastal zone check        ~20ms   (GIST indexed)
API → PostgreSQL: layer lookup                        ~10ms   (composite index)
API → TiTiler: GET /point/{lng},{lat}?url={...}      ~200ms  (warm COG, VSI cache hit)
  └── TiTiler → Azure Blob: GDAL range request        [included in above]
API: result assembly + JSON serialization             ~5ms
API → Browser: response transmission                  ~50ms
                                                     ────────
TOTAL (warm path, p50 estimate)                      ~360ms
BUDGET REMAINING for p95 variance                   ~3140ms
p95 target                                          ≤ 3500ms
```

**Key observation:** TiTiler point query latency is the dominant variable. A warm COG with VSI cache hit delivers ~100–200ms. A cold query (first range request from Azure Blob) can be 500ms–1s.

**Risk:** Cold TiTiler start (scale-from-zero) adds 10–20s for the first request. See Risk R-03 in [12-risks-assumptions-and-open-questions.md](12-risks-assumptions-and-open-questions.md).

---

## 3. Latency Budget — Geocoding (NFR-002: 2.5s)

```
Browser → API (network)                              ~50ms
API: request parsing + validation                    ~5ms
API → Geocoding provider (external HTTPS)           ~500–1500ms  (provider-dependent)
API: candidate normalization + truncation            ~2ms
API → Browser (response)                            ~50ms
                                                   ─────────
TOTAL (typical)                                    ~600–1600ms
p95 target                                         ≤ 2500ms
```

**Risk:** Geocoding provider latency is the dominant uncertainty. European providers (HERE, Mapbox) typically respond in 200–500ms. Nominatim (dev only) varies 100ms–3s.

---

## 4. Latency Budget — Control Switch (NFR-004: 1.5s from cache)

When a scenario or horizon change hits the TanStack Query cache (60s staleTime):

```
User interaction → React state update               ~5ms
TanStack Query: cache hit check                     ~1ms
TanStack Query: return cached AssessmentResult      ~1ms
React: re-render ResultPanel with new result        ~10ms
MapLibre: update ExposureLayer tile URL             ~20ms
MapLibre: fetch new tiles (3–6 tiles at zoom 12)   ~200–800ms  (network + TiTiler rendering)
                                                   ─────────
TOTAL (cache hit, warm tiles)                      ~250–850ms
p95 target (cache)                                 ≤ 1500ms
```

**Note:** If the cache miss occurs (first time viewing SSP5 / 2100, or after 60s), the full assessment flow runs (~360ms–3500ms). NFR-004's 1.5s target applies specifically to the cached case.

---

## 5. Frontend Performance Strategy

### 5.1 Bundle Size Targets

| Bundle | Target | Notes |
|---|---|---|
| Initial JS (critical path) | ≤ 150 KB gzipped | AppShell, SearchBar, config fetch |
| MapLibre + deck.gl | Deferred (dynamic import) | ~500 KB total; loaded after shell mounts |
| MethodologyPanel | Deferred (dynamic import) | Only loaded on first open |
| Total JS | ≤ 800 KB gzipped | Measured by Next.js bundle analyzer |

### 5.2 Critical Rendering Path

```
1. Next.js Server Component renders AppShell HTML + critical CSS (inline)
2. Browser receives HTML → LCP (map placeholder / EmptyState visible)
3. Browser fetches JS bundles (non-render-blocking for MapLibre)
4. React hydrates → GET /v1/config/scenarios fires
5. Config cached → ScenarioControl + HorizonControl rendered
6. MapLibre dynamic import resolves → map initialises, Europe view shown
```

Steps 1–5 target completion within 4s (NFR-001).

### 5.3 Image and Asset Optimization

- Next.js `<Image>` component for any static images (automatic WebP, lazy loading)
- SVG icons preferred over raster for UI elements
- No large static assets on critical path

### 5.4 Tile Loading Performance

Map tile performance depends on:
1. **COG quality** — correct overview levels; incorrect tiling = slow tile generation by TiTiler
2. **Azure Blob proximity** — tiles served from West Europe region; latency is low for EU users
3. **TiTiler VSI cache** — `VSI_CACHE_SIZE=50MB` keeps recently-read COG byte ranges in memory
4. **MapLibre tile batching** — MapLibre requests 3–12 tiles per viewport change; TiTiler handles these in parallel

### 5.5 Web Vitals Targets

| Metric | Target | Measured By |
|---|---|---|
| LCP (Largest Contentful Paint) | ≤ 4s | Playwright + Lighthouse CI |
| FID / INP | ≤ 200ms | Real User Monitoring (if analytics enabled) |
| CLS (Cumulative Layout Shift) | ≤ 0.1 | Playwright |
| TTFB | ≤ 800ms | Azure CDN (Phase 3) or Container Apps |

---

## 6. Backend Performance Strategy

### 6.1 Database Query Optimization

**All critical queries use indexes:**

```sql
-- Geography boundary lookups: GIST index (created in 05-data-architecture.md)
CREATE INDEX geography_boundaries_geom_idx ON geography_boundaries USING GIST(geom);

-- Layer lookup: composite partial index on valid layers only
CREATE INDEX layers_lookup_idx ON layers (scenario_id, horizon_year, methodology_version)
    WHERE layer_valid = true;
```

**No ORM — direct Npgsql queries:**
- Dapper or raw Npgsql for all queries
- No Entity Framework Core (avoids N+1 query generation and hidden query complexity)
- Query plans are predictable and inspectable

### 6.2 In-Process Memory Cache

Scenario and methodology config rarely changes. The API caches this data in-process:

```csharp
services.AddMemoryCache();

// In IScenarioRepository implementation:
public async Task<IReadOnlyList<Scenario>> GetAllAsync(CancellationToken ct)
{
    return await _cache.GetOrCreateAsync("scenarios", async entry =>
    {
        entry.AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(5);
        return await _db.QueryAsync<Scenario>("SELECT * FROM scenarios ORDER BY sort_order");
    }) ?? [];
}
```

This eliminates DB round-trips for scenario config on every `/v1/assess` request.

### 6.3 Assessment Pipeline Optimization

The assessment pipeline makes sequential DB calls. Optimization options:

**Current (sequential):**
```
Europe check (20ms) → Coastal zone check (20ms) → Layer lookup (10ms) → TiTiler (200ms)
Total DB: ~50ms
```

**Optimization (parallel geography checks):**
```csharp
var europeTask = _geoRepo.IsWithinEuropeAsync(lat, lng, ct);
var coastalTask = _geoRepo.IsWithinCoastalZoneAsync(lat, lng, ct);
await Task.WhenAll(europeTask, coastalTask);
```

This saves ~20ms by running both `ST_Within` checks concurrently. Trade-off: if the point is outside Europe, the coastal zone check was wasted. For the common European coastal case, saves 20ms.

**Recommended for Phase 1:** implement parallel geography checks.

---

## 7. Scalability Design

### 7.1 Stateless API Containers

The API container is fully stateless — no in-flight state, no sticky sessions. The `IMemoryCache` for scenarios is per-instance but populated from the same DB source. Multiple replicas can handle requests independently.

### 7.2 Container Apps Autoscaling

```
Scale rules (ca-api and ca-tiler):
  trigger: HTTP concurrency
  min replicas: 0 (scale to zero, cost optimisation)
  max replicas: 5
  scale-up threshold: 10 concurrent requests per instance
```

**Scale-to-zero consideration:** The first request after idle period incurs a cold start penalty (10–30s for .NET, ~5–10s for Python/TiTiler). For a portfolio demo, warm up the app before presentation (see Risk R-03).

### 7.3 Database Scalability

PostgreSQL Flexible Server with Burstable B1ms SKU supports up to 20 connections at full performance. With 5 API replicas × pool size 4 = 20 connections: exactly at limit.

**If traffic grows:**
- Increase PostgreSQL SKU (B2ms or General Purpose)
- Add PgBouncer for connection pooling (reduce direct connections per replica)

### 7.4 TiTiler Scalability

TiTiler is stateless (all state in Azure Blob / GDAL VSI cache is per-instance). Multiple replicas handle tile requests independently.

**VSI cache note:** The 50MB in-process cache in each TiTiler replica is independent. With 3 replicas, the same COG bytes may be cached in each replica separately. This is acceptable — COG byte ranges are read-only and identical.

---

## 8. Performance Testing Plan

### 8.1 Phase 0 Spikes (Critical)

Before Phase 1 implementation, validate the key performance assumptions:

**Spike 1: TiTiler `/point` latency (validates Assumption A-01)**
```bash
# From API container environment (or equivalent location)
# Measure p50, p95, p99 for warm and cold COG
for i in {1..100}; do
  time curl "https://tiler.example.com/cog/point/4.9041,52.3676?url=${COG_URL}"
done
```

Expected: p50 ≤ 200ms, p95 ≤ 500ms (warm COG). If p95 > 1000ms, evaluate Option C.

**Spike 2: PostGIS ST_Within performance (validates Assumption A-02)**
```sql
EXPLAIN ANALYZE
SELECT ST_Within(
    ST_SetSRID(ST_Point(4.9041, 52.3676), 4326),
    geom
) FROM geography_boundaries WHERE name = 'europe';
```

Expected: seq scan avoided; GIST index used; < 20ms.

### 8.2 Load Test (Phase 2)

Target: 10 concurrent users × 5 minute sustained (NFR-018).

```bash
# k6 or Artillery load test
# Scenario: concurrent assess requests for varied coordinates
k6 run --vus 10 --duration 5m scripts/assess-load-test.js
```

Success criteria:
- p95 ≤ 3500ms (NFR-003)
- Error rate < 1%
- No container OOM or crash

---

## 9. Performance Monitoring (Ongoing)

See [09-observability-and-operations.md](09-observability-and-operations.md) §3 for KQL queries. Key metrics to track in production:

```kql
// Assessment latency percentiles over time
AppTraces
| where Properties.event == "AssessmentCompleted"
| summarize
    p50 = percentile(todouble(Properties.durationMs), 50),
    p95 = percentile(todouble(Properties.durationMs), 95),
    p99 = percentile(todouble(Properties.durationMs), 99)
  by bin(TimeGenerated, 5m)
| render timechart

// TiTiler vs DB contribution to assessment latency
AppTraces
| where Properties.event == "AssessmentCompleted"
| extend tilerMs = todouble(Properties.tilerDurationMs)
| extend dbMs = todouble(Properties.dbDurationMs)
| summarize avg(tilerMs), avg(dbMs) by bin(TimeGenerated, 1h)
```

Alert threshold: p95 assessment latency > 4000ms (buffer above NFR-003) for 10+ minutes.
