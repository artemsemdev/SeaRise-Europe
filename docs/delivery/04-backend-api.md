# Epic 04 — Backend API Core

| Field          | Value                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Epic ID        | E-04                                                                                               |
| Phase          | 0/1 — bridges foundation and MVP                                                                   |
| Status         | Not Started                                                                                        |
| Effort         | ~7 days                                                                                            |
| Dependencies   | Epic 02 (local Docker Compose environment, PostgreSQL schema), Epic 03 (seed data + COG layers in local storage) |
| Stories        | 7 (S04-01 through S04-07)                                                                          |
| Produces       | Fully functional API that the frontend consumes                                                    |

---

## 1  Objective

Implement the ASP.NET Core Minimal API that serves all five endpoints consumed by the frontend: geocoding, assessment, scenario configuration, methodology metadata, and health. The API must enforce the full domain logic pipeline (geography validation, layer resolution, exposure evaluation, result state determination) and meet all latency, privacy, and observability requirements.

---

## 2  Why This Epic Exists

The API is the only runtime component that contains application logic. The frontend is a presentation layer; TiTiler is an off-the-shelf tile server; PostgreSQL is a data store. Every product requirement that involves computation — geocoding normalization, geography classification, exposure assessment, result state determination — is implemented here. Without this epic, the frontend has nothing to call, and the data pipeline's output (COGs and seed data) has no consumer.

---

## 3  Scope

### 3.1 In Scope

- ASP.NET Core .NET 8+ Minimal API project scaffold with clean layer architecture (HTTP / Application / Domain / Infrastructure).
- Domain layer: `ResultStateDeterminator`, `GeographyClassification`, `ResultState`, `AssessmentResult`, `AssessmentQuery`, `GeocodingCandidate`, `ExposureLayer`, and all supporting types.
- Infrastructure adapters: `PostGisGeographyRepository`, `LayerRepository`, `ScenarioRepository`, `MethodologyRepository`, `NominatimGeocodingClient` (dev), `TiTilerExposureEvaluator`.
- Application service: `AssessmentService` orchestrating the full assessment pipeline with parallel geography checks.
- All five API endpoints: `POST /v1/geocode`, `POST /v1/assess`, `GET /v1/config/scenarios`, `GET /v1/config/methodology`, `GET /health`.
- FluentValidation for all request DTOs.
- CORS configuration (frontend domain only).
- Structured JSON logging (Serilog), correlation ID middleware, standard log events.
- In-process `IMemoryCache` for scenario and methodology config (5-minute TTL).
- Dockerfile for the API container.
- Unit tests (domain layer, 100% branch coverage on `ResultStateDeterminator`) and integration tests (Testcontainers PostgreSQL+PostGIS).

### 3.2 Out of Scope

- Production geocoding provider implementation (OQ-06 — placeholder interface only; `NominatimGeocodingClient` for development).
- Frontend implementation (Epic 05).
- TiTiler container configuration (Epic 02/03).
- Database schema creation or seed data insertion (Epic 02/03).
- CDN, custom domain, or production DNS.
- OpenTelemetry distributed tracing (Phase 2).
- Polly circuit breakers (Phase 2).

---

## 4  Traceability

### 4.1 Product Requirement Traceability

| Requirement | Description                                                |
| ----------- | ---------------------------------------------------------- |
| FR-001      | Location search input                                      |
| FR-002      | Query length validation (1-200 chars)                      |
| FR-004      | Geocoding returns ranked candidates                        |
| FR-005      | Candidate selection                                        |
| FR-009      | Europe geography validation (server-side)                  |
| FR-011      | Coastal zone classification                                |
| FR-012      | Geography-based result state                               |
| FR-014      | Scenario selection                                         |
| FR-015      | Time horizon selection (2030, 2050, 2100)                  |
| FR-016      | Default scenario and horizon on initial load               |
| FR-020      | Result includes scenario, horizon, methodology             |
| FR-033      | Methodology metadata endpoint                              |
| FR-035      | Methodology version in every response                      |
| FR-039      | Error states for provider failures                         |
| BR-001      | Anonymous public access (no authentication)                |
| BR-006      | Preserve geocoding provider rank order                     |
| BR-007      | Maximum 5 geocoding candidates                             |
| BR-008      | Maximum 200 character geocoding input                      |
| BR-010      | Fixed result state taxonomy (5 states)                     |
| BR-011      | No overstatement of exposure results                       |
| BR-014      | No substitution when data is unavailable                   |
| BR-015      | Methodology version always present                         |
| NFR-002     | Geocoding response <=2.5s p95                              |
| NFR-003     | Assessment response <=3.5s p95                             |
| NFR-005     | HTTPS only                                                 |
| NFR-006     | No secrets in client code                                  |
| NFR-007     | No raw address strings in logs                             |
| NFR-011     | Health endpoint for liveness/readiness probes              |
| NFR-013     | Correlation IDs in all requests/responses                  |
| NFR-019     | Stateless runtime                                          |

### 4.2 Architecture Traceability

| Architecture Document                                      | Relevance                                        |
| ---------------------------------------------------------- | ------------------------------------------------ |
| `docs/architecture/03-component-view.md`                   | Layer architecture, all component interfaces     |
| `docs/architecture/06-api-and-contracts.md`                | Endpoint contracts, error model, CORS            |
| `docs/architecture/05-data-architecture.md`                | PostgreSQL schema, read paths, blob layout       |
| `docs/architecture/09-observability-and-operations.md`     | Log events, correlation ID, Serilog config       |
| `docs/architecture/10-testing-strategy.md`                 | Unit/integration test patterns, Testcontainers   |
| `docs/architecture/14-integration-patterns.md`             | Geocoding, TiTiler, PostgreSQL integration       |
| `docs/architecture/07-security-architecture.md`            | Key Vault, managed identity, CORS                |
| `docs/architecture/08-deployment-topology.md`              | Container Apps deployment, Dockerfile            |

---

## 5  Implementation Plan

