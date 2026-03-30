# 06 — API and Contracts

> **Status:** Proposed Architecture
> **Style:** REST/JSON over HTTPS. Base path: `/v1/`. All responses include a `requestId` for log correlation (NFR-013).

---

## 1. Conventions

- **HTTPS only** for all communication (NFR-005)
- **JSON** request/response bodies with `Content-Type: application/json`
- **Path versioning:** `/v1/` prefix. Breaking changes require `/v2/`.
- **requestId** in every response body — matches `X-Correlation-Id` header in backend logs (NFR-013)
- **No user authentication** — all endpoints are public (BR-001)
- **Result states** are string enum values matching BR-010 exactly — never numeric codes
- **Raw query strings** are NOT logged at any level (NFR-007)
- **CORS:** API must allow requests from the frontend domain only. TiTiler must also configure CORS for the frontend domain.

---

## 2. Endpoints

### POST /v1/geocode

**Purpose:** Accept a free-text location query and return ranked geocoding candidates.

**Request:**
```json
{
  "query": "Amsterdam"
}
```

**Validation:**
- `query`: required, string, 1–200 characters (FR-002, BR-008)

**Success Response (200 OK):**
```json
{
  "requestId": "req_abc123",
  "candidates": [
    {
      "rank": 1,
      "label": "Amsterdam, North Holland, Netherlands",
      "country": "NL",
      "latitude": 52.3676,
      "longitude": 4.9041,
      "displayContext": "North Holland, Netherlands"
    },
    {
      "rank": 2,
      "label": "Amsterdam, New York, United States",
      "country": "US",
      "latitude": 42.9387,
      "longitude": -74.1882,
      "displayContext": "New York, United States"
    }
  ]
}
```

**Notes:**
- `candidates` is 0–5 items (BR-007). Empty array = no results found (frontend shows no-results state per FR-038).
- `displayContext` provides locality detail to distinguish duplicate labels (BR-009)
- Provider rank is preserved in `rank` field (BR-006)
- `country` is ISO 3166-1 alpha-2 code
- Raw query string NOT logged (NFR-007)

**Error responses:**
- 400: `VALIDATION_ERROR` — query empty or >200 chars
- 500: `GEOCODING_PROVIDER_ERROR` — upstream provider unavailable → frontend shows FR-039 error state

---

### POST /v1/assess

**Purpose:** Evaluate coastal sea-level exposure for a coordinate under a specific scenario and time horizon. Returns one of the 5 result states (BR-010).

**Request:**
```json
{
  "latitude": 52.3676,
  "longitude": 4.9041,
  "scenarioId": "ssp2-45",
  "horizonYear": 2050
}
```

**Validation:**
- `latitude`: required, float, -90 to 90
- `longitude`: required, float, -180 to 180
- `scenarioId`: required, must exist in `scenarios` table
- `horizonYear`: required, must be 2030, 2050, or 2100 (FR-015)

**Success Response (200 OK) — ModeledExposureDetected:**
```json
{
  "requestId": "req_def456",
  "resultState": "ModeledExposureDetected",
  "location": {
    "latitude": 52.3676,
    "longitude": 4.9041
  },
  "scenario": {
    "id": "ssp2-45",
    "displayName": "Intermediate (SSP2-4.5)"
  },
  "horizon": {
    "year": 2050,
    "displayLabel": "2050"
  },
  "methodologyVersion": "v1.0",
  "layerTileUrlTemplate": "https://tiler.example.com/cog/tiles/{z}/{x}/{y}.png?url=https://blob.../layers/v1.0/ssp2-45/2050.tif",
  "legendSpec": {
    "colorStops": [
      { "value": 1, "color": "#E85D04", "label": "Modeled exposure zone" }
    ]
  },
  "generatedAt": "2026-03-30T12:00:00Z"
}
```

**Success Response — OutOfScope:**
```json
{
  "requestId": "req_ghi789",
  "resultState": "OutOfScope",
  "location": { "latitude": 50.07, "longitude": 14.43 },
  "scenario": { "id": "ssp2-45", "displayName": "Intermediate (SSP2-4.5)" },
  "horizon": { "year": 2050, "displayLabel": "2050" },
  "methodologyVersion": "v1.0",
  "layerTileUrlTemplate": null,
  "legendSpec": null,
  "generatedAt": "2026-03-30T12:00:00Z"
}
```

