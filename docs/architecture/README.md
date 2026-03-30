# SeaRise Europe — Architecture Documentation

## Overview

This directory contains the technical architecture documentation for SeaRise Europe. All documents describe **Proposed Architecture** derived from the product definition in `docs/product/`. No implementation code exists yet — this documentation set is the first architectural artifact and establishes the design baseline for Phase 0 and Phase 1 implementation.

These documents exist to:
- Enable an engineering team to implement the system with minimal ambiguity
- Surface and track architectural risks, assumptions, and unresolved product questions
- Demonstrate strong architecture judgment across frontend, backend, geospatial, and data domains
- Serve as a portfolio-quality reference for technical reviewers (Persona P-03)

---

## Relationship to Product Documentation

| Product Doc | Role in Architecture |
|---|---|
| `docs/product/PRD.md` | **Primary source of truth.** All functional requirements (FR-xxx), business rules (BR-xxx), non-functional requirements (NFR-xxx), and acceptance criteria (AC-xxx) come from here. Architecture decisions reference PRD IDs explicitly. |
| `docs/product/VISION.md` | Establishes strategic pillars (scientific honesty, data transparency, engineering quality) that constrain architectural choices. |
| `docs/product/PERSONAS.md` | Informs frontend architecture priorities (P-01: clear result states; P-02: transparent methodology; P-03: graceful error handling and real data). |
| `docs/product/ROADMAP.md` | Pointer to [`docs/delivery/ROADMAP.md`](../delivery/ROADMAP.md). The delivery roadmap defines Phase 0 (data pipeline + infrastructure) as a prerequisite for Phase 1 (MVP). Architecture is structured to respect this dependency. |
| `docs/delivery/ROADMAP.md` | **Delivery roadmap.** Epic breakdown (01–08), dependency map, critical path, MVP definition of done, and story-level implementation plans. Translates architecture into sequenced, implementation-ready work. |
| `docs/product/METRICS_PLAN.md` | Defines the observability and analytics requirements that shape the logging, metrics, and instrumentation design. |
| `docs/product/CONTENT_GUIDELINES.md` | Establishes result-state copy rules and prohibited language that constrain frontend component behavior and test coverage. |

Architecture documents do not restate product decisions — they translate them into technical design. When an architecture document references a PRD requirement, it is to trace _why_ a design choice was made.

---

## Reading Order

### For an implementer starting fresh:
1. [README.md](README.md) — this file
2. [01-system-context.md](01-system-context.md) — understand the system's scope and external boundaries
3. [02-container-view.md](02-container-view.md) — understand the deployable units
4. [05-data-architecture.md](05-data-architecture.md) — understand the data model before touching the database
5. [06-api-and-contracts.md](06-api-and-contracts.md) — understand the API contracts before writing any service code
6. [03-component-view.md](03-component-view.md) — understand internal API structure
7. [03a-frontend-architecture.md](03a-frontend-architecture.md) — understand the frontend before writing UI code
8. [16-geospatial-data-pipeline.md](16-geospatial-data-pipeline.md) — understand the offline pipeline before beginning Phase 0 data work
9. [12-risks-assumptions-and-open-questions.md](12-risks-assumptions-and-open-questions.md) — understand what is blocked and what to resolve first
10. [17-open-question-closure-proposal.md](17-open-question-closure-proposal.md) — review the proposed closure set before converting decisions into ADRs and seed data

### For a technical reviewer or architect:
1. [01-system-context.md](01-system-context.md)
2. [11-architecture-decisions.md](11-architecture-decisions.md)
3. [12-risks-assumptions-and-open-questions.md](12-risks-assumptions-and-open-questions.md)
4. [17-open-question-closure-proposal.md](17-open-question-closure-proposal.md)
5. [03a-frontend-architecture.md](03a-frontend-architecture.md)
6. [13-domain-model.md](13-domain-model.md)