Work through stories in the following order, chosen to maximize testability at each step:

1. **S04-01 — Initialize ASP.NET Core Minimal API Project.** Scaffold the solution, establish layer boundaries, configure NuGet packages. Everything else depends on this.
2. **S04-02 — Implement Domain Layer.** Pure types and logic with no infrastructure dependencies. Fully unit-testable immediately.
3. **S04-03 — Implement Infrastructure Adapters.** Connect to PostgreSQL (PostGIS queries), TiTiler (HTTP client), geocoding provider (Nominatim for dev). Depends on S04-02 for domain types.
4. **S04-04 — Implement Assessment Service.** Orchestrates the pipeline. Depends on S04-02 (domain) and S04-03 (adapters via interfaces).
5. **S04-05 — Implement API Endpoints and Validation.** Wires everything to HTTP. Depends on S04-04 (assessment service) and S04-03 (repositories for config endpoints).
6. **S04-06 — Implement Structured Logging and Correlation ID Middleware.** Cross-cutting concern layered on top of working endpoints. Can be partially parallelized with S04-05.
7. **S04-07 — Backend Unit and Integration Tests.** Depends on all prior stories. Some tests (domain unit tests) can be written alongside S04-02.

### Execution Order Map

```
S04-01 (Project Scaffold)
  │
  └──► S04-02 (Domain Layer)
         │
         └──► S04-03 (Infrastructure Adapters)
                │
                └──► S04-04 (Assessment Service)
                       │
                       ├──► S04-05 (API Endpoints)
                       │
                       └──► S04-06 (Logging + Correlation IDs)  ◄── parallel with S04-05
                              │
                              └──► S04-07 (Unit + Integration Tests)
```

**Rationale:** The dependency chain follows the layered architecture: domain first (no dependencies), then infrastructure adapters (depend on domain types), then application service (depends on both), then HTTP endpoints and logging (depend on service layer). S04-05 and S04-06 can run in parallel because logging middleware and endpoint wiring are independent concerns. S04-07 must be last because tests exercise all layers together, though domain unit tests can be written incrementally alongside S04-02.

---

## 6  User Stories

---

### S04-01 — Initialize ASP.NET Core Minimal API Project

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S04-01                 |
| Type           | Technical Enabler      |
| Effort         | ~0.5 days              |
| Dependencies   | None                   |

**Statement**

As the engineer maintaining delivery quality, I want the API project scaffolded with clean layer separation, Dockerfile, and NuGet dependencies, so that all subsequent stories have a compilable solution to build on.

**Why**

Every story in this epic adds code to the API project. Without a properly structured solution — correct layer references, dependency direction, NuGet packages, and Docker build — subsequent work has no foundation. Getting the structure right now prevents structural debt that is expensive to fix after code accumulates.

**Scope Notes**

- Create ASP.NET Core .NET 8+ solution with projects or folders enforcing the four-layer architecture: HTTP, Application, Domain, Infrastructure.
- Domain project has no reference to Infrastructure, Application, or HTTP projects.
- Infrastructure project references Domain only (for interface implementations).
- Application project references Domain only (orchestration depends on domain types and interfaces).
- HTTP project (the host) references Application and registers Infrastructure via DI.
- Add NuGet packages: `Npgsql`, `Dapper` (or raw Npgsql), `FluentValidation`, `Serilog.AspNetCore`, `Serilog.Sinks.Console`, `Serilog.Formatting.Compact`, `AspNetCore.HealthChecks.NpgSql`, `AspNetCore.HealthChecks.AzureBlobStorage`, `Microsoft.Extensions.Caching.Memory`.
- Create `Dockerfile` (multi-stage build: SDK build, runtime image).
- Create `appsettings.json` and `appsettings.Development.json` with placeholder configuration for PostgreSQL connection string, TiTiler base URL, geocoding base URL, CORS allowed origins.
- Register DI container wiring in `Program.cs` (services, middleware pipeline skeleton).

**Traceability**

- Requirements: NFR-019 (stateless), NFR-023 (no Kubernetes — Container Apps via Docker image)
- Architecture: `docs/architecture/03-component-view.md` (layer architecture, section 1), `docs/architecture/08-deployment-topology.md` (Dockerfile)

**Implementation Notes**

- Prefer separate projects over folders for layer enforcement — the compiler prevents invalid references.
- Suggested project names: `SeaRise.Api` (host), `SeaRise.Application`, `SeaRise.Domain`, `SeaRise.Infrastructure`.
- The Dockerfile should produce a minimal runtime image (`mcr.microsoft.com/dotnet/aspnet:8.0`).
- Do not add EF Core. The project uses Npgsql and Dapper (or raw Npgsql) for all data access per architecture decision.

**Acceptance Criteria**

1. Solution builds without errors (`dotnet build` succeeds).
2. Domain project has zero references to Infrastructure, Application, or HTTP projects.
3. Dockerfile builds successfully and produces a runnable container image.
4. `Program.cs` contains DI registration skeleton and middleware pipeline skeleton (CORS, health checks, endpoint routing).
5. NuGet packages listed above are referenced in the correct projects.
6. `appsettings.json` contains placeholder configuration keys for all external dependencies.

**Definition of Done**

- Solution committed and builds in CI.
- Layer dependency direction verified by project reference inspection.

**Testing Approach**

- Build verification: `dotnet build` and `docker build` both succeed.

**Evidence Required**

- `dotnet build` output showing zero errors.
- `docker build` output showing successful image creation.
- Project reference listing confirming dependency direction.

---

### S04-02 — Implement Domain Layer

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S04-02                 |
| Type           | Feature                |
| Effort         | ~1 day                 |
| Dependencies   | S04-01                 |

**Statement**

As the system, I need the domain layer implemented with all pure business types and the `ResultStateDeterminator`, so that the assessment pipeline has correct, fully testable decision logic with no infrastructure coupling.

**Why**