**Success Response — DataUnavailable:**
```json
{
  "requestId": "req_jkl012",
  "resultState": "DataUnavailable",
  "location": { "latitude": 51.20, "longitude": 2.90 },
  "scenario": { "id": "ssp1-26", "displayName": "Low (SSP1-2.6)" },
  "horizon": { "year": 2030, "displayLabel": "2030" },
  "methodologyVersion": "v1.0",
  "layerTileUrlTemplate": null,
  "legendSpec": null,
  "generatedAt": "2026-03-30T12:00:00Z"
}
```

**All five result states:** `ModeledExposureDetected`, `NoModeledExposureDetected`, `DataUnavailable`, `OutOfScope`, `UnsupportedGeography`

**Invariants:**
- `methodologyVersion` is **always present** (FR-035, BR-015)
- `scenario` and `horizon` are **always present** (FR-020)
- `layerTileUrlTemplate` is **non-null only when** `resultState === "ModeledExposureDetected"` (FR-021)
- `OutOfScope` and `UnsupportedGeography` return HTTP **200 OK** — they are valid result states, not errors
- DataUnavailable is returned when no valid layer exists — no substitution of another combination (BR-014)

**Error responses:**
- 400: `VALIDATION_ERROR`, `UNKNOWN_SCENARIO`, `UNKNOWN_HORIZON`
- 500: `INTERNAL_ERROR` → frontend shows FR-039 error state

---

### GET /v1/config/scenarios

**Purpose:** Return the configured scenario set, available horizons, and defaults. Frontend fetches on app load and caches for the session.

**Response (200 OK):**
```json
{
  "requestId": "req_mno345",
  "scenarios": [
    {
      "id": "ssp1-26",
      "displayName": "Low (SSP1-2.6)",
      "description": "A lower-emissions pathway representing ambitious mitigation.",
      "sortOrder": 1
    },
    {
      "id": "ssp2-45",
      "displayName": "Intermediate (SSP2-4.5)",
      "description": "A middle-of-the-road pathway. Reflects current policy trajectory.",
      "sortOrder": 2
    },
    {
      "id": "ssp5-85",
      "displayName": "High (SSP5-8.5)",
      "description": "A high-emissions pathway. Upper-bound projection.",
      "sortOrder": 3
    }
  ],
  "horizons": [
    { "year": 2030, "displayLabel": "2030", "sortOrder": 1 },
    { "year": 2050, "displayLabel": "2050", "sortOrder": 2 },
    { "year": 2100, "displayLabel": "2100", "sortOrder": 3 }
  ],
  "defaults": {
    "scenarioId": "ssp2-45",
    "horizonYear": 2050
  }
}
```

**IMPORTANT:** Scenario IDs, display names, and descriptions above are **illustrative examples only**. Actual values are determined by OQ-02 (BLOCKING). Horizon values (2030, 2050, 2100) are confirmed (FR-015). Default scenario and horizon are OQ-03 (BLOCKING).

---

### GET /v1/config/methodology

**Purpose:** Return current active methodology metadata for display in the methodology panel (FR-033).

**Response (200 OK):**
```json
{
  "requestId": "req_pqr678",
  "methodologyVersion": "v1.0",
  "seaLevelProjectionSource": {
    "name": "IPCC AR6 sea-level projections",
    "provider": "NASA Sea Level Change Team",
    "url": "https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool"
  },
  "elevationSource": {
    "name": "Copernicus DEM (Digital Surface Model, GLO-30)",
    "provider": "Copernicus / DLR",
    "url": "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM"
  },
  "whatItDoes": "This methodology combines IPCC AR6 mean sea-level projections with Copernicus DEM surface elevations to identify locations where projected sea-level rise reaches or exceeds the terrain elevation under each scenario and time horizon.",
  "whatItDoesNotAccountFor": [
    "Flood defenses or coastal adaptation infrastructure",
    "Hydrodynamic connectivity (whether water can physically reach a location)",
    "Storm surge or tidal variability",
    "Land subsidence",
    "Local drainage infrastructure"
  ],
  "resolutionNote": "Results are derived from approximately 30-meter resolution datasets. Results cannot distinguish conditions within a single city block and are not suitable for site-specific engineering or property-level decisions.",
  "interpretationGuidance": {
    "modeledExposureDetected": "The selected point falls within a zone where modeled sea-level rise reaches or exceeds the terrain elevation under the selected scenario and time horizon.",
    "noModeledExposureDetected": "The selected point does not fall within a modeled exposure zone under the selected scenario and time horizon. This does not constitute a safety determination."
  },
  "updatedAt": "2026-03-30T00:00:00Z"
}
```

