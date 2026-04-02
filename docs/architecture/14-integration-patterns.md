# 14 — Integration Patterns

> **Status:** Proposed Architecture
> **Scope:** How the system integrates with external services (geocoding provider, TiTiler, Azure Blob Storage, PostgreSQL) and the patterns used to manage failures, timeouts, and provider variability.

---

## 1. Integration Inventory

| Integration | Direction | Protocol | Auth | Criticality |
|---|---|---|---|---|
| API → Geocoding provider | Outbound | HTTPS/REST | API key (header) | High (BR-001 use case requires geocoding) |
| API → TiTiler (`/point`) | Outbound | HTTP/REST (internal) | None | High (assessment depends on pixel value) |
| Browser → TiTiler (tiles) | Outbound | HTTPS/REST | None | Medium (overlay display; assessment result already known) |
| API → PostgreSQL | Outbound | TCP (Npgsql) | Connection string | Critical (all domain logic depends on DB) |
| TiTiler → Azure Blob | Outbound | HTTPS (GDAL VSIAZ) | Managed identity or connection string | Critical (TiTiler is useless without Blob access) |
| API → Azure Blob (integrity) | Outbound | HTTPS (Azure SDK) | Managed identity | Low (optional integrity check) |
| Frontend → API | Outbound | HTTPS/REST | None (public) | High |

---

## 2. Geocoding Provider Integration

### 2.1 Interface Contract

The geocoding provider is abstracted behind `IGeocodingService`. The production implementation (`AzureMapsGeocodingClient`, ADR-019) adapts the Azure Maps Search API to the internal `GeocodingCandidate` model.

```csharp
public interface IGeocodingService
{
    Task<IReadOnlyList<GeocodingCandidate>> GeocodeAsync(
        string query,
        CancellationToken cancellationToken);
}
```

### 2.2 Provider Normalization

Each provider returns candidates in a different format. The adapter's job:

| Provider Field | Internal Field | Notes |
|---|---|---|
| Provider-specific rank/score | `Rank` (1-based) | Preserve provider order (BR-006) |
| Display name / formatted address | `Label` | Full place label |
| Country code | `Country` | ISO 3166-1 alpha-2 |
| lat / lon / location | `Latitude`, `Longitude` | Float coordinates |
| Admin1 + country or region | `DisplayContext` | Disambiguates duplicate place names (BR-009) |

`DisplayContext` construction varies:
- If provider returns admin hierarchy: `"{region}, {country_display_name}"`
- If provider returns only country: `"{country_display_name}"`
- Never: raw address string

### 2.3 Error Handling

```csharp
public async Task<IReadOnlyList<GeocodingCandidate>> GeocodeAsync(string query, CancellationToken ct)
{
    try
    {
        var response = await _httpClient.GetAsync(BuildUrl(query), ct);
        response.EnsureSuccessStatusCode();
        return ParseAndNormalize(await response.Content.ReadAsStringAsync(ct));
    }
    catch (HttpRequestException ex)
    {
        _logger.LogError("GeocodeProviderError {StatusCode}", ex.StatusCode);
        throw new GeocodingProviderException("Upstream geocoding provider unavailable", ex);
    }
    catch (TaskCanceledException) when (!ct.IsCancellationRequested)
    {
        // Timeout (not user cancellation)
        throw new GeocodingProviderException("Geocoding provider request timed out");
    }
    // User cancellation (AbortController) — propagate naturally as OperationCanceledException
}
```

`GeocodingProviderException` is caught by the HTTP layer and mapped to HTTP 500 `GEOCODING_PROVIDER_ERROR`.

### 2.4 Timeouts

```csharp
// Registered in DI container
services.AddHttpClient<IGeocodingService, ProviderGeocodingClient>(client =>
{
    client.BaseAddress = new Uri(config["Geocoding:BaseUrl"]);
    client.Timeout = TimeSpan.FromSeconds(5);  // Hard timeout — within NFR-002 (2.5s) budget
    client.DefaultRequestHeaders.Add("Authorization", $"Bearer {apiKey}");
});
```

**Timeout strategy:** 5s total timeout on the geocoding HTTP call. If the provider doesn't respond within 5s, the API returns `GEOCODING_PROVIDER_ERROR`. This keeps the API responsive even when the provider is slow.

### 2.5 Retry Policy

For MVP: **no automatic retry** on geocoding failures. The frontend provides a manual "Retry" button (FR-039). Automatic retries risk amplifying provider outage load and add latency to the user experience.

---

## 3. TiTiler Integration (Assessment Point Query)

### 3.1 Pattern: HTTP Request to `/point/{lng},{lat}`