The `ResultStateDeterminator` is the most safety-critical logic in the system. It maps every combination of geography classification, layer availability, and exposure evaluation to exactly one of five result states. A wrong mapping displays misleading exposure information to users. Implementing it as a pure function in an isolated domain layer means it can be tested exhaustively without mocking infrastructure, and its correctness is provable before any adapter code exists.

**Scope Notes**

- `ResultState` enum: `ModeledExposureDetected`, `NoModeledExposureDetected`, `DataUnavailable`, `OutOfScope`, `UnsupportedGeography`.
- `GeographyClassification` enum: `InEuropeAndCoastalZone`, `InEuropeOutsideCoastalZone`, `OutsideEurope`.
- `ResultStateDeterminator` static class with `Determine(GeographyClassification, ExposureLayer?, bool?)` method using pattern matching.
- `AssessmentQuery` record: `Latitude`, `Longitude`, `ScenarioId`, `HorizonYear`.
- `AssessmentResult` record: `RequestId`, `ResultState`, `Location`, `Scenario`, `Horizon`, `MethodologyVersion`, `LayerTileUrlTemplate` (nullable), `LegendSpec` (nullable), `GeneratedAt`.
- `GeocodingCandidate` record: `Rank`, `Label`, `Country`, `Latitude`, `Longitude`, `DisplayContext`.
- `ExposureLayer` record: `Id`, `ScenarioId`, `HorizonYear`, `MethodologyVersion`, `BlobPath`, `LegendColormap`.
- `Scenario`, `Horizon`, `MethodologyVersion` domain types matching database schema.
- Domain interfaces: `IGeographyRepository`, `ILayerResolver`, `IExposureEvaluator`, `IGeocodingService`, `IScenarioRepository`, `IMethodologyRepository`.
- No `using` statements referencing Infrastructure, Npgsql, HTTP, or any I/O namespace.

**Traceability**

- Requirements: BR-010 (fixed result state taxonomy), BR-011 (no overstatement), BR-014 (no substitution), BR-015 (methodology version always present), FR-020 (scenario + horizon in result)
- Architecture: `docs/architecture/03-component-view.md` (sections 2-5), `docs/architecture/13-domain-model.md`

**Implementation Notes**

- The `ResultStateDeterminator.Determine` method must match the pattern-matching implementation in `docs/architecture/03-component-view.md` section 2 exactly. The safe fallback for unmatched patterns is `DataUnavailable`.
- All domain types should be records (immutable value objects).
- Interfaces defined in the domain layer are implemented in the infrastructure layer — this is the dependency inversion that keeps the domain pure.

**Acceptance Criteria**

1. `ResultStateDeterminator.Determine` handles all 8 meaningful input combinations per `docs/architecture/10-testing-strategy.md` section 2.1.
2. All domain types compile with no references to Infrastructure or HTTP namespaces.
3. `AssessmentResult` record includes `MethodologyVersion` as a non-nullable field.
4. `ResultState` enum contains exactly 5 values matching BR-010.
5. `GeographyClassification` enum contains exactly 3 values.
6. All interfaces (`IGeographyRepository`, `ILayerResolver`, `IExposureEvaluator`, `IGeocodingService`, `IScenarioRepository`, `IMethodologyRepository`) are defined in the domain project.

**Definition of Done**

- Domain layer compiles independently (`dotnet build SeaRise.Domain`).
- No infrastructure namespace references in the domain project.
- `ResultStateDeterminator` unit tests pass with 100% branch coverage.

**Testing Approach**

- Unit tests: `ResultStateDeterminator` with all 8 combinations from `docs/architecture/10-testing-strategy.md` section 2.1. Use `[Theory]`/`[InlineData]` parameterized tests.

**Evidence Required**

- Unit test run output showing all `ResultStateDeterminator` combinations pass.
- Branch coverage report confirming 100% on `ResultStateDeterminator`.

---

### S04-03 — Implement Infrastructure Adapters

| Field          | Value                             |
| -------------- | --------------------------------- |
| ID             | S04-03                            |
| Type           | Feature                           |
| Effort         | ~1.5 days                         |
| Dependencies   | S04-02 (domain interfaces and types) |

**Statement**

As the system, I need all infrastructure adapters implemented against the domain interfaces, so that the application layer can orchestrate real database queries, geocoding calls, and TiTiler point lookups.

**Why**

The domain layer defines what the system needs (interfaces); the infrastructure layer provides how. Without concrete adapter implementations, the assessment pipeline and geocoding flow cannot execute. Each adapter encapsulates one external dependency — PostgreSQL, TiTiler, geocoding provider, or the scenario/methodology config store — keeping provider-specific logic isolated from business rules.

**Scope Notes**

- `PostGisGeographyRepository` implementing `IGeographyRepository`: parameterized `ST_Within` queries against `geography_boundaries` table for both Europe and coastal zone checks.
- `LayerRepository` implementing `ILayerResolver`: query `layers` table with composite index lookup joining active `methodology_versions`.
- `ScenarioRepository` implementing `IScenarioRepository`: query `scenarios` and `horizons` tables. Wrap with `IMemoryCache` (5-minute TTL).
- `MethodologyRepository` implementing `IMethodologyRepository`: query `methodology_versions WHERE is_active = true`. Wrap with `IMemoryCache` (5-minute TTL).
- `NominatimGeocodingClient` implementing `IGeocodingService`: Nominatim public API adapter for development use. Normalize response to `GeocodingCandidate`. Enforce max 5 candidates (BR-007), preserve rank order (BR-006).
- `TiTilerExposureEvaluator` implementing `IExposureEvaluator`: HTTP call to TiTiler `/cog/point/{lng},{lat}` endpoint. Parse pixel value, return `bool`.
- Register all adapters in the DI container.
- Configure `HttpClient` instances with appropriate timeouts: geocoding 5s, TiTiler 3s.

**Traceability**

- Requirements: BR-006 (preserve rank), BR-007 (max 5 candidates), NFR-002 (geocoding <=2.5s), NFR-003 (assessment <=3.5s)
- Architecture: `docs/architecture/03-component-view.md` (sections 2-4), `docs/architecture/14-integration-patterns.md` (sections 2, 3, 5), `docs/architecture/05-data-architecture.md` (schema, read paths)

