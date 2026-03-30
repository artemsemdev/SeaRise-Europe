# SeaRise Europe — Delivery Roadmap

## Document Metadata

| Field | Value |
|---|---|
| Owner | Artem Sem |
| Status | Draft |
| Version | 0.1 |
| Last updated | 2026-03-30 |
| Delivery model | Solo engineer, end-to-end |

**Version History**

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 0.1 | 2026-03-30 | Artem Sem | Initial delivery roadmap — adapted from product roadmap |

> **Note:** This document replaces `docs/product/ROADMAP.md` as the primary execution plan. Product phasing and prioritization logic from the original roadmap are preserved; the structure has been rewritten for delivery planning with dependency ordering, effort estimates, and an epic breakdown sized for solo implementation.

---

## 1. Delivery Approach

### 1.1 Scope

This roadmap covers Phase 0 (foundation and data pipeline) and Phase 1 (MVP — Core Exposure Explorer) as defined in the product documentation. Phase 2 (Quality and Depth) and Phase 3 (Expansion) are out of scope for this delivery plan.

### 1.2 Delivery Model

One engineer implements the entire system end-to-end: geospatial pipeline, cloud infrastructure, backend API, frontend application, testing, and release hardening. Effort estimates reflect solo delivery capacity.

### 1.3 Sequencing Philosophy

**Depth-first, dependency-aware.** Each epic produces a verifiable deliverable that the next epic depends on. No epic begins work that requires outputs from a later epic. Decision closure comes first because unresolved open questions (OQ-02 through OQ-07) block pipeline, schema, and UI implementation.

### 1.4 Phase Distinction

| Phase | Theme | Deliverable | Audience |
|---|---|---|---|
| Phase 0 | Foundation | Data pipeline, infrastructure, seed data, resolved open questions | Engineer (internal) |
| Phase 1 | MVP | Fully functional, publicly deployable exposure explorer | All personas (P-01, P-02, P-03) |

Phase 0 produces no user-visible output. Its exit criteria must be met before Phase 1 feature work begins.

---

## 2. Epic Overview

| # | Epic | Phase | Effort | Dependencies |
|---|---|---|---|---|
| 01 | [Decision Closure and Delivery Baseline](01-decision-closure.md) | 0 | ~4 days | None — entry point |
| 02 | [Cloud Infrastructure and CI/CD](02-cloud-infrastructure.md) | 0 | ~5 days | Epic 01 (provider decisions) |
| 03 | [Geospatial Data Pipeline](03-geospatial-pipeline.md) | 0 | ~7 days | Epic 01 (methodology), Epic 02 (Blob + DB) |
| 04 | [Backend API Core](04-backend-api.md) | 0/1 | ~7 days | Epic 02 (infra), Epic 03 (seed data + layers) |
| 05 | [Frontend Shell and Search Flow](05-frontend-search.md) | 1 | ~6 days | Epic 04 (geocode + config endpoints) |
| 06 | [Scenario Controls and Assessment UX](06-assessment-ux.md) | 1 | ~6 days | Epic 04 (assess endpoint), Epic 05 (map + shell) |
| 07 | [Transparency, Accessibility, and Content Compliance](07-transparency-a11y.md) | 1 | ~5 days | Epic 06 (result panel exists) |
| 08 | [Testing, Security Hardening, and Release Readiness](08-release-hardening.md) | 1 | ~7 days | All prior epics |
| | **Total** | | **~47 days (~9.5 weeks)** | |

---

## 3. Execution Sequence

```
Phase 0 — Foundation
──────────────────────────────────────────────────────
 Epic 01: Decision Closure          ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 Epic 02: Cloud Infrastructure           █████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
 Epic 03: Geospatial Pipeline                 ███████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

Phase 1 — MVP
──────────────────────────────────────────────────────
 Epic 04: Backend API                              ███████░░░░░░░░░░░░░░░░░░░░░░░░░░
 Epic 05: Frontend + Search                                 ██████░░░░░░░░░░░░░░░░░░
 Epic 06: Assessment UX                                           ██████░░░░░░░░░░░░
 Epic 07: Transparency + A11y                                           █████░░░░░░░
 Epic 08: Release Hardening                                                  ███████

──────────────────────────────────────────────────────
 Week  1    2    3    4    5    6    7    8    9   10
```

