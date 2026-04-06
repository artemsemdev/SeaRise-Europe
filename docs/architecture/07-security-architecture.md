# 07 — Security Architecture

> **Status:** Proposed Architecture
> **Scope:** Security controls, threat model, secrets management, and privacy boundaries for the SeaRise Europe system.

---

## 1. Security Posture Summary

SeaRise Europe is a **public, read-only, anonymous web application** (BR-001). There are no user accounts, no sessions, no payment flows, and no privileged operations. This substantially narrows the attack surface compared to authenticated applications.

Key security properties:
- No authentication or authorization layer (by design — BR-001)
- No user-generated data stored (BR-016)
- No raw addresses written to any persistent store (NFR-007, BR-016)
- All API keys and connection strings held server-side only (NFR-006)
- HTTPS required for all communication (NFR-005)
- API keys for geocoding and basemap providers never sent to the browser

---

## 2. Threat Model

### 2.1 Assets to Protect

| Asset | Sensitivity | Rationale |
|---|---|---|
| Geocoding provider API key | High | Billing exposure if leaked; rate-limit abuse |
| Basemap tile provider key (ADR-020: Azure Maps) | Medium–High | Billing and usage policy violation if scraped; mitigated by CORS origin restriction |
| PostgreSQL connection string | High | Read access to all scenario/layer config |
| Azure Blob Storage credentials | Medium | Read access to COG layer files |
| Azure Key Vault access | High | Master access to all above credentials |

### 2.2 Threats and Controls

| Threat | Vector | Control |
|---|---|---|
| **API key exfiltration** | Client-side bundle inspection | Keys held in API container env vars only; never bundled into frontend (NFR-006) |
| **Geocoding provider key abuse** | Scraped from source / network traffic | Key only used server-side in the API container; browser only communicates with `/v1/geocode` |
| **Basemap key scraping** | Browser Network tab | ADR-020 — mitigated by Azure Maps CORS origin restriction (see §3.3); key visible in tile URL is accepted risk if domain-locked |
| **SQL injection** | Malformed coordinates in POST body | Parameterized queries via Npgsql; never string-interpolated (see §4) |
| **SSRF via geocoding endpoint** | Attacker-controlled `query` input | Query string is passed only to the trusted managed geocoding provider; no URL construction from query value |
| **SSRF via assess endpoint** | Attacker-controlled lat/lng | Coordinates are floats, validated at HTTP layer; no URL constructed from coordinate values |
| **Path traversal in blob access** | Attacker-controlled scenario/horizon IDs | Layer blob path is resolved from DB lookup using validated scenario/horizon IDs — never constructed from raw request values |
| **Abusive geocoding traffic** | Bot / scripted abuse | Rate limiting at Azure Container Apps ingress or API Gateway (see §3.5); accepted risk at MVP scale |
| **XSS** | User-supplied query rendered in DOM | React escapes all dynamic content; never use `dangerouslySetInnerHTML` with user input |
| **CORS bypass** | Cross-origin request to API | CORS policy allows only frontend domain with restricted methods (GET, POST, OPTIONS) (see §06 §7) |
| **Secret drift** | Secrets hardcoded in source / Dockerfile | Key Vault references used; secrets never in source code or image layers (NFR-006) |
| **Container breakout** | Compromised container affecting others | Azure Container Apps process isolation; least-privilege managed identities per container |
| **COG tampering** | Malicious blob content affecting tile output | Blobs are write-once from pipeline; Storage account access restricted to pipeline principal + managed identity |

---

## 3. Secrets Management

### 3.1 Azure Key Vault Architecture

All secrets are stored in **Azure Key Vault** and injected into Container Apps as environment variables at runtime via Key Vault references. No secret ever appears in:
- Source code or git history
- Dockerfile or build context
- Container registry image layers
- Application logs
- Frontend JavaScript bundles

```
Azure Key Vault
├── geocoding-provider-api-key       → API container: GEOCODING_API_KEY
├── postgres-connection-string       → API container: DATABASE_URL
├── blob-storage-connection-string   → API container: BLOB_CONNECTION_STRING
│                                    → TiTiler container: AZURE_STORAGE_CONNECTION_STRING
├── cors-allowed-origins             → API container: CORS_ALLOWED_ORIGINS
└── basemap-subscription-key (ADR-020: Azure Maps) → Frontend build env: NEXT_PUBLIC_BASEMAP_STYLE_URL (CORS origin-restricted, see §3.3)
```