**Implementation Notes**

- All PostGIS queries must use parameterized SQL (no string interpolation) per `docs/architecture/14-integration-patterns.md` section 5.2.
- `NominatimGeocodingClient` must respect Nominatim usage policy (1 request per second, custom User-Agent). This is acceptable for development only.
- `TiTilerExposureEvaluator` must construct the COG URL from `layer.BlobPath` using the GDAL VSIAZ URI scheme (`az://geospatial/{blobPath}`) per `docs/architecture/14-integration-patterns.md` section 3.4.
- Pixel value interpretation: `1` = exposed, `0` = not exposed, `null`/NoData = not exposed. Adjust if OQ-05 resolution changes the threshold.
- `GeocodingProviderException` for upstream failures, caught by the HTTP layer and mapped to `GEOCODING_PROVIDER_ERROR`.
- PostgreSQL connection pool: max 20, min 1, per `docs/architecture/14-integration-patterns.md` section 5.1.

**Acceptance Criteria**

1. `PostGisGeographyRepository` executes parameterized `ST_Within` queries for both `europe` and `coastal_analysis_zone` boundaries.
2. `LayerRepository` resolves layers using the composite index on `(scenario_id, horizon_year, methodology_version)` with `layer_valid = true` and active methodology version.
3. `NominatimGeocodingClient` returns at most 5 candidates with provider rank preserved.
4. `TiTilerExposureEvaluator` calls `/cog/point/{lng},{lat}` and correctly interprets pixel value 1 as exposed, 0 as not exposed.
5. `ScenarioRepository` and `MethodologyRepository` use `IMemoryCache` with 5-minute TTL.
6. `HttpClient` timeout is 5s for geocoding and 3s for TiTiler.
7. `GeocodingProviderException` is thrown on upstream HTTP failures or timeouts.

**Definition of Done**

- All adapters registered in DI and compile against domain interfaces.
- Configuration keys for connection strings, base URLs, and API keys are read from `IConfiguration`.

**Testing Approach**

- Integration tests (S04-07) against Testcontainers PostgreSQL+PostGIS for repository adapters.
- Unit tests for geocoding candidate normalization (truncation to 5, rank preservation).

**Evidence Required**

- Adapter registration in `Program.cs` showing DI wiring.
- Geocoding normalization unit test output.

---

### S04-04 — Implement Assessment Service

| Field          | Value                                             |
| -------------- | ------------------------------------------------- |
| ID             | S04-04                                            |
| Type           | Feature                                           |
| Effort         | ~1 day                                            |
| Dependencies   | S04-02 (domain types), S04-03 (adapter interfaces)|

**Statement**

As the system, I need the `AssessmentService` implemented to orchestrate the full exposure assessment pipeline, so that a single call from the API endpoint produces a correct `AssessmentResult` for any coordinate, scenario, and horizon combination.

**Why**

The assessment pipeline is the core use case of the product. It coordinates four sequential concerns — geography validation, layer resolution, exposure evaluation, and result state determination — into a single coherent flow. The orchestration logic determines when to short-circuit (outside Europe: stop immediately), when to skip steps (no layer: skip TiTiler), and when to run steps in parallel (Europe check and coastal zone check via `Task.WhenAll`). Getting this orchestration wrong produces incorrect result states or unnecessary latency.

**Scope Notes**

- Implement `AssessmentService` in the Application layer, implementing `IAssessmentService`.
- Pipeline steps in order: geography validation, layer resolution, exposure evaluation, `ResultStateDeterminator`.
- Run `IsWithinEuropeAsync` and `IsWithinCoastalZoneAsync` in parallel via `Task.WhenAll` to save ~20ms.
- Short-circuit on `OutsideEurope` before layer resolution.
- Short-circuit on `InEuropeOutsideCoastalZone` before layer resolution.
- Short-circuit on `null` layer (DataUnavailable) before exposure evaluation.
- Assemble `AssessmentResult` with mandatory fields: `RequestId`, `ResultState`, `Location`, `Scenario`, `Horizon`, `MethodologyVersion`, `GeneratedAt`.
- `LayerTileUrlTemplate` is non-null only when `ResultState == ModeledExposureDetected`.
- `MethodologyVersion` is always present regardless of result state.

**Traceability**

- Requirements: FR-020 (result includes scenario/horizon/methodology), FR-035 (methodology version always present), BR-010 (fixed result states), BR-011 (no overstatement), BR-014 (no substitution), NFR-003 (assessment <=3.5s)
- Architecture: `docs/architecture/03-component-view.md` (section 2, Assessment Module, sequence diagram in section 6)

**Implementation Notes**

- The parallel geography check pattern:
  ```csharp
  var europeTask = _geographyRepo.IsWithinEuropeAsync(lat, lng, ct);
  var coastalTask = _geographyRepo.IsWithinCoastalZoneAsync(lat, lng, ct);
  await Task.WhenAll(europeTask, coastalTask);
  ```
  This saves ~20ms by running both PostGIS queries concurrently. If the Europe check fails, the coastal result is discarded.
- The `AssessmentService` should accept the `requestId` (correlation ID) from the HTTP layer so it can include it in the result.
- The active `MethodologyVersion` string should be fetched once per request from `IMethodologyRepository` (cached at 5-minute TTL, so this is effectively free).
- Scenario display name and horizon display label should be fetched from `IScenarioRepository` for inclusion in the response.

**Acceptance Criteria**