---

## 4. Dependency Map

```
Epic 01 (Decisions)
  │
  ├──► Epic 02 (Infrastructure)
  │       │
  │       ├──► Epic 03 (Pipeline)
  │       │       │
  │       │       └──► Epic 04 (Backend API)
  │       │               │
  │       └───────────────┤
  │                       ├──► Epic 05 (Frontend + Search)
  │                       │       │
  │                       │       └──► Epic 06 (Assessment UX)
  │                       │               │
  │                       │               └──► Epic 07 (Transparency + A11y)
  │                       │                       │
  │                       │                       └──► Epic 08 (Release Hardening)
  │                       │                               ▲
  │                       └───────────────────────────────┘
  └──► (all epics reference decision outputs)
```

### Dependency Matrix

| Epic | Depends On | Produces For |
|---|---|---|
| 01 | — | 02, 03, 04 (all downstream) |
| 02 | 01 | 03, 04, 08 |
| 03 | 01, 02 | 04 |
| 04 | 02, 03 | 05, 06, 08 |
| 05 | 04 | 06 |
| 06 | 04, 05 | 07 |
| 07 | 06 | 08 |
| 08 | All prior | — (release gate) |

---

## 5. Critical Path

The critical path runs through every epic sequentially because there is one engineer:

**01 → 02 → 03 → 04 → 05 → 06 → 07 → 08**

Any delay on any epic delays the release. The highest-risk items on the critical path are:

| Item | Risk | Impact |
|---|---|---|
| OQ-02 through OQ-06 resolution (Epic 01) | Decision paralysis or research spirals | Blocks all downstream work |
| Geospatial pipeline (Epic 03) | Data acquisition issues, GDAL complexity, COG validation failures | Blocks backend API and all frontend work |
| TiTiler `/point` latency validation (Epic 03/04) | May require fallback to PostGIS raster approach | Rearchitects assessment pipeline |
| PostGIS geography boundary seeding (Epic 03) | Coastal zone geometry definition is non-trivial | Blocks geography validation and all result states |

---

## 6. Blockers, Prerequisites, and Open Questions

### 6.1 Blocking Open Questions (Must Resolve in Epic 01)

| OQ | Question | Blocks |
|---|---|---|
| OQ-02 | MVP scenario set (IDs, names, descriptions) | Schema seed, pipeline COG paths, API contract, frontend controls |
| OQ-03 | Default scenario and time horizon | Config endpoint response, initial UI state |
| OQ-04 | Coastal analysis zone geometry definition | PostGIS seed, geography validation, OutOfScope behavior |
| OQ-05 | Exposure methodology (binary vs. continuous threshold) | Pipeline processing logic, ExposureEvaluator, content copy |
| OQ-06 | Production geocoding provider | GeocodingClient implementation, API key procurement, displayContext mapping |
| OQ-07 | Basemap tile provider | Frontend map style, attribution requirements, key management |

### 6.2 Pre-Launch Open Questions (Resolve by Epic 08)

| OQ | Question | Impact |
|---|---|---|
| OQ-08 | Shareable URLs / deep links | URL state implementation in frontend (designed for but not committed) |
| OQ-09 | Dataset refresh cadence | Operational documentation only |
| OQ-10 | Analytics enablement and privacy model | Consent banner, analytics event wiring |
| OQ-11 | Raw coordinates visible to user | Minor UI decision |
| OQ-12 | Tablet/mobile visual parity requirement | Responsive layout scope in Epic 07 |

### 6.3 External Dependencies

| Dependency | Owner | Status | Impact If Delayed |
|---|---|---|---|
| NASA AR6 sea-level projection data access | Public (NASA) | Available | Pipeline cannot generate layers |
| Copernicus DEM GLO-30 tile access | Public (Copernicus) | Available | Pipeline cannot generate layers |
| Azure subscription with sufficient credits | Artem Sem | Assumed available | Infrastructure cannot be provisioned |
| Geocoding provider API key (OQ-06) | Artem Sem | Pending decision | Geocoding works in dev only (Nominatim) |
| Basemap provider account (OQ-07) | Artem Sem | Pending decision | Map renders without basemap tiles |