**Notes:** Content maps directly to CONTENT_GUIDELINES §5 methodology panel requirements. `whatItDoesNotAccountFor` list is a required element.

---

### GET /health

**Purpose:** Health and readiness check for Azure Container Apps probes (NFR-011).

**Healthy response (200 OK):**
```json
{
  "status": "healthy",
  "components": {
    "postgres": "healthy",
    "blobStorage": "healthy"
  },
  "timestamp": "2026-03-30T12:00:00Z"
}
```

**Degraded response (503 Service Unavailable):**
```json
{
  "status": "unhealthy",
  "components": {
    "postgres": "unhealthy",
    "blobStorage": "healthy"
  },
  "timestamp": "2026-03-30T12:00:00Z"
}
```

Returns HTTP 200 when healthy, HTTP 503 when any critical dependency is unavailable.

---

## 3. Error Model

Standard error envelope for all 4xx and 5xx responses:

```json
{
  "requestId": "req_abc123",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Query must be between 1 and 200 characters.",
    "field": "query"
  }
}
```

**Error codes:**

| Code | HTTP Status | When |
|---|---|---|
| `VALIDATION_ERROR` | 400 | Input format invalid |
| `UNKNOWN_SCENARIO` | 400 | `scenarioId` not in database |
| `UNKNOWN_HORIZON` | 400 | `horizonYear` not in {2030, 2050, 2100} |
| `GEOCODING_PROVIDER_ERROR` | 500 | Upstream geocoding provider unavailable |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

**Note:** `OutOfScope`, `UnsupportedGeography`, and `DataUnavailable` are **not errors**. They are valid `resultState` values in a 200 OK assess response.

---

## 4. Result State Taxonomy Reference

| resultState | HTTP | Condition | layerTileUrlTemplate |
|---|---|---|---|
| `ModeledExposureDetected` | 200 | In Europe ✓, In coastal zone ✓, Layer exists ✓, Point intersects exposure zone | present |
| `NoModeledExposureDetected` | 200 | In Europe ✓, In coastal zone ✓, Layer exists ✓, Point NOT in exposure zone | null |
| `DataUnavailable` | 200 | In Europe ✓, In coastal zone ✓, No valid layer for scenario+horizon+active version | null |
| `OutOfScope` | 200 | In Europe ✓, NOT in coastal zone | null |
| `UnsupportedGeography` | 200 | NOT in Europe | null |

This taxonomy is **FIXED** (BR-010). The API must never return a string outside this set.

---

## 5. Validation Approach

In ASP.NET Core Minimal API:
```csharp
app.MapPost("/v1/assess", async (AssessRequest req, IAssessmentService svc) =>
{
    // Validation via FluentValidation endpoint filter or .WithValidator<AssessRequest>()
    var result = await svc.AssessAsync(...);
    return Results.Ok(result);
})
.WithValidator<AssessRequest>();
```

Geography validation is **not** in the HTTP layer — it returns result states, not HTTP errors.

---

## 6. Versioning Strategy

- Path versioning: `/v1/`
- Minor, additive changes (new optional response fields): no version bump required
- Breaking changes (removed fields, changed shapes, new required fields): introduce `/v2/`
- MVP starts at v1; no v2 planned

---

## 7. CORS Configuration

**API container:**
```csharp
builder.Services.AddCors(options =>
{
    options.AddPolicy("frontend", policy =>
    {
        policy.WithOrigins(Environment.GetEnvironmentVariable("CORS_ALLOWED_ORIGINS")
                          .Split(','))
              .AllowAnyMethod()
              .AllowAnyHeader();
    });
});
app.UseCors("frontend");
```

**TiTiler:** Configure `TITILER_API_CORS_ORIGINS` environment variable with the frontend domain.

In development: allow `http://localhost:3000`. In production: allow the production frontend domain only.