1. `AssessAsync` returns `UnsupportedGeography` without calling `ILayerResolver` or `IExposureEvaluator` when the coordinate is outside Europe.
2. `AssessAsync` returns `OutOfScope` without calling `ILayerResolver` or `IExposureEvaluator` when the coordinate is in Europe but outside the coastal zone.
3. `AssessAsync` returns `DataUnavailable` without calling `IExposureEvaluator` when no valid layer exists for the scenario+horizon combination.
4. `AssessAsync` returns `ModeledExposureDetected` when geography is valid, layer exists, and exposure evaluator returns `true`.
5. `AssessAsync` returns `NoModeledExposureDetected` when geography is valid, layer exists, and exposure evaluator returns `false`.
6. Every `AssessmentResult` includes a non-null `MethodologyVersion`, `Scenario`, `Horizon`, and `GeneratedAt`.
7. `IsWithinEuropeAsync` and `IsWithinCoastalZoneAsync` execute concurrently (verified by mock invocation timing or call ordering in tests).

**Definition of Done**

- `AssessmentService` compiles and is registered in DI.
- All 5 result state paths are reachable and produce correctly assembled `AssessmentResult` records.

**Testing Approach**

- Unit tests with mocked `IGeographyRepository`, `ILayerResolver`, `IExposureEvaluator`, `IScenarioRepository`, `IMethodologyRepository`. Verify short-circuit behavior: when geography fails, layer resolver and exposure evaluator are never invoked.

**Evidence Required**

- Unit test output showing all 5 result state paths pass.
- Verification that short-circuit tests confirm downstream dependencies are not called.

---

### S04-05 — Implement API Endpoints and Validation

| Field          | Value                                         |
| -------------- | --------------------------------------------- |
| ID             | S04-05                                        |
| Type           | Feature                                       |
| Effort         | ~1 day                                        |
| Dependencies   | S04-04 (assessment service), S04-03 (repositories for config endpoints) |

**Statement**

As the system, I need all five API endpoints implemented with request validation, error handling, and response shaping that exactly match `docs/architecture/06-api-and-contracts.md`, so that the frontend can consume a stable, documented API contract.

**Why**

The API contract is the integration surface between backend and frontend. Every field name, status code, error code, and null/non-null rule in the contract document is a promise to the frontend. Deviating from the contract forces frontend rework or produces runtime bugs. Implementing all five endpoints with validation in a single story ensures the contract is delivered atomically and can be verified against the architecture document in one pass.

**Scope Notes**

- `POST /v1/geocode`: Accept `{ query }`, validate 1-200 chars, return `{ requestId, candidates[] }`. Error: 400 `VALIDATION_ERROR`, 500 `GEOCODING_PROVIDER_ERROR`.
- `POST /v1/assess`: Accept `{ latitude, longitude, scenarioId, horizonYear }`, validate ranges and existence. Return `{ requestId, resultState, location, scenario, horizon, methodologyVersion, layerTileUrlTemplate, legendSpec, generatedAt }`. Error: 400 `VALIDATION_ERROR`/`UNKNOWN_SCENARIO`/`UNKNOWN_HORIZON`, 500 `INTERNAL_ERROR`.
- `GET /v1/config/scenarios`: Return scenario list, horizon list, defaults. Cached.
- `GET /v1/config/methodology`: Return active methodology metadata.
- `GET /health`: Health checks for PostgreSQL + Blob Storage. 200 healthy, 503 unhealthy.
- Standard error envelope: `{ requestId, error: { code, message, field } }`.
- FluentValidation validators: `GeocodeRequestValidator`, `AssessRequestValidator`.
- CORS policy: allow frontend domain from `CORS_ALLOWED_ORIGINS` environment variable.
- Request/response DTO types in the HTTP layer, separate from domain types.

**Traceability**

- Open Questions consumed: OQ-06 (geocoding provider — dev fallback to Nominatim)
- Requirements: FR-001, FR-002, FR-004, FR-014, FR-015, FR-016, FR-020, FR-033, FR-035, FR-039, BR-001, BR-008, BR-010, NFR-005, NFR-011
- Architecture: `docs/architecture/06-api-and-contracts.md` (full contract reference), `docs/architecture/03-component-view.md` (section 4, validation boundaries)

**Implementation Notes**

- Use Minimal API `.MapPost()` / `.MapGet()` with FluentValidation endpoint filters or `.WithValidator<T>()` extension per `docs/architecture/06-api-and-contracts.md` section 5.
- Geography validation (Europe/coastal) is not in the HTTP layer — it returns result states via the assessment service, not HTTP errors.
- `OutOfScope`, `UnsupportedGeography`, and `DataUnavailable` return HTTP 200 OK. They are valid result states, not errors.
- `layerTileUrlTemplate` is non-null only for `ModeledExposureDetected`. For all other result states, it must be `null`.
- The `requestId` in every response body must match the `X-Correlation-Id` header value (wired from correlation ID middleware in S04-06).
- CORS configuration per `docs/architecture/06-api-and-contracts.md` section 7: read allowed origins from environment variable, split on comma.
- Health checks: register `AddNpgsql` and `AddAzureBlobStorage` per `docs/architecture/03-component-view.md` section 2 (Health Module).
- Map `GeocodingProviderException` to HTTP 500 `GEOCODING_PROVIDER_ERROR`. Map unhandled exceptions to HTTP 500 `INTERNAL_ERROR`.

**Acceptance Criteria**

1. `POST /v1/geocode` with empty query returns 400 with error code `VALIDATION_ERROR`.
2. `POST /v1/geocode` with query > 200 chars returns 400 with error code `VALIDATION_ERROR`.
3. `POST /v1/assess` with latitude outside [-90, 90] returns 400 `VALIDATION_ERROR`.
4. `POST /v1/assess` with unknown scenario ID returns 400 `UNKNOWN_SCENARIO`.
5. `POST /v1/assess` with horizon year not in {2030, 2050, 2100} returns 400 `UNKNOWN_HORIZON`.
6. `POST /v1/assess` for a non-European coordinate returns 200 with `resultState: "UnsupportedGeography"`.
7. `GET /v1/config/scenarios` returns scenario list with `defaults.scenarioId` and `defaults.horizonYear`.
8. `GET /v1/config/methodology` returns `whatItDoes`, `whatItDoesNotAccountFor`, and `methodologyVersion`.
9. `GET /health` returns 200 when PostgreSQL and Blob Storage are healthy, 503 when either is unhealthy.
10. All error responses use the standard error envelope: `{ requestId, error: { code, message } }`.
11. CORS allows requests from the configured frontend domain only.