---

## 7. Phase 0 Exit Criteria

Phase 0 is complete when all of the following are true:

- [ ] All blocking open questions (OQ-02 through OQ-07) are resolved and documented.
- [ ] Exposure methodology is documented with source attribution, threshold definition, and limitations.
- [ ] Geospatial pipeline has generated valid COG files for all scenario × horizon combinations.
- [ ] At least one COG layer is renderable via TiTiler from Azure Blob Storage.
- [ ] TiTiler `/point` endpoint returns expected pixel values for known test coordinates.
- [ ] PostgreSQL schema is deployed with PostGIS, seeded with scenarios, horizons, methodology version, geography boundaries, and layer metadata.
- [ ] Azure infrastructure is provisioned: Container Apps Environment, PostgreSQL, Blob Storage, Key Vault, Container Registry.
- [ ] CI/CD pipeline builds and deploys at least the API container to staging.
- [ ] Docker Compose local development environment runs all three containers + PostgreSQL.
- [ ] All decisions are recorded in `docs/architecture/11-architecture-decisions.md` or in Epic 01 decision log.

---

## 8. MVP Definition of Done

Phase 1 MVP is complete and release-ready when all of the following are true:

### Functional Completeness

- [ ] All 28 acceptance criteria (AC-001 through AC-028) from `docs/product/PRD.md` §17 pass.
- [ ] All 5 result states render correctly with CONTENT_GUIDELINES-compliant copy.
- [ ] All 10 demo script scenarios (D-01 through D-10) from the product roadmap pass without manual intervention.
- [ ] Search → geocode → candidate selection → assessment → result display flow works end-to-end.
- [ ] Scenario and horizon controls update map and result without requiring a new search.
- [ ] Methodology panel displays all required elements (FR-033, CONTENT_GUIDELINES §5).
- [ ] Disclaimer is visible on every result view (FR-024).
- [ ] Reset returns the application to the initial empty state (FR-041).

### Non-Functional Compliance

- [ ] App shell loads within 4 seconds p95 on modern desktop broadband (NFR-001).
- [ ] Geocoding response within 2.5 seconds p95 (NFR-002).
- [ ] Assessment response within 3.5 seconds p95 (NFR-003).
- [ ] Control-switch latency within 1.5 seconds p95 for cached results (NFR-004).
- [ ] HTTPS on all client-server communication (NFR-005).
- [ ] No secrets in client-side source (NFR-006).
- [ ] No raw addresses persisted (NFR-007).
- [ ] Core flows meet WCAG 2.2 AA (NFR-015).
- [ ] Structured logging with correlation IDs operational (NFR-012, NFR-013).
- [ ] Health endpoint returns accurate status (NFR-011).

### Quality and Trust

- [ ] 0 copy integrity findings where UI text overstates certainty (SM-8).
- [ ] 100% of displayed results include visible source attribution and methodology version (SM-7).
- [ ] Search-to-result completion rate ≥ 85% on QA test address set (SM-1).
- [ ] No prohibited language from CONTENT_GUIDELINES §9 present in any UI string.

### Release Readiness

- [ ] All containers deploy to staging via CI/CD.
- [ ] Smoke tests pass on staging (health, config, geocode, assess).
- [ ] E2E test suite (Playwright) passes for demo script D-01 through D-10.
- [ ] Accessibility audit passes (axe-core, keyboard walkthrough).
- [ ] Log audit confirms no raw addresses or precise coordinates in production logs.
- [ ] Security checklist from `docs/architecture/07-security-architecture.md` §8 is complete.

---

## 9. Epic Rationale

### Epic 01 — Decision Closure and Delivery Baseline

Unresolved open questions block schema design, pipeline logic, API contracts, and UI controls. This epic forces all blocking decisions to be made, documented, and committed before any implementation begins. Without it, every downstream epic risks rework from mid-stream decision changes.

### Epic 02 — Cloud Infrastructure and CI/CD

Infrastructure must exist before the pipeline can upload COGs or the API can connect to PostgreSQL. This epic provisions all Azure resources, sets up Docker Compose for local development, and establishes the CI/CD pipeline. It produces the platform that all subsequent epics build on.

### Epic 03 — Geospatial Data Pipeline