**Key Vault reference syntax in Container Apps:**

```
secretref:keyvault-name/secret-name
```

At container startup, Container Apps resolves the reference and injects the value. The resolved value is never written to disk.

### 3.2 Managed Identity for Blob Storage

TiTiler accesses Azure Blob Storage via the GDAL VSIAZ driver. Two access options:

| Option | Security | Operational Complexity |
|---|---|---|
| **Managed Identity** (preferred) | No credentials in environment; identity-bound to container | Requires RBAC role assignment (`Storage Blob Data Reader`) |
| **Connection String** | Simple; Key Vault reference handles rotation | Credential in memory; rotation requires container restart |

**Recommendation:** Managed Identity for TiTiler → Blob access (Proposed Architecture). Managed Identity also for the API container's Blob integrity check access.

### 3.3 Basemap Tile Key (ADR-020: Azure Maps)

The basemap provider key is the only credential that must be accessible from the browser (as part of tile URLs). Three mitigation approaches:

| Approach | Security Level | Complexity |
|---|---|---|
| **CORS origin restriction** | Key requests only accepted from registered origins; useless if scraped | Low — configure in Azure Portal |
| **HTTP referrer restriction** | Provider rejects requests not originating from registered referrer | Low — configure in Azure Portal |
| **Server-side tile proxy** | API proxies all tile requests; key never leaves server | High — adds latency and hosting cost |

**Decision (ADR-020):** CORS origin-restricted subscription key via Azure Maps. Azure Maps supports CORS origin restrictions configured in the Azure Portal. Production and staging domains registered. Server-side proxy not needed. Uses the same Azure Maps account as geocoding (ADR-019).

### 3.4 Key Rotation

- All secrets in Key Vault; rotation does not require code changes
- Container Apps environment variable update triggers rolling restart
- No in-process key caching beyond the process lifetime

### 3.5 Rate Limiting

ASP.NET Core built-in rate limiter (`System.Threading.RateLimiting`) is configured in `Program.cs`:

| Scope | Limit | Window | Purpose |
|-------|------:|--------|---------|
| Global (per IP) | 60 | 1 min | General abuse prevention |
| `POST /v1/geocode` | 20 | 1 min | Protect Azure Maps API quota |
| `POST /v1/assess` | 10 | 1 min | Protect TiTiler + PostGIS from expensive queries |

- Exceeded limits return HTTP 429 (Too Many Requests)
- Rate limit rejections emit a structured `RateLimitExceeded` warning log with client IP and path for monitoring and alerting
- Request body size limit: 1 KB (Kestrel `MaxRequestBodySize`)
- **Additional layer (Azure):** Container Apps ingress rules can add infrastructure-level rate limiting if needed

---

## 4. Input Validation and Injection Prevention

### 4.1 SQL Injection Prevention

All database access uses Npgsql with parameterized queries. No string interpolation in SQL:

```csharp
// CORRECT — parameterized
await connection.QueryAsync<bool>(
    "SELECT ST_Within(ST_SetSRID(ST_Point(@Lng, @Lat), 4326), geom) FROM geography_boundaries WHERE name = 'europe'",
    new { Lat = latitude, Lng = longitude });

// NEVER DO THIS
$"SELECT ... WHERE lat = {latitude}"   // ← injection vector
```

PostGIS geometry functions receive float parameters, not strings. There is no scenario where user-supplied text appears in a SQL query.

### 4.2 HTTP Input Validation

All API inputs are validated at the HTTP layer before entering the application:

```csharp
// Geocode endpoint
public record GeocodeRequest(string Query);
// FluentValidation: Query required, 1–200 chars (BR-008)

// Assess endpoint
public record AssessRequest(double Latitude, double Longitude, string ScenarioId, int HorizonYear);
// FluentValidation:
//   Latitude: -90 to 90
//   Longitude: -180 to 180
//   ScenarioId: must exist in scenarios table
//   HorizonYear: must be in {2030, 2050, 2100} (FR-015)
```

Invalid inputs return HTTP 400 with `VALIDATION_ERROR` before any infrastructure calls are made.

### 4.3 SSRF Prevention