**Definition of Done**

- All 5 endpoints respond correctly to valid and invalid requests.
- Response shapes match `docs/architecture/06-api-and-contracts.md` exactly.
- FluentValidation rules cover all documented constraints.

**Testing Approach**

- Integration tests (S04-07) using `WebApplicationFactory` with real PostgreSQL (Testcontainers) and mocked TiTiler.

**Evidence Required**

- Curl or test output showing each endpoint's success and error responses.
- Response bodies compared against `docs/architecture/06-api-and-contracts.md` examples.

---

### S04-06 — Implement Structured Logging and Correlation ID Middleware

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S04-06                 |
| Type           | Technical Enabler      |
| Effort         | ~0.5 days              |
| Dependencies   | S04-05 (endpoints exist to instrument) |

**Statement**

As the engineer maintaining delivery quality, I want structured JSON logging with correlation IDs and privacy-safe log events, so that every request is traceable through the system and no raw address strings appear in any log output.

**Why**

Without structured logging, diagnosing production failures requires guessing. Without correlation IDs, linking a user-visible error to its server-side cause requires timestamp-based log archaeology. Without privacy enforcement, a single log statement containing a raw address string violates NFR-007 and BR-016. This story makes the system observable while keeping it privacy-compliant.

**Scope Notes**

- Correlation ID middleware: read `X-Correlation-Id` from request header or generate UUID v4 with `req_` prefix. Inject into `ILogger` scope. Return in `X-Correlation-Id` response header.
- Serilog configuration: structured JSON formatter, write to stdout, enrich with `service: "searise-api"`.
- Minimum log level: `Information` (override `Microsoft.AspNetCore` to `Warning`).
- Implement all log events from `docs/architecture/09-observability-and-operations.md` section 2.3:
  - `GeocodeRequested` (Debug), `GeocodeCompleted` (Info), `GeocodeProviderError` (Error).
  - `AssessmentRequested` (Debug), `AssessmentCompleted` (Info), `AssessmentError` (Error).
  - `GeographyCheckCompleted` (Debug), `LayerResolved` (Debug), `LayerNotFound` (Info), `TilerQueryCompleted` (Debug).
  - `HealthCheckCompleted` (Debug).
- Privacy enforcement: verify that query strings, latitude, and longitude never appear in any log field. Log `candidateCount`, `resultState`, `scenarioId`, `horizonYear`, `countryCode`, `durationMs` instead.

**Traceability**

- Requirements: NFR-007 (no raw address logging), NFR-013 (correlation IDs), NFR-008 (structured logging)
- Architecture: `docs/architecture/09-observability-and-operations.md` (sections 2.1-2.4)

**Implementation Notes**

- The correlation ID middleware implementation is specified in `docs/architecture/09-observability-and-operations.md` section 2.2. Follow it exactly.
- The `requestId` in API response bodies must use the same correlation ID value as the log scope. The middleware should store the correlation ID in `HttpContext.Items` for endpoint handlers to read.
- Use event-specific log statements (not generic request/response body dump middleware) to prevent accidental logging of sensitive fields.
- `durationMs` should be measured using `Stopwatch` or `System.Diagnostics.Activity` in the assessment service and geocoding service.

**Acceptance Criteria**

1. Every API response body contains a `requestId` field.
2. Every log entry emitted during a request contains the same `requestId`.
3. `X-Correlation-Id` response header matches the `requestId` in the response body.
4. When `X-Correlation-Id` is sent in the request, it is reused (not replaced).
5. When `X-Correlation-Id` is absent from the request, a new UUID is generated.
6. Serilog writes structured JSON to stdout.
7. A successful geocode request produces a `GeocodeCompleted` log event with `candidateCount` and `durationMs` but no query string.
8. A successful assessment request produces an `AssessmentCompleted` log event with `resultState`, `scenarioId`, `horizonYear`, `durationMs` but no latitude or longitude.
9. Log level for `Microsoft.AspNetCore` is `Warning` (no framework noise at `Information` level).

**Definition of Done**

- Structured JSON logs visible in container stdout.
- Grep of all log statements in the codebase confirms zero instances of raw address, latitude, or longitude being logged.

**Testing Approach**

- Manual verification: run the API locally, issue requests, inspect stdout JSON output.
- Code review: audit all `_logger.Log*` calls for prohibited fields.

**Evidence Required**

- Sample stdout log output showing structured JSON with `requestId`, event name, and properties.
- Audit result confirming no raw address or coordinate fields in any log statement.

---

### S04-07 — Backend Unit and Integration Tests

| Field          | Value                                                 |
| -------------- | ----------------------------------------------------- |
| ID             | S04-07                                                |
| Type           | Quality Assurance                                     |
| Effort         | ~1.5 days                                             |
| Dependencies   | S04-01 through S04-06 (all implementation complete)   |

**Statement**

As the engineer maintaining delivery quality, I want comprehensive unit and integration tests covering the domain layer, assessment pipeline, infrastructure adapters, and API endpoints, so that regressions are caught automatically and the system's correctness is provable.

**Why**

The assessment pipeline produces results that users interpret as exposure information. An untested regression that changes a result state mapping, breaks a geography check, or silently drops the methodology version from a response undermines the product's credibility. The `ResultStateDeterminator` requires 100% branch coverage because every branch maps to a different user-visible outcome. Integration tests against a real PostgreSQL+PostGIS instance (via Testcontainers) catch query bugs that mocked tests miss.

**Scope Notes**

- **Domain unit tests:**
  - `ResultStateDeterminator`: all 8 combinations per `docs/architecture/10-testing-strategy.md` section 2.1. 100% branch coverage.
  - Geocoding candidate normalization: truncation to 5 (BR-007), rank preservation (BR-006).
  - Input validation: geocode query length bounds, assess coordinate bounds, horizon year validation.