The offline pipeline generates the COG exposure layers that the entire application serves. Without valid layers in Blob Storage and registered in PostgreSQL, the backend cannot resolve assessments and the frontend cannot render overlays. This is the most technically novel epic and carries the highest implementation risk.

### Epic 04 — Backend API Core

The API is the integration point between frontend and all backend services. This epic implements all five endpoints, the domain logic (ResultStateDeterminator, geography validation, layer resolution, exposure evaluation), structured logging, and the health endpoint. It produces a fully testable API that the frontend can consume.

### Epic 05 — Frontend Shell and Search Flow

The frontend shell, map initialization, and search-to-candidate flow must work before assessment results can be displayed. This epic establishes the Next.js project, MapLibre integration, search bar, geocoding API integration, candidate list, and location marker. It produces the first user-interactive surface.

### Epic 06 — Scenario Controls and Assessment UX

With the search flow working and the API available, this epic wires up the full assessment cycle: scenario and horizon controls, assessment API calls, all five result states in the result panel, exposure layer overlay via deck.gl, legend, stale request handling, loading states, error states, and the reset flow.

### Epic 07 — Transparency, Accessibility, and Content Compliance

Scientific honesty and accessibility are product pillars, not afterthoughts. This epic implements the methodology panel, ensures all copy matches CONTENT_GUIDELINES, externalizes strings for localization readiness, implements keyboard navigation and ARIA attributes, and validates responsive layout.

### Epic 08 — Testing, Security Hardening, and Release Readiness

The final epic writes and runs the full test suite, completes security hardening (CORS, CSP, Key Vault integration, log audit), executes the demo script, and validates all MVP exit criteria. It is the release gate.

---

## 10. Assumptions

| # | Assumption | Risk If Wrong |
|---|---|---|
| A-01 | Azure subscription is available with sufficient credits for ~$30–40/month MVP hosting | Infrastructure epic cannot proceed |
| A-02 | NASA AR6 and Copernicus DEM data are downloadable without access barriers | Pipeline epic is blocked |
| A-03 | Binary COG approach (0/1/NoData) is confirmed for exposure methodology | Pipeline rework if continuous values required |
| A-04 | TiTiler `/point` latency is ≤ 200ms on warm COG | Assessment latency may exceed NFR-003 |
| A-05 | PostGIS `ST_Within` with GIST index completes in ≤ 20ms | Assessment latency budget exceeded |
| A-06 | Nominatim is acceptable for development; production geocoder selected in Epic 01 | Geocoding works in dev only |
| A-07 | Container Apps cold start (10–30s) is acceptable with pre-demo warm-up | First demo request may timeout |
| A-08 | One engineer can sustain ~5 productive implementation days per week | Timeline extends proportionally |

---

## 11. Gaps and Contradictions

The following gaps or potential contradictions were identified during delivery planning:

| # | Item | Source | Impact | Resolution |
|---|---|---|---|---|
| G-01 | Architecture doc 12 lists OQ-01 (browser matrix) as non-blocking but NFR-008 requires browser support verification | `docs/architecture/12-risks-assumptions-and-open-questions.md` vs `docs/product/PRD.md` §13 | Browser testing scope unclear | Resolve during Epic 08; test against Chrome, Firefox, Safari, Edge latest 2 versions |
| G-02 | Phase 0 exit criteria in product roadmap require "CI/CD pipeline is operational" but architecture doc 08 §9 places full CI/CD in Phase 1 | `docs/product/ROADMAP.md` vs `docs/architecture/08-deployment-topology.md` | Sequencing ambiguity | Epic 02 establishes CI/CD for at least one container; full pipeline completed in Epic 04 |
| G-03 | Architecture doc 12 lists OQ-08 (shareable URLs) as Phase 2 but frontend architecture (03a) designs URL state from the start | `docs/architecture/12-risks-assumptions-and-open-questions.md` vs `docs/architecture/03a-frontend-architecture.md` §4.4 | Scope ambiguity | Implement URL state in Epic 06 as low-cost; do not advertise as a feature until OQ-08 is resolved |
| G-04 | Product ROADMAP says "environment separation (development, staging, production-like demo)" but architecture cost profile assumes one deployment | `docs/product/ROADMAP.md` Phase 0 vs `docs/architecture/08-deployment-topology.md` §8 | Budget and provisioning scope | Epic 02 provisions dev (Docker Compose) + staging (Azure). Production = staging for MVP portfolio demo |