The `ExposureEvaluator` (Option A — see ADR-006) queries TiTiler's point endpoint:

```
GET {TILER_BASE_URL}/cog/point/{longitude},{latitude}?url={blobStorageUrl}

Response:
{
  "coordinates": [4.9041, 52.3676, 1],
  "values": [[1]],
  "band_names": ["b1"]
}
```

**Pixel value interpretation:**
- `1` → `ModeledExposureDetected`
- `0` → `NoModeledExposureDetected`
- `null` / NoData → treat as `NoModeledExposureDetected` (location is within coastal zone but outside COG extent)

**Confirmed (ADR-015):** Binary methodology — pixel values are 0 or 1. No continuous interpretation needed.

### 3.2 ExposureEvaluator Implementation

```csharp
public class TilerExposureEvaluator : IExposureEvaluator
{
    private readonly HttpClient _tilerClient;
    private readonly ILogger<TilerExposureEvaluator> _logger;

    public async Task<bool> IsExposedAsync(
        double latitude,
        double longitude,
        ExposureLayer layer,
        CancellationToken ct)
    {
        // Blob URL for the COG — from layer.blobPath (not from request input)
        var cogUrl = BuildBlobUrl(layer.blobPath);
        var url = $"/cog/point/{longitude},{latitude}?url={Uri.EscapeDataString(cogUrl)}";

        var response = await _tilerClient.GetAsync(url, ct);
        response.EnsureSuccessStatusCode();

        var result = await response.Content.ReadFromJsonAsync<TilerPointResponse>(ct);
        var pixelValue = result?.Values?.FirstOrDefault()?.FirstOrDefault();

        _logger.LogDebug("TilerQueryCompleted {PixelValue}", pixelValue);

        return pixelValue == 1;  // ADR-015: binary methodology, pixel 1 = exposed
    }
}
```

### 3.3 TiTiler Timeout and Failure Handling

```csharp
services.AddHttpClient<IExposureEvaluator, TilerExposureEvaluator>(client =>
{
    client.BaseAddress = new Uri(config["Tiler:BaseUrl"]);
    client.Timeout = TimeSpan.FromSeconds(3);  // Within assessment budget
});
```

**Failure:** If TiTiler returns non-2xx or times out, the `AssessmentService` catches the exception and returns HTTP 500 `INTERNAL_ERROR` to the client. There is no fallback assessment path.

### 3.4 Blob URL Construction

The COG URL passed to TiTiler is constructed from the `blob_path` stored in the database:

```csharp
private string BuildBlobUrl(string blobPath)
{
    // blobPath: "layers/v1.0/ssp2-45/2050.tif"
    // Construct a SAS URL or use connection string-based GDAL VSIAZ path
    // Option A: TiTiler VSIAZ (Azure connection string configured in TiTiler env)
    return $"az://geospatial/{blobPath}";   // GDAL VSIAZ URI scheme

    // Option B: HTTPS blob URL (if TiTiler has network access + storage is public-readable)
    // return $"https://{storageAccount}.blob.core.windows.net/geospatial/{blobPath}";
}
```

**Note:** The GDAL VSIAZ scheme (`az://container/path`) requires `AZURE_STORAGE_CONNECTION_STRING` or managed identity configured in TiTiler's environment. The blob container must not be publicly accessible (security requirement).

---

## 4. Browser → TiTiler Tile Integration

### 4.1 Pattern: XYZ Tile URL Template

The API returns a `layerTileUrlTemplate` in the assess response (only for `ModeledExposureDetected`):

```
https://tiler.searise-europe.example.com/cog/tiles/{z}/{x}/{y}.png
  ?url=https://sa.blob.core.windows.net/geospatial/layers/v1.0/ssp2-45/2050.tif
  &colormap_name=reds
  &rescale=0,1
```

MapLibre uses this template to fetch tiles directly from TiTiler. The API is not in this path.

### 4.2 CORS Requirements

TiTiler must allow tile requests from the frontend domain:
```
TITILER_API_CORS_ORIGINS=https://www.searise-europe.example.com
```

### 4.3 Tile Caching

TiTiler itself does not cache tiles. The browser caches tile responses via standard HTTP caching. COG files are static (`Cache-Control: max-age=86400, public`) — tile responses can be aggressively cached.

If `layerTileUrlTemplate` changes (new methodology version), MapLibre's tile cache is effectively invalidated because the URL changes.

---

## 5. PostgreSQL Integration

### 5.1 Connection Management

```csharp
// Registered in Program.cs
services.AddNpgsqlDataSource(
    connectionString,
    builder => builder
        .EnableDynamicJson()
        .ConfigureJsonOptions(options => { /* PostGIS geometry handling */ }));
```