- **Application unit tests (mocked dependencies):**
  - `AssessmentService`: all 5 result state paths. Verify short-circuit behavior (downstream dependencies not called when upstream check fails).
  - `AssessmentService`: verify `MethodologyVersion` is always present in every result (FR-035).
  - `AssessmentService`: verify `Scenario` and `Horizon` are always present (FR-020).

- **Integration tests (Testcontainers PostgreSQL+PostGIS):**
  - `PostGisGeographyRepository`: Amsterdam is in Europe, New York is not. Prague is in Europe but not in coastal zone (requires seeded geometry).
  - `LayerRepository`: resolves correct layer for valid scenario+horizon+active version, returns null for invalid combination or `layer_valid = false`.
  - `ScenarioRepository`: returns seeded scenarios with correct defaults.

- **API endpoint integration tests (WebApplicationFactory + Testcontainers):**
  - `POST /v1/geocode` valid query returns 200 with candidates.
  - `POST /v1/geocode` empty query returns 400 `VALIDATION_ERROR`.
  - `POST /v1/assess` outside Europe returns 200 `UnsupportedGeography`.
  - `POST /v1/assess` unknown scenario returns 400 `UNKNOWN_SCENARIO`.
  - `POST /v1/assess` response always includes `requestId`.
  - `GET /v1/config/scenarios` returns horizons containing 2030, 2050, 2100 (FR-015).
  - `GET /health` returns 200 when database is healthy.

**Traceability**

- Requirements: BR-006, BR-007, BR-008, BR-010, BR-014, FR-015, FR-020, FR-035, NFR-011
- Architecture: `docs/architecture/10-testing-strategy.md` (sections 2, 3), `docs/architecture/03-component-view.md`

**Implementation Notes**

- Use `Testcontainers.PostgreSql` NuGet package to spin up a PostGIS-enabled PostgreSQL container. The `TestDbFixture` should run `init.sql` to create the schema and seed test data (scenarios, horizons, methodology version, Europe boundary geometry, coastal zone geometry).
- Coastal zone geometry in tests can be a simplified bounding box covering European coastal areas until the actual geometry from Epic 01/S01-03 is available.
- For API integration tests, mock the geocoding provider and TiTiler HTTP clients (they are external dependencies not under test). Use `WebApplicationFactory` with overridden service registrations.
- Organize tests by category: `[Trait("Category", "Unit")]` and `[Trait("Category", "Integration")]` so CI can run them separately.
- Use xUnit for the test framework.

**Acceptance Criteria**

1. `ResultStateDeterminator` has 100% branch coverage with all 8 combinations passing.
2. At least 3 `AssessmentService` unit tests verify short-circuit behavior (downstream mocks not invoked).
3. At least 3 integration tests verify `PostGisGeographyRepository` against real PostGIS (Testcontainers).
4. At least 3 integration tests verify `LayerRepository` against real PostgreSQL.
5. At least 5 API endpoint integration tests pass using `WebApplicationFactory`.
6. `GET /health` test confirms 200 when database is healthy.
7. All tests pass in CI (`dotnet test` exits 0).

**Definition of Done**

- All tests pass locally and in CI.
- `ResultStateDeterminator` branch coverage confirmed at 100%.
- Test categories allow separate unit and integration test execution.

**Testing Approach**

- This story is the testing story. Verification is that all tests pass and coverage targets are met.

**Evidence Required**

- `dotnet test` output showing all tests pass.
- Branch coverage report for `ResultStateDeterminator` showing 100%.
- CI pipeline output showing green test run.

---

## 7  Technical Deliverables

| Deliverable                                        | Format                          | Produced By |
| -------------------------------------------------- | ------------------------------- | ----------- |
| ASP.NET Core solution with 4-layer architecture    | C# solution (committed)         | S04-01      |
| Dockerfile (multi-stage build)                     | Dockerfile (committed)          | S04-01      |
| Domain types and `ResultStateDeterminator`         | C# (committed)                  | S04-02      |
| Infrastructure adapters (6 implementations)        | C# (committed)                  | S04-03      |
| `AssessmentService` orchestration                  | C# (committed)                  | S04-04      |
| 5 API endpoints with FluentValidation              | C# (committed)                  | S04-05      |
| Correlation ID middleware + Serilog configuration   | C# (committed)                  | S04-06      |
| Unit test suite (~30+ tests)                       | C# xUnit (committed)            | S04-07      |
| Integration test suite (~15+ tests)                | C# xUnit + Testcontainers       | S04-07      |

---

## 8  Data, API, and Infrastructure Impact

- **Database:** Read-only at runtime. Queries `scenarios`, `horizons`, `methodology_versions`, `layers`, and `geography_boundaries` tables. No schema changes — schema is created in Epic 02, seed data inserted in Epic 03.
- **API:** This epic creates the API. All five endpoints defined in `docs/architecture/06-api-and-contracts.md` are implemented.
- **Blob Storage:** Read-only. The `TiTilerExposureEvaluator` constructs blob URLs for TiTiler to read. The health check verifies blob container reachability.
- **Infrastructure:** Consumes the local PostgreSQL and local blob storage provisioned in Epic 02 via Docker Compose. The Dockerfile produced here is built locally and tested via Docker Compose. Azure Container Apps deployment happens in Epic 08.

---

## 9  Security and Privacy

- No authentication required (BR-001 — anonymous public access).
- All secrets (PostgreSQL connection string, geocoding API key, blob storage connection string) read from environment variables sourced from Azure Key Vault. No secrets in source code or Docker images.
- CORS restricts API access to the frontend domain only.
- Raw address strings (geocoding query input) are never logged, stored, or persisted (NFR-007, BR-016).
- Coordinates are used for the duration of a request only and never persisted in any user-associated store.
- All PostGIS queries use parameterized SQL to prevent injection.
- HTTPS is enforced at the Container Apps ingress level (NFR-005).

---

## 10  Observability