The API makes two categories of outbound calls:
1. **Geocoding provider** — URL is a fixed, configured base URL. Only the `query` parameter is appended. The `query` string is treated as a plain search term, not a URL or path.
2. **TiTiler `/point` endpoint** — URL is constructed from validated float coordinates + a `blob_path` from the database (not from the request). An attacker cannot control the blob_path via the API. Additionally, the blob_path is validated against an allowlist pattern (`^[a-z0-9][a-z0-9/_\-\.]*\.tif$`) with an explicit `..` traversal check before being passed to TiTiler, preventing path traversal even in the event of database compromise.

Neither call involves user-controlled URL construction.

### 4.4 XSS Prevention

- React escapes all dynamic values by default
- `dangerouslySetInnerHTML` is prohibited with user-supplied content
- Methodology content (from API `/v1/config/methodology`) contains no user input; any rendered HTML is developer-controlled
- Result state labels, scenario names, and error messages are controlled string enums — not user-supplied text

### 4.5 Content Security Policy

CSP headers are configured in `next.config.js` via the `headers()` function:

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'unsafe-eval' 'unsafe-inline';
  style-src 'self' 'unsafe-inline';
  img-src 'self' blob: data: https://*.atlas.microsoft.com {TILER_ORIGIN};
  connect-src 'self' https://*.atlas.microsoft.com {TILER_ORIGIN};
  worker-src 'self' blob:;
  child-src 'self' blob:;
  font-src 'self';
```

**Notes:**
- `unsafe-eval` is required by MapLibre GL JS (WebGL shader compilation). This is an accepted limitation of the mapping library.
- `unsafe-inline` for scripts is required by Next.js inline script injection. This is an accepted framework limitation.
- `*.atlas.microsoft.com` covers Azure Maps basemap tiles and search API.
- `{TILER_ORIGIN}` is dynamically resolved from `NEXT_PUBLIC_TILER_BASE_URL` at build time (defaults to `http://localhost:8000` for local dev). This ensures TiTiler raster tile requests are permitted by CSP in all environments.

### 4.6 HTTP Security Headers

Both the API (`Program.cs` middleware) and frontend (`next.config.js`) set the following headers on all responses:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevent MIME sniffing |
| `X-Frame-Options` | `DENY` | Prevent clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer leakage |
| `Permissions-Policy` | `geolocation=(), camera=(), microphone=()` | Disable unnecessary browser APIs |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Enforce HTTPS in browsers (HSTS) |

---

## 5. Privacy and Data Handling

### 5.1 No User Data Storage

SeaRise Europe stores no personal data. This is enforced by architecture, not just policy:

- No user table, session table, or address table in PostgreSQL (schema in [05-data-architecture.md](05-data-architecture.md))
- No cookies set by the application
- No user identifiers generated or stored
- The geocoding query (`query` field in POST body) is passed to the provider and discarded; it is never written to any store (BR-016, NFR-007)

### 5.2 Log Privacy

Raw query strings **must not appear in any log**. Enforcement approach:

```csharp
// CORRECT — log only metadata
logger.LogInformation("Geocode request processed. ResultCount={Count} RequestId={RequestId}",
    candidates.Count, requestId);

// NEVER DO THIS
logger.LogInformation("Geocode query: {Query}", request.Query);  // ← NFR-007 violation
```

Structured log fields that are permitted:
- `requestId` (correlation ID)
- `resultState` (enum value)
- `country_code` (ISO 3166-1 alpha-2 from geocoding result — NOT the raw query)
- `duration_ms` (request processing time)
- `statusCode` (HTTP status)

Precise coordinates must not appear in production logs or analytics (see [METRICS_PLAN.md](../product/METRICS_PLAN.md) §7).

### 5.3 GDPR Considerations

The application is Europe-focused and may attract EU residents. Key considerations:

- **No personal data processed** → minimal GDPR exposure
- **Analytics (OQ-10):** No client-side analytics in MVP (server-side observability only). If analytics are added in Phase 2, events must use `country_code` only, not coordinates or any user identifier. This is documented in METRICS_PLAN.md §6.
- **Consent banner:** Required only if analytics cookies are set. If analytics are server-side only (no cookies), no consent banner required under ePrivacy Directive.
- **Privacy policy:** Required for production deployment. Content is outside this document's scope.

---

## 6. Network Security

### 6.1 Communication Security