### For operations and deployment:
1. [08-deployment-topology.md](08-deployment-topology.md)
2. [09-observability-and-operations.md](09-observability-and-operations.md)
3. [07-security-architecture.md](07-security-architecture.md)

---

## Document Index

| # | File | Purpose | Status |
|---|---|---|---|
| — | [README.md](README.md) | Index and orientation for the architecture documentation set | Confirmed |
| 01 | [01-system-context.md](01-system-context.md) | System purpose, actors, external dependencies, constraints | Proposed Architecture |
| 02 | [02-container-view.md](02-container-view.md) | Deployable containers, responsibilities, communication patterns | Proposed Architecture |
| 03 | [03-component-view.md](03-component-view.md) | Internal structure of the ASP.NET Core API | Proposed Architecture |
| 03a | [03a-frontend-architecture.md](03a-frontend-architecture.md) | Frontend architecture — routing, state, map, components, accessibility | Proposed Architecture |
| 04 | [04-runtime-sequences.md](04-runtime-sequences.md) | Sequence diagrams for all key runtime flows | Proposed Architecture |
| 05 | [05-data-architecture.md](05-data-architecture.md) | Data model, storage choices, geospatial representations, lifecycle | Proposed Architecture |
| 06 | [06-api-and-contracts.md](06-api-and-contracts.md) | API style, endpoints, request/response shapes, error model | Proposed Architecture |
| 07 | [07-security-architecture.md](07-security-architecture.md) | Security model, secrets management, privacy, GDPR | Proposed Architecture |
| 08 | [08-deployment-topology.md](08-deployment-topology.md) | Azure infrastructure, environments, CI/CD, scaling | Proposed Architecture |
| 09 | [09-observability-and-operations.md](09-observability-and-operations.md) | Logging, metrics, alerting, health checks, runbook | Proposed Architecture |
| 10 | [10-testing-strategy.md](10-testing-strategy.md) | Unit, integration, E2E, accessibility, performance, and geospatial testing | Proposed Architecture |
| 11 | [11-architecture-decisions.md](11-architecture-decisions.md) | ADR-style records for all major technical decisions | Proposed Architecture |
| 12 | [12-risks-assumptions-and-open-questions.md](12-risks-assumptions-and-open-questions.md) | Blocking open questions, technical risks, assumptions, contradictions | Proposed Architecture |
| 13 | [13-domain-model.md](13-domain-model.md) | Domain concepts, bounded contexts, entities, invariants | Proposed Architecture |
| 14 | [14-integration-patterns.md](14-integration-patterns.md) | Third-party integrations, retry/timeout, fallback, failure isolation | Proposed Architecture |
| 15 | [15-performance-and-scalability.md](15-performance-and-scalability.md) | Latency budgets, bottleneck analysis, caching, concurrency | Proposed Architecture |
| 16 | [16-geospatial-data-pipeline.md](16-geospatial-data-pipeline.md) | Offline data pipeline: acquisition, processing, COG generation, publication | Proposed Architecture |
| 17 | [17-open-question-closure-proposal.md](17-open-question-closure-proposal.md) | Proposed resolutions for the architecture open questions before ADR conversion | Proposal for review |

---

## Confirmed vs Proposed Architecture

**Confirmed** (from PRD or explicit product decisions):
- Result state taxonomy: `ModeledExposureDetected | NoModeledExposureDetected | DataUnavailable | OutOfScope | UnsupportedGeography` (BR-010)
- Time horizons: exactly 2030, 2050, 2100 (FR-015)
- Max 5 geocoding candidates (BR-007), max 200-char search input (BR-008)
- Anonymous public access, no auth (BR-001)
- No raw address persistence (BR-016, NFR-007)
- No Kubernetes for MVP (NFR-023)
- Stateless runtime services (NFR-019)
- WCAG 2.2 AA accessibility (NFR-015)
- Methodology version visible in API response and UI (FR-035, NFR-021)
- COG or PMTiles format for geospatial assets (NFR-020)
- English-only MVP UI, copy externalized for localization (BR-017, NFR-018)

