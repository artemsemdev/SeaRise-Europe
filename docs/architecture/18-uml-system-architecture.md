# UML System Architecture

| Field | Value |
|---|---|
| **Document** | UML System Architecture Diagrams |
| **Version** | 0.1-draft |
| **Last Updated** | 2026-03-31 |
| **Status** | Draft |

> All diagrams use Mermaid notation. Render with any Mermaid-compatible viewer (GitHub, VS Code preview, mermaid.live).

---

## Table of Contents

1. [System Context Diagram](#1-system-context-diagram)
2. [Container Diagram](#2-container-diagram)
3. [Component Diagram — API](#3-component-diagram--api)
4. [Component Diagram — Frontend](#4-component-diagram--frontend)
5. [Class Diagram — Domain Model](#5-class-diagram--domain-model)
6. [Class Diagram — Infrastructure Interfaces](#6-class-diagram--infrastructure-interfaces)
7. [Sequence Diagram — Assessment Happy Path](#7-sequence-diagram--assessment-happy-path)
8. [Sequence Diagram — Geocoding Flow](#8-sequence-diagram--geocoding-flow)
9. [Sequence Diagram — Scenario/Horizon Change](#9-sequence-diagram--scenariohorizon-change)
10. [State Machine — Frontend Application Phase](#10-state-machine--frontend-application-phase)
11. [Deployment Diagram](#11-deployment-diagram)
12. [Activity Diagram — Offline Geospatial Pipeline](#12-activity-diagram--offline-geospatial-pipeline)
13. [Package Diagram — Layered Architecture](#13-package-diagram--layered-architecture)

---

## 1. System Context Diagram

Shows SeaRise Europe and its external actors and systems.

```mermaid
C4Context
    title System Context — SeaRise Europe

    Person(user, "Public User", "Anonymous visitor exploring coastal sea-level exposure in Europe")

    System(searise, "SeaRise Europe", "Web application that assesses coastal sea-level exposure for European locations under IPCC AR6 scenarios")

    System_Ext(geocoding, "Azure Maps Search", "Resolves free-text addresses to coordinates (ADR-019)")
    System_Ext(basemap, "Azure Maps", "Serves Light vector tiles for interactive map (ADR-020)")
    System_Ext(ipcc, "IPCC AR6 Projections", "Sea-level rise projection data (NetCDF, offline pipeline input)")
    System_Ext(copernicus, "Copernicus DEM GLO-30", "Digital elevation model at ~30m resolution (offline pipeline input)")

    Rel(user, searise, "Searches locations, views exposure results", "HTTPS")
    Rel(searise, geocoding, "Geocodes user queries", "HTTPS REST")
    Rel(searise, basemap, "Loads map tiles", "HTTPS")
    Rel_L(ipcc, searise, "Provides SLR projections", "Offline download")
    Rel_L(copernicus, searise, "Provides elevation data", "Offline download")
```

---

## 2. Container Diagram

Shows the runtime containers, managed services, and their interactions.

```mermaid
C4Container
    title Container Diagram — SeaRise Europe

    Person(user, "Public User")

    Container_Boundary(searise, "SeaRise Europe") {
        Container(frontend, "Frontend", "Next.js 14+, MapLibre GL JS, deck.gl", "Interactive web UI: search, map, results, methodology panel")
        Container(api, "API", "ASP.NET Core .NET 8+, Minimal API", "Stateless backend: geocoding proxy, geography validation, assessment pipeline")
        Container(tiler, "Tiler", "TiTiler / FastAPI, GDAL", "Serves XYZ map tiles and point queries from COG raster files")
        ContainerDb(postgres, "PostgreSQL + PostGIS", "Azure Flexible Server", "Scenarios, horizons, methodology versions, layer metadata, geography boundaries")
        ContainerDb(blob, "Azure Blob Storage", "Hot tier, private container", "Cloud-Optimized GeoTIFF raster layers")
    }

    System_Ext(geocoding, "Geocoding Provider")
    System_Ext(basemap, "Basemap Tile Provider")

    Rel(user, frontend, "Browses", "HTTPS")
    Rel(frontend, api, "REST API calls", "HTTPS JSON")
    Rel(frontend, tiler, "Loads exposure tiles", "HTTPS (XYZ tile URLs)")
    Rel(frontend, basemap, "Loads base map tiles", "HTTPS")
    Rel(api, postgres, "Queries", "TCP / Npgsql")
    Rel(api, tiler, "Point queries for pixel values", "HTTP internal")
    Rel(api, geocoding, "Forward geocoding", "HTTPS REST")
    Rel(tiler, blob, "Reads COG byte ranges", "HTTPS / GDAL VSIAZ")
```

---

## 3. Component Diagram — API

Shows the internal layered architecture of the ASP.NET Core API container.

```mermaid
classDiagram
    direction TB

    namespace HTTP_Layer {
        class GeocodeEndpoint {
            +POST /v1/geocode(query)
        }
        class AssessEndpoint {
            +POST /v1/assess(lat, lng, scenarioId, horizonYear)
        }
        class ConfigEndpoints {
            +GET /v1/config/scenarios
            +GET /v1/config/methodology
        }
        class HealthEndpoint {
            +GET /health
        }
    }

    namespace Application_Layer {
        class GeocodingOrchestrator {
            +GeocodeAsync(query) GeocodingResponse
        }
        class AssessmentService {
            +AssessAsync(query) AssessmentResult
        }
    }

    namespace Domain_Layer {
        class ResultStateDeterminator {
            +Determine(geography, layer, isExposed) ResultState
        }
        class GeographyClassification {
            <<enumeration>>
            OutsideEurope
            InEuropeOutsideCoastalZone
            InEuropeAndCoastalZone
        }
        class ResultState {
            <<enumeration>>
            ModeledExposureDetected
            NoModeledExposureDetected
            DataUnavailable
            OutOfScope
            UnsupportedGeography
        }
    }

    namespace Infrastructure_Layer {
        class PostGisGeographyRepository {
            +IsWithinEuropeAsync(lat, lng) bool
            +IsWithinCoastalZoneAsync(lat, lng) bool
        }
        class LayerResolver {
            +ResolveAsync(scenarioId, horizonYear) ExposureLayer?
        }
        class ExposureEvaluator {
            +IsExposedAsync(lat, lng, layer) bool
        }
        class GeocodingServiceImpl {
            +GeocodeAsync(query) List~GeocodingCandidate~
        }
    }

    GeocodeEndpoint --> GeocodingOrchestrator
    AssessEndpoint --> AssessmentService
    GeocodingOrchestrator --> GeocodingServiceImpl
    AssessmentService --> PostGisGeographyRepository
    AssessmentService --> LayerResolver
    AssessmentService --> ExposureEvaluator
    AssessmentService --> ResultStateDeterminator
```

---

## 4. Component Diagram — Frontend

Shows the key frontend components and their relationships.

```mermaid
classDiagram
    direction TB

    namespace Server_Components {
        class RootLayout {
            +layout.tsx
            +HTML shell, metadata, fonts
        }
        class Page {
            +page.tsx
            +Renders AppShell
        }
    }

    namespace Client_Shell {
        class AppShell {
            <<"use client">>
            +Orchestrates all interactive surfaces
        }
    }

    namespace Search_Surface {
        class SearchBar {
            +Free-text input (max 200 chars)
            +Triggers geocoding
        }
        class CandidateList {
            +Renders 1-5 ranked results
            +Selection triggers assessment
        }
    }

    namespace Map_Surface {
        class MapSurface {
            +MapLibre GL JS (dynamic import, ssr:false)
            +Europe-centered initial view
        }
        class ExposureOverlay {
            +deck.gl TileLayer
            +Binary colored exposure tiles
        }
        class LocationMarker {
            +Selected location pin
        }
        class Legend {
            +Colormap for exposure layer
        }
    }

    namespace Result_Surface {
        class ResultPanel {
            +Location + scenario + horizon summary
            +5 result state visual treatments
        }
        class ScenarioControl {
            +Radio/tabs for scenario selection
        }
        class HorizonControl {
            +Segmented buttons: 2030, 2050, 2100
        }
    }

    namespace Info_Surface {
        class MethodologyPanel {
            +Drawer/modal (dynamic import)
            +Source attribution and limitations
        }
    }

    namespace State_Management {
        class AppPhaseStore {
            +Zustand
            +idle, geocoding, assessing, result...
        }
        class MapStateStore {
            +Zustand
            +viewport, selectedLocation
        }
        class ServerStateCache {
            +TanStack Query
            +config, geocode, assess caches
        }
    }

    RootLayout --> Page
    Page --> AppShell
    AppShell --> SearchBar
    AppShell --> MapSurface
    AppShell --> ResultPanel
    SearchBar --> CandidateList
    MapSurface --> ExposureOverlay
    MapSurface --> LocationMarker
    MapSurface --> Legend
    ResultPanel --> ScenarioControl
    ResultPanel --> HorizonControl
    ResultPanel --> MethodologyPanel
    AppShell --> AppPhaseStore
    AppShell --> MapStateStore
    AppShell --> ServerStateCache
```

---

## 5. Class Diagram — Domain Model

Shows all domain entities, value objects, and enumerations with their attributes.

```mermaid
classDiagram
    direction LR

    class Scenario {
        +string id
        +string displayName
        +string description
        +int sortOrder
        +bool isDefault
    }

    class TimeHorizon {
        +int year
        +string displayLabel
        +bool isDefault
        +int sortOrder
    }

    class MethodologyVersion {
        +string version
        +bool isActive
        +string seaLevelSourceName
        +string seaLevelSourceUrl
        +string elevationSourceName
        +string elevationSourceUrl
        +string whatItDoes
        +string[] limitations
        +string resolutionNote
        +decimal? exposureThreshold
        +datetime updatedAt
    }

    class ExposureLayer {
        +uuid id
        +string scenarioId
        +int horizonYear
        +string methodologyVersion
        +string blobPath
        +string blobContainer
        +bool cogFormat
        +bool isValid
        +JSONB legendColormap
        +datetime generatedAt
    }

    class GeographyBoundary {
        +string name
        +GEOMETRY~MULTIPOLYGON~ geom
        +string description
        +string source
        +datetime createdAt
    }

    class AssessmentQuery {
        <<value object>>
        +float latitude
        +float longitude
        +string scenarioId
        +int horizonYear
    }

    class AssessmentResult {
        <<value object>>
        +string requestId
        +ResultState resultState
        +Location location
        +ScenarioRef scenario
        +HorizonRef horizon
        +string methodologyVersion
        +string? layerTileUrlTemplate
        +LegendSpec? legendSpec
        +datetime generatedAt
    }

    class GeocodingCandidate {
        <<value object>>
        +int rank
        +string label
        +string country
        +float latitude
        +float longitude
        +string displayContext
    }

    class Location {
        <<value object>>
        +float latitude
        +float longitude
    }

    class ScenarioRef {
        <<value object>>
        +string id
        +string displayName
    }

    class HorizonRef {
        <<value object>>
        +int year
        +string displayLabel
    }

    class LegendSpec {
        <<value object>>
        +ColorStop[] colorStops
    }

    class ColorStop {
        <<value object>>
        +int value
        +string color
        +string label
    }

    class ResultState {
        <<enumeration>>
        ModeledExposureDetected
        NoModeledExposureDetected
        DataUnavailable
        OutOfScope
        UnsupportedGeography
    }

    class GeographyClassification {
        <<enumeration>>
        OutsideEurope
        InEuropeOutsideCoastalZone
        InEuropeAndCoastalZone
    }

    Scenario "1" --o "0..*" ExposureLayer : scenarioId
    TimeHorizon "1" --o "0..*" ExposureLayer : horizonYear
    MethodologyVersion "1" --o "0..*" ExposureLayer : methodologyVersion

    AssessmentQuery --> Scenario : references
    AssessmentQuery --> TimeHorizon : references

    AssessmentResult --> ResultState : resultState
    AssessmentResult *-- Location : location
    AssessmentResult *-- ScenarioRef : scenario
    AssessmentResult *-- HorizonRef : horizon
    AssessmentResult *-- "0..1" LegendSpec : legendSpec
    LegendSpec *-- "1..*" ColorStop : colorStops
```

---

## 6. Class Diagram — Infrastructure Interfaces

Shows the dependency inversion between domain and infrastructure layers.

```mermaid
classDiagram
    direction TB

    namespace Domain_Interfaces {
        class IGeographyRepository {
            <<interface>>
            +IsWithinEuropeAsync(lat, lng) Task~bool~
            +IsWithinCoastalZoneAsync(lat, lng) Task~bool~
        }
        class IGeocodingService {
            <<interface>>
            +GeocodeAsync(query) Task~List~GeocodingCandidate~~
        }
        class ILayerResolver {
            <<interface>>
            +ResolveAsync(scenarioId, horizonYear) Task~ExposureLayer?~
        }
        class IExposureEvaluator {
            <<interface>>
            +IsExposedAsync(lat, lng, layer) Task~bool~
        }
        class IAssessmentService {
            <<interface>>
            +AssessAsync(query) Task~AssessmentResult~
        }
    }

    namespace Infrastructure_Implementations {
        class PostGisGeographyRepository {
            -NpgsqlConnection _conn
            +IsWithinEuropeAsync(lat, lng) Task~bool~
            +IsWithinCoastalZoneAsync(lat, lng) Task~bool~
        }
        class NominatimGeocodingService {
            -HttpClient _http
            +GeocodeAsync(query) Task~List~GeocodingCandidate~~
        }
        class DbLayerResolver {
            -NpgsqlConnection _conn
            +ResolveAsync(scenarioId, horizonYear) Task~ExposureLayer?~
        }
        class TiTilerExposureEvaluator {
            -HttpClient _http
            +IsExposedAsync(lat, lng, layer) Task~bool~
        }
    }

    namespace Application_Services {
        class AssessmentService {
            -IGeographyRepository _geography
            -ILayerResolver _layerResolver
            -IExposureEvaluator _evaluator
            -ResultStateDeterminator _determinator
            +AssessAsync(query) Task~AssessmentResult~
        }
        class GeocodingOrchestrator {
            -IGeocodingService _geocoder
            +GeocodeAsync(query) Task~GeocodingResponse~
        }
    }

    IGeographyRepository <|.. PostGisGeographyRepository : implements
    IGeocodingService <|.. NominatimGeocodingService : implements
    ILayerResolver <|.. DbLayerResolver : implements
    IExposureEvaluator <|.. TiTilerExposureEvaluator : implements
    IAssessmentService <|.. AssessmentService : implements

    AssessmentService --> IGeographyRepository : depends on
    AssessmentService --> ILayerResolver : depends on
    AssessmentService --> IExposureEvaluator : depends on
    GeocodingOrchestrator --> IGeocodingService : depends on
```

---

## 7. Sequence Diagram — Assessment Happy Path

Full assessment flow for a valid coastal European location with exposure detected.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as API (ASP.NET Core)
    participant PG as PostgreSQL + PostGIS
    participant TL as TiTiler
    participant Blob as Azure Blob Storage

    User->>FE: Search "Amsterdam"
    FE->>API: POST /v1/geocode {query: "Amsterdam"}
    API->>API: Validate query (1-200 chars)
    API-->>FE: 200 OK {candidates: [{rank:1, label:"Amsterdam, NH, NL", lat:52.37, lng:4.90, ...}]}
    FE->>User: Show candidate list

    User->>FE: Select "Amsterdam, NH, NL"
    Note over FE: Phase → assessing

    FE->>API: POST /v1/assess {lat:52.37, lng:4.90, scenarioId:"ssp2-45", horizonYear:2050}

    API->>API: Validate inputs (coords, scenario, horizon)

    API->>PG: ST_Within(POINT(4.90, 52.37), europe_boundary)
    PG-->>API: true (in Europe)

    API->>PG: ST_Within(POINT(4.90, 52.37), coastal_analysis_zone)
    PG-->>API: true (in coastal zone)

    API->>PG: SELECT layer WHERE scenario='ssp2-45' AND horizon=2050 AND version=(active) AND valid=true
    PG-->>API: ExposureLayer {blobPath: "layers/v1.0/ssp2-45/2050.tif"}

    API->>TL: GET /point/4.90,52.37?url=layers/v1.0/ssp2-45/2050.tif
    TL->>Blob: HTTP Range Request (COG byte ranges)
    Blob-->>TL: Raster data
    TL-->>API: {values: [[1]]}

    API->>API: ResultStateDeterminator → ModeledExposureDetected

    API-->>FE: 200 OK {resultState:"ModeledExposureDetected", layerTileUrlTemplate:"...", legendSpec:{...}, methodologyVersion:"v1.0"}

    Note over FE: Phase → result
    FE->>TL: Load XYZ tiles /{z}/{x}/{y}.png
    TL->>Blob: HTTP Range Requests
    Blob-->>TL: Tile bytes
    TL-->>FE: PNG tiles
    FE->>User: Display result panel + exposure overlay + legend
```

---

## 8. Sequence Diagram — Geocoding Flow

Shows the full geocoding flow including edge cases.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant TQ as TanStack Query Cache
    participant API as API
    participant GS as IGeocodingService
    participant GP as Geocoding Provider

    User->>FE: Type query, submit
    FE->>FE: Validate (1-200 chars)

    alt Cache hit (staleTime: 30s)
        FE->>TQ: Check ['geocode', query]
        TQ-->>FE: Cached candidates
    else Cache miss
        FE->>API: POST /v1/geocode {query}
        API->>API: Validate query
        API->>GS: GeocodeAsync(query)
        GS->>GP: Forward geocode request
        GP-->>GS: Raw provider response
        GS->>GS: Normalize to GeocodingCandidate[]
        GS->>GS: Limit to max 5 candidates (BR-007)
        GS-->>API: List<GeocodingCandidate>
        API-->>FE: 200 OK {candidates: [...]}
        FE->>TQ: Cache result
    end

    alt 0 candidates
        Note over FE: Phase → no_results
        FE->>User: "No results found"
    else 1 candidate
        Note over FE: Auto-select, Phase → assessing
        FE->>API: POST /v1/assess {...}
    else 2-5 candidates
        Note over FE: Phase → candidate_selection
        FE->>User: Show CandidateList
    end
```

---

## 9. Sequence Diagram — Scenario/Horizon Change

Shows the control-change flow with stale request handling.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant AC as AbortController
    participant TQ as TanStack Query
    participant API as API

    Note over FE: Currently showing result for SSP2-4.5 / 2050

    User->>FE: Select SSP5-8.5 scenario
    Note over FE: Phase → result_updating (previous result still visible)

    FE->>AC: Abort previous in-flight request (if any)
    AC-->>API: Abort signal

    FE->>TQ: Query ['assess', lat, lng, 'ssp5-85', 2050]

    alt Cache hit (60s staleTime)
        TQ-->>FE: Cached AssessmentResult
        Note over FE: Phase → result (instant update)
    else Cache miss
        TQ->>API: POST /v1/assess {scenarioId:"ssp5-85", horizonYear:2050, ...}
        API-->>TQ: 200 OK {resultState: "ModeledExposureDetected", ...}
        TQ-->>FE: New AssessmentResult
        Note over FE: Phase → result
    end

    FE->>FE: Update ResultPanel + ExposureOverlay + Legend atomically (FR-031)
    FE->>User: New result displayed
```

---

## 10. State Machine — Frontend Application Phase

```mermaid
stateDiagram-v2
    [*] --> idle : App loaded, config fetched

    idle --> geocoding : Search submitted
    idle --> idle : Reset

    geocoding --> no_results : 0 candidates returned
    geocoding --> candidate_selection : 2+ candidates returned
    geocoding --> assessing : 1 candidate (auto-select)
    geocoding --> geocoding_error : Provider failure / network error

    no_results --> idle : Edit query / reset

    candidate_selection --> assessing : User selects candidate

    assessing --> result : AssessmentResult received
    assessing --> assessment_error : Request failed

    result --> result_updating : Scenario, horizon, or marker changed
    result --> idle : Reset

    result_updating --> result : New AssessmentResult received
    result_updating --> assessment_error : Request failed

    assessment_error --> assessing : Retry
    assessment_error --> idle : Reset

    geocoding_error --> geocoding : Retry
    geocoding_error --> idle : Reset

    note right of idle : EmptyState rendered\nScenario + Horizon controls populated
    note right of result : ResultPanel visible\nExposure overlay active\nControls interactive
    note right of result_updating : Previous result visible\nLoading indicator shown
```

---

## 11. Deployment Diagram

Shows the Azure infrastructure topology.

```mermaid
graph TB
    subgraph Internet
        User[Public User<br/>Browser]
    end

    subgraph Azure["Azure Resource Group: rg-searise-europe-prod"]
        subgraph CAE["Container Apps Environment: cae-searise-europe"]
            FE["ca-frontend<br/>Next.js 14+<br/>Port 3000<br/>0-3 replicas"]
            API["ca-api<br/>ASP.NET Core .NET 8+<br/>Port 8080<br/>0-5 replicas"]
            TL["ca-tiler<br/>TiTiler / FastAPI<br/>Port 8000<br/>0-5 replicas"]
        end

        PG["Azure Database for PostgreSQL<br/>Flexible Server (Burstable B1ms)<br/>+ PostGIS extension"]
        BLOB["Azure Blob Storage<br/>sa-seariseeurope<br/>Container: geospatial (private)"]
        ACR["Azure Container Registry<br/>acr-seariseeurope"]
        KV["Azure Key Vault<br/>kv-searise-europe"]
        MON["Azure Monitor<br/>Log Analytics Workspace"]
    end

    subgraph External
        GEO["Azure Maps Search<br/>(ADR-019)"]
        BASE["Azure Maps<br/>(ADR-020)"]
    end

    User -->|HTTPS| FE
    User -->|HTTPS| BASE
    FE -->|HTTPS JSON| API
    FE -->|HTTPS XYZ tiles| TL
    API -->|TCP / Npgsql| PG
    API -->|HTTP internal| TL
    API -->|HTTPS| GEO
    TL -->|GDAL VSIAZ<br/>HTTP range requests| BLOB
    ACR -.->|Image pull| CAE
    KV -.->|Secret refs| CAE
    CAE -.->|Logs + metrics| MON

    style CAE fill:#e8f4f8,stroke:#0078d4
    style Azure fill:#f0f6ff,stroke:#0078d4
```

---

## 12. Activity Diagram — Offline Geospatial Pipeline

Shows the Phase 0 data pipeline that generates COG raster assets.

```mermaid
flowchart TD
    Start([Pipeline Triggered]) --> Download

    subgraph Download["Step 1: Download"]
        D1[Fetch IPCC AR6 NetCDF<br/>sea-level projections]
        D2[Fetch Copernicus DEM GLO-30<br/>GeoTIFF tiles]
        D1 & D2 --> D3[Cache raw data locally]
    end

    Download --> Preprocess

    subgraph Preprocess["Step 2: Preprocess"]
        P1[Interpolate SLR grid<br/>to DEM resolution]
        P2[Reproject to EPSG:4326]
        P1 --> P2
    end

    Preprocess --> Compute

    subgraph Compute["Step 3: Compute Exposure"]
        C1["Binary comparison:<br/>exposure = 1 if SLR >= DEM else 0"]
        C2[Apply coastal analysis zone mask<br/>NoData outside zone]
        C1 --> C2
    end

    Compute --> COGify

    subgraph COGify["Step 4: COGify"]
        G1[Convert to Cloud-Optimized GeoTIFF]
        G2["256x256 tiles, internal overviews, deflate compression"]
        G1 --> G2
    end

    COGify --> QA

    subgraph QA["Step 5: QA Validation"]
        Q1{COG structure valid?}
        Q2{CRS = EPSG:4326?}
        Q3{Pixel values binary 0/1?}
        Q4{Extent covers Europe?}
        Q5{Non-empty exposure pixels?}
        Q1 -->|Yes| Q2
        Q2 -->|Yes| Q3
        Q3 -->|Yes| Q4
        Q4 -->|Yes| Q5
    end

    Q1 -->|No| Fail([QA Failed — Abort])
    Q2 -->|No| Fail
    Q3 -->|No| Fail
    Q4 -->|No| Fail
    Q5 -->|No| Fail

    Q5 -->|Yes| Upload

    subgraph Upload["Step 6: Upload"]
        U1["Upload COG to Azure Blob<br/>geospatial/layers/{version}/{scenario}/{horizon}.tif"]
    end

    Upload --> Register

    subgraph Register["Step 7: Register"]
        R1["INSERT into layers table<br/>layer_valid = false"]
        R2["UPDATE layer_valid = true<br/>(after QA confirmation)"]
        R1 --> R2
    end

    Register --> Done([Pipeline Complete])

    style Fail fill:#fdd,stroke:#d44
    style Done fill:#dfd,stroke:#4a4
```

---

## 13. Package Diagram — Layered Architecture

Shows the dependency direction between architectural layers (clean architecture).

```mermaid
graph TB
    subgraph HTTP["HTTP Layer"]
        direction LR
        E1["GeocodeEndpoint"]
        E2["AssessEndpoint"]
        E3["ConfigEndpoints"]
        E4["HealthEndpoint"]
        E5["Request Validation"]
        E6["Error Middleware"]
    end

    subgraph APP["Application Layer"]
        direction LR
        A1["AssessmentService"]
        A2["GeocodingOrchestrator"]
    end

    subgraph DOM["Domain Layer"]
        direction LR
        D1["ResultStateDeterminator"]
        D2["GeographyClassification"]
        D3["ResultState"]
        D4["Value Objects"]
        D5["Domain Interfaces"]
    end

    subgraph INF["Infrastructure Layer"]
        direction LR
        I1["PostGisGeographyRepository"]
        I2["DbLayerResolver"]
        I3["TiTilerExposureEvaluator"]
        I4["NominatimGeocodingService"]
        I5["Azure Blob Client"]
    end

    HTTP --> APP
    APP --> DOM
    INF -.->|implements| DOM

    style HTTP fill:#fff3cd,stroke:#856404
    style APP fill:#d1ecf1,stroke:#0c5460
    style DOM fill:#d4edda,stroke:#155724
    style INF fill:#f8d7da,stroke:#721c24

    classDef note font-size:10px
```

**Dependency Rule:** Dependencies point inward. The Domain layer has zero references to Infrastructure. Infrastructure implements Domain interfaces (dependency inversion).

---

## Cross-References

| Diagram | Related Architecture Document |
|---|---|
| System Context | [01-system-context.md](01-system-context.md) |
| Container | [02-container-view.md](02-container-view.md) |
| API Components | [03-component-view.md](03-component-view.md) |
| Frontend Components | [03a-frontend-architecture.md](03a-frontend-architecture.md) |
| Sequence Diagrams | [04-runtime-sequences.md](04-runtime-sequences.md) |
| Domain Model Classes | [13-domain-model.md](13-domain-model.md) |
| Deployment | [08-deployment-topology.md](08-deployment-topology.md) |
| Pipeline Activity | [16-geospatial-data-pipeline.md](16-geospatial-data-pipeline.md) |
| API Contracts | [06-api-and-contracts.md](06-api-and-contracts.md) |