---

## 12. Demo Script (Preserved from Product Roadmap)

These scenarios must pass without manual intervention before MVP is declared complete:

| # | Input | Expected State | Validates |
|---|---|---|---|
| D-01 | Known coastal location in the Netherlands | Modeled Coastal Exposure Detected | Core happy path |
| D-02 | Known coastal location in Portugal | Modeled Exposure or No Exposure | Southern Europe coverage |
| D-03 | Known coastal city in Italy | Modeled Exposure or No Exposure | Mediterranean coverage |
| D-04 | Inland European city (e.g., Prague) | Out of Scope | Coastal zone gating |
| D-05 | Inland European location far from coast | Out of Scope | Inland detection |
| D-06 | Non-European location (e.g., New York) | Unsupported Geography | Geography gating |
| D-07 | Ambiguous query with multiple candidates | Up to 5 ranked candidates | Multi-result handling |
| D-08 | Empty search submission | Inline validation, no request | Input validation |
| D-09 | Change scenario after initial result | Map and summary update | Control-change flow |
| D-10 | Change time horizon after initial result | Map and summary update | Horizon-change flow |

---

## 13. Reference Documents

### Product Documentation

| Document | Path | Role in Delivery |
|---|---|---|
| Product Requirements Document | `docs/product/PRD.md` | Primary source for FR, BR, NFR, AC, OQ |
| Product Vision & Strategy | `docs/product/VISION.md` | Strategic pillars constraining design decisions |
| User Personas | `docs/product/PERSONAS.md` | Informs UX priorities and demo scenarios |
| Competitive Analysis | `docs/product/COMPETITIVE_ANALYSIS.md` | Differentiation context |
| UX Content Guidelines | `docs/product/CONTENT_GUIDELINES.md` | Governs all UI copy, result states, prohibited language |
| Metrics Plan | `docs/product/METRICS_PLAN.md` | Defines success metrics and observability requirements |

### Architecture Documentation

| Document | Path | Role in Delivery |
|---|---|---|
| Architecture Index | `docs/architecture/README.md` | Reading order and document relationships |
| System Context | `docs/architecture/01-system-context.md` | System boundaries, actors, constraints |
| Container View | `docs/architecture/02-container-view.md` | Deployable units and communication patterns |
| Component View (API) | `docs/architecture/03-component-view.md` | Internal API structure and interfaces |
| Frontend Architecture | `docs/architecture/03a-frontend-architecture.md` | Route structure, state management, components |
| Runtime Sequences | `docs/architecture/04-runtime-sequences.md` | Sequence diagrams for all key flows |
| Data Architecture | `docs/architecture/05-data-architecture.md` | Schema, storage layout, data lifecycle |
| API and Contracts | `docs/architecture/06-api-and-contracts.md` | Endpoint definitions, request/response shapes |
| Security Architecture | `docs/architecture/07-security-architecture.md` | Threat model, secrets management, privacy |
| Deployment Topology | `docs/architecture/08-deployment-topology.md` | Azure resources, environments, CI/CD |
| Observability and Operations | `docs/architecture/09-observability-and-operations.md` | Logging, metrics, alerting, runbooks |
| Testing Strategy | `docs/architecture/10-testing-strategy.md` | Test pyramid, test data, CI gates |
| Architecture Decisions | `docs/architecture/11-architecture-decisions.md` | ADR records for all major choices |
| Risks and Open Questions | `docs/architecture/12-risks-assumptions-and-open-questions.md` | Blocking questions, assumptions, risk register |
| Domain Model | `docs/architecture/13-domain-model.md` | Entities, invariants, ubiquitous language |
| Integration Patterns | `docs/architecture/14-integration-patterns.md` | Provider integration, error handling, timeouts |
| Performance and Scalability | `docs/architecture/15-performance-and-scalability.md` | Latency budgets, optimization strategy |
| Geospatial Data Pipeline | `docs/architecture/16-geospatial-data-pipeline.md` | Offline pipeline: acquisition through publication |