- Structured JSON logs emitted to stdout, routed to Azure Log Analytics via Container Apps.
- Every request gets a correlation ID (`requestId`) propagated through all log entries and returned in the response.
- Log events follow the taxonomy in `docs/architecture/09-observability-and-operations.md` section 2.3.
- `durationMs` captured for geocoding and assessment operations to support NFR-002 and NFR-003 compliance measurement.
- `/health` endpoint enables Azure Container Apps liveness and readiness probes.
- No raw addresses or precise coordinates in any log field.

---

## 11  Testing

| Story   | Testing Approach                                                                  |
| ------- | --------------------------------------------------------------------------------- |
| S04-01  | Build verification: `dotnet build`, `docker build`                                |
| S04-02  | Unit tests: `ResultStateDeterminator` 100% branch coverage (8 combinations)       |
| S04-03  | Integration tests (S04-07): repository adapters against Testcontainers PostgreSQL  |
| S04-04  | Unit tests: `AssessmentService` with mocked dependencies (5 result state paths)   |
| S04-05  | Integration tests (S04-07): API endpoints via `WebApplicationFactory`             |
| S04-06  | Manual verification: structured JSON stdout inspection, log audit for prohibited fields |
| S04-07  | Self-verifying: all tests pass, 100% branch coverage on `ResultStateDeterminator` |

---

## 12  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| TiTiler `/point` endpoint latency exceeds budget (~200ms) in practice | Medium | Medium | Measure during integration testing. If too slow, evaluate direct GDAL query (Option B) or pre-materialized lookup (Option C) per `docs/architecture/03-component-view.md` section 2. |
| Nominatim rate limiting blocks development workflow | Low | Medium | Use a local Nominatim instance via Docker or cache responses during development. |
| PostGIS `ST_Within` performance degrades with complex coastal zone geometry | Medium | Low | Simplify geometry (reduce vertex count) if query time exceeds 20ms. GIST index is already specified. |
| Testcontainers PostGIS image adds significant CI time | Low | Medium | Use a dedicated CI step with cached Docker layers. Time-box integration tests. |
| Production geocoding provider (OQ-06) requires adapter changes that invalidate the interface | Medium | Low | The `IGeocodingService` interface is stable. Only the implementation changes. If the response format requires new fields, extend `GeocodingCandidate` without breaking existing consumers. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| Epic 02 has provisioned PostgreSQL with PostGIS enabled and all 5 tables created. | API cannot start or pass health checks. Block until Epic 02 completes S02-03. |
| Epic 03 has seeded scenario, horizon, methodology, geography boundary, and layer data. | Config endpoints return empty results; assessment pipeline returns `DataUnavailable` for all queries. Seed data must exist before meaningful testing. |
| TiTiler container is running and accessible at the configured base URL. | `IExposureEvaluator` calls fail. Assessment returns `INTERNAL_ERROR`. TiTiler can be mocked in integration tests. |
| Binary exposure methodology is confirmed (OQ-05). | If continuous, `TiTilerExposureEvaluator` pixel interpretation and `ResultStateDeterminator` logic require adjustment. Impact is localized to two components. |
| .NET 8 LTS is the target framework. | If .NET 9 is required, minor API surface changes may apply. Migration is straightforward. |

---

## 13  Epic Acceptance Criteria

1. `POST /v1/geocode` accepts free-text queries, validates input (1-200 chars), and returns 0-5 ranked candidates.
2. `POST /v1/assess` evaluates coastal exposure and returns one of the 5 fixed result states for any valid input.
3. `POST /v1/assess` returns `UnsupportedGeography` for non-European coordinates and `OutOfScope` for inland European coordinates, both as HTTP 200 OK.
4. Every assessment response includes `methodologyVersion`, `scenario`, `horizon`, and `generatedAt`.
5. `GET /v1/config/scenarios` returns the scenario list, horizon list, and defaults.
6. `GET /v1/config/methodology` returns the active methodology metadata.
7. `GET /health` returns 200 when PostgreSQL and Blob Storage are healthy, 503 when either is unhealthy.
8. All error responses use the standard error envelope with documented error codes.
9. Structured JSON logs are emitted to stdout with correlation IDs. No raw addresses or coordinates appear in any log.
10. `ResultStateDeterminator` has 100% branch coverage.
11. Integration tests pass against real PostgreSQL+PostGIS via Testcontainers.
12. API container image builds and runs via Dockerfile.

---

## 14  Definition of Done

- All 7 user stories completed with evidence.
- All 5 API endpoints respond correctly to valid and invalid inputs.
- Response shapes match `docs/architecture/06-api-and-contracts.md` exactly.
- `ResultStateDeterminator` has 100% branch coverage.
- Integration tests pass against Testcontainers PostgreSQL+PostGIS.
- Structured JSON logging confirmed with correlation IDs.
- Log audit confirms no raw address or coordinate fields in any log statement.
- Docker image builds and runs.
- No unresolved blocker within this epic's scope.

---

## 15  Demo and Evidence Required

| Evidence                                                  | Location (expected)                                  |
| --------------------------------------------------------- | ---------------------------------------------------- |
| `dotnet build` and `docker build` output                  | CI pipeline artifacts                                |
| Curl output: `POST /v1/geocode` (valid + invalid)        | S04-05 / S04-07 test evidence                        |
| Curl output: `POST /v1/assess` (all 5 result states)     | S04-05 / S04-07 test evidence                        |
| Curl output: `GET /v1/config/scenarios`                   | S04-05 / S04-07 test evidence                        |
| Curl output: `GET /v1/config/methodology`                 | S04-05 / S04-07 test evidence                        |
| Curl output: `GET /health` (healthy + unhealthy)          | S04-05 / S04-07 test evidence                        |
| Structured JSON log sample (stdout)                       | S04-06 evidence                                      |
| `ResultStateDeterminator` test output (100% branch)       | S04-07 test evidence                                 |
| Integration test output (Testcontainers)                  | S04-07 CI pipeline output                            |
| Log audit: no raw addresses or coordinates                | S04-06 code review evidence                          |