**Proposed Architecture** (derived from product intent, technology choices, and architectural judgment — not yet implemented):
- Next.js 14+ App Router as frontend framework
- ASP.NET Core .NET 8+ Minimal API as backend
- TiTiler as tile server
- Azure Container Apps for hosting
- Azure Database for PostgreSQL with PostGIS for structured data and geography validation
- Azure Blob Storage for COG file storage
- Zustand + TanStack Query for frontend state management
- AbortController-based stale request cancellation
- URL state design for deep-link readiness (OQ-08)
- Python/GDAL/rio_cogeo for the offline geospatial pipeline

---

## Optional Documents — Rationale for Inclusion

All four optional documents (13–16) were created because:

| Document | Reason for inclusion |
|---|---|
| [13-domain-model.md](13-domain-model.md) | The domain has non-trivial complexity: a fixed result-state taxonomy, geography-gated assessment logic, methodology versioning, and strict invariants (no substitution, no overstatement). Documenting the domain model prevents these invariants from being accidentally violated in implementation. |
| [14-integration-patterns.md](14-integration-patterns.md) | The system has five integration points with external or internal services (geocoding provider, basemap tiles, TiTiler, Azure Blob, offline pipeline). Three blocking open questions (OQ-04, OQ-05, OQ-06) directly concern integration behavior. Failure isolation patterns are non-trivial. |
| [15-performance-and-scalability.md](15-performance-and-scalability.md) | Four specific latency NFRs (NFR-001 through NFR-004) with measurable p95 targets. Geospatial tile serving and PostGIS geography queries have non-obvious performance characteristics. Latency budget analysis justifies key architectural choices (lazy loading, COG overviews, TiTiler). |
| [16-geospatial-data-pipeline.md](16-geospatial-data-pipeline.md) | The offline pipeline is a Phase 0 prerequisite — Phase 1 cannot proceed without it. It is a core implementation concern involving multiple data sources, complex processing, and non-trivial validation. NFR-022 requires reproducibility. Omitting this document would leave a major implementation gap. |

---

## Where to Track Unresolved Questions

[12-risks-assumptions-and-open-questions.md](12-risks-assumptions-and-open-questions.md) is the canonical location for:
- Blocking open questions (OQ-02 through OQ-06) and their implementation impact
- Pre-launch open questions (OQ-07 through OQ-12)
- Technical risks
- Architecture assumptions
- Contradictions between repository state and product intent

Use [17-open-question-closure-proposal.md](17-open-question-closure-proposal.md) as the companion document when you want the **recommended closure set** rather than the unresolved-question inventory.

The five blocking questions **must be resolved before Phase 1 implementation begins**. They are documented in detail in document 12 and referenced throughout the architecture where relevant.

---

## Architecture Summary

SeaRise Europe is a three-container web application backed by managed cloud data services. The **frontend** (Next.js) handles search, map display, and result presentation. The **API** (ASP.NET Core) proxies geocoding, performs server-side geography validation, resolves exposure assessment results, and manages scenario/methodology configuration. The **tile server** (TiTiler) serves Cloud-Optimized GeoTIFF map tiles directly from Azure Blob Storage to the browser.

Persistent state lives in two managed services: **PostgreSQL** (scenario config, layer metadata, geography boundaries, methodology versions) and **Azure Blob Storage** (precomputed COG raster files, one per scenario × horizon × methodology version). No user data is ever persisted.

An **offline geospatial pipeline** (not a runtime service) generates the COG files from IPCC AR6 sea-level projections and Copernicus DEM elevation data. This pipeline must complete Phase 0 before any Phase 1 user-facing feature work can proceed.

All runtime containers are stateless and deploy to Azure Container Apps. No Kubernetes, no message queues, no distributed cache in MVP.