| Path | Protocol | Notes |
|---|---|---|
| Browser → Frontend | HTTPS (TLS 1.2+) | Azure Container Apps provides TLS termination |
| Browser → API | HTTPS (TLS 1.2+) | Azure Container Apps provides TLS termination |
| Browser → TiTiler (tile requests) | HTTPS (TLS 1.2+) | Azure Container Apps provides TLS termination |
| API → TiTiler | Internal (HTTP within VNet or Container Apps env) | No external exposure required; see §6.2 |
| API → PostgreSQL | TLS (enforced by Azure Database for PostgreSQL) | `sslmode=require` in connection string |
| TiTiler → Blob Storage | HTTPS (Azure SDK) | Internal Azure network |
| API → Blob Storage | HTTPS (Azure SDK) | Internal Azure network |
| API → Geocoding provider | HTTPS | External; enforced by provider |

### 6.2 Network Isolation

**Proposed topology** (Proposed Architecture):

```
Internet ──► Container Apps Ingress (public)
                ├── frontend   (public ingress)
                ├── api        (public ingress)
                └── tiler      (internal ingress — not publicly exposed)

api ──► tiler   (internal Container Apps traffic, not internet-routed)
```

TiTiler serves two traffic types:
1. **Assessment point queries** (`/point/{lng},{lat}`) — from the API container only; should use internal ingress
2. **Map tile requests** (`/{z}/{x}/{y}.png`) — from the browser directly; requires public ingress

**Tradeoff:** If TiTiler must be publicly accessible for browser tile requests, the `/point` endpoint is also publicly accessible. Mitigations:
- Rate limiting on `/point` at ingress
- Or: separate TiTiler instances for internal (assessment) and public (tile serving) — adds operational complexity

For MVP, single TiTiler instance with public ingress is accepted. Internal traffic from API to TiTiler uses the Container Apps internal DNS name, not the public URL.

---

## 7. Supply Chain Security

| Risk | Control |
|---|---|
| Compromised npm package | `npm audit --audit-level=high` in CI; lock file committed; no `*` version ranges; Dependabot enabled |
| Compromised NuGet package | `dotnet list package --vulnerable` in CI; lock file committed; Dependabot enabled |
| Compromised Python package (TiTiler) | Pin TiTiler version in Dockerfile; review on upgrade; Dependabot enabled for pip |
| Malicious Docker base image | Use Microsoft/official base images only; pin digest in production Dockerfile; Dependabot enabled for Docker |
| Compromised GitHub Action | CI actions pinned to specific version tags (not floating major); Dependabot monitors for updates |
| Azure Container Registry exposure | ACR access restricted to Container Apps environment via Managed Identity |

---

## 8. Security Checklist (Pre-Production)

- [ ] All secrets in Key Vault — none in source code, Dockerfiles, or environment variable literals
- [ ] HTTPS enforced on all ingress (Container Apps managed certificate)
- [ ] CORS configured to production frontend domain only
- [ ] Azure Maps basemap subscription key CORS origin-restricted (ADR-020)
- [ ] Raw query string absent from all log statements (code review + log audit)
- [ ] Precise coordinates absent from all log statements
- [x] CSP headers configured for frontend (`next.config.js`) — includes TiTiler origin via `NEXT_PUBLIC_TILER_BASE_URL`
- [x] HTTP security headers configured for API and frontend (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, Strict-Transport-Security)
- [x] Rate limiting configured: global 60/min per IP, geocode 20/min, assess 10/min
- [x] Rate limit rejections (HTTP 429) logged with structured `RateLimitExceeded` event
- [x] Request body size limited to 1 KB (Kestrel)
- [x] `npm audit --audit-level=high` and `dotnet list package --vulnerable` in CI pipeline
- [x] Dependabot configured for npm, NuGet, pip, GitHub Actions, and Docker
- [x] GitHub Actions pinned to specific version tags (not floating major)
- [x] CORS restricted to `GET`, `POST`, `OPTIONS` methods only
- [x] API Dockerfile runs as non-root user (`appuser:1001`)
- [x] Health endpoint returns minimal response by default; component details require `X-Health-Detail` header
- [x] Blob path validated against allowlist pattern before TiTiler requests
- [ ] TiTiler CORS configured to frontend domain only (`TITILER_API_CORS_ORIGINS`)
- [ ] PostgreSQL connection uses `sslmode=require`
- [ ] Azure Blob Storage not publicly accessible (private container)
- [ ] Managed identities used for Blob access (no connection strings in TiTiler if possible)
- [ ] Privacy policy page linked from frontend
- [ ] Analytics consent implemented if OQ-10 resolves to opt-in model