**Connection pool settings:**
```
Maximum Pool Size = 20    // Per API replica; Container Apps may run 1–5 replicas
Minimum Pool Size = 1
Connection Idle Lifetime = 300s
Connection Lifetime = 600s
```

### 5.2 PostGIS Query Pattern

```csharp
// Geography check — parameterized, no string interpolation
const string europeQuery = @"
    SELECT ST_Within(
        ST_SetSRID(ST_Point(@Lng, @Lat), 4326),
        geom
    ) FROM geography_boundaries WHERE name = 'europe'";

var isInEurope = await connection.ExecuteScalarAsync<bool>(
    europeQuery,
    new { Lat = latitude, Lng = longitude });
```

**Performance:** GIST index on `geography_boundaries.geom` ensures spatial lookups complete in ~20ms.

### 5.3 Health Check

```csharp
services.AddHealthChecks()
    .AddNpgsql(connectionString, name: "postgres");
```

The health check executes `SELECT 1` against PostgreSQL. Failure causes `GET /health` to return HTTP 503.

---

## 6. Azure Blob Storage Integration

### 6.1 TiTiler Access (GDAL VSIAZ)

TiTiler reads COGs via GDAL's VSIAZ virtual filesystem driver. This is configured entirely via environment variables — no code changes required:

```
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
# OR (preferred): use managed identity via AZURE_CLIENT_ID + AZURE_TENANT_ID
```

GDAL VSIAZ performs HTTP range requests against the Blob Storage REST API, reading only the COG bytes needed for the requested tile or point query.

### 6.2 API Access (Azure SDK — Integrity Check)

The API may optionally verify blob existence during layer registration (not a runtime check per assessment):

```csharp
var blobClient = new BlobServiceClient(connectionString);
var containerClient = blobClient.GetBlobContainerClient("geospatial");
var blobExists = await containerClient.GetBlobClient(blobPath).ExistsAsync();
```

This is not in the critical assessment path.

---

## 7. Resilience Patterns Summary

| Integration | Timeout | Retry | Circuit Breaker | Fallback |
|---|---|---|---|---|
| Geocoding provider | 5s | None (manual retry via UI) | None (MVP) | None — returns `GEOCODING_PROVIDER_ERROR` |
| TiTiler `/point` | 3s | None | None (MVP) | None — returns `INTERNAL_ERROR` |
| PostgreSQL | Connection timeout: 5s | Npgsql built-in retry on transient | None explicit | None — returns `INTERNAL_ERROR` |
| Azure Blob (TiTiler via GDAL) | GDAL default (~30s) | GDAL retry | None | None — TiTiler returns error |

**Phase 2 consideration:** Add Polly-based circuit breaker for geocoding provider. If provider is down for > 60s, fail fast without waiting for individual request timeouts.

---

## 8. Frontend Integration Patterns

### 8.1 TanStack Query Configuration

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,                  // One automatic retry for transient failures
      refetchOnWindowFocus: false,
      staleTime: 0,              // Default — overridden per query
    },
  },
})

// Config query — session-cached
const { data: config } = useQuery({
  queryKey: ['config', 'scenarios'],
  queryFn: fetchScenarios,
  staleTime: Infinity,           // Never refetch during session
})

// Assessment query — short-lived cache
const { data: result } = useQuery({
  queryKey: ['assess', lat, lng, scenarioId, horizonYear],
  queryFn: ({ signal }) => fetchAssessment({ lat, lng, scenarioId, horizonYear, signal }),
  staleTime: 60_000,             // 60s — covers rapid control changes
  enabled: !!selectedLocation,
})
```

### 8.2 Request Cancellation

TanStack Query passes an `AbortSignal` to the `queryFn`. The fetch call forwards this signal:

```typescript
async function fetchAssessment(
  params: AssessParams & { signal: AbortSignal }
): Promise<AssessmentResult> {
  const response = await fetch('/v1/assess', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: params.signal,       // AbortController signal from TanStack Query
  })
  if (!response.ok) {
    const error = await response.json()
    throw new ApiError(error.error.code, error.error.message)
  }
  return response.json()
}
```

When the query key changes (scenario change), TanStack Query automatically aborts the previous request via the signal.

### 8.3 Error Boundary Strategy

```typescript
// Two-level error handling:
// 1. TanStack Query isError state — renders ErrorBanner in the component
// 2. React ErrorBoundary at page level — catches unexpected render errors

// ErrorBanner receives the error code from the API and shows appropriate copy
<ErrorBanner
  code={assessError?.code}   // "INTERNAL_ERROR" | "GEOCODING_PROVIDER_ERROR"
  onRetry={() => refetch()}
/>
```
