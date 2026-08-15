# Architecture Decision Register

> **Status:** Current
> **Last reviewed:** 2026-08-16

This register contains only decisions that remain active in the accepted target
architecture. [ADR-021 — Static-First Offline Geospatial Architecture](adr/ADR-021-static-first-offline-geospatial-architecture.md)
is the authoritative architecture decision and resolves conflicts with earlier
records. Superseded implementation choices remain available in Git history,
not as active guidance in this document.

## Active decisions

| ID | Decision | Status | Current interpretation |
|---|---|---|---|
| ADR-002 | Keep client state minimal | Accepted | Use React local state by default; Zustand only for genuinely shared state. Immutable files are not a reason to add a server-state cache. |
| ADR-010 | Model five domain result states | Superseded by ADR-024 | The projection product uses `ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, and `UnsupportedGeography`; the two binary exposure states remain historical. |
| ADR-014 | Keep explorer state in the URL | Accepted, amended | Browser URL APIs carry location, scenario, horizon, and pinned release; there is no dependency on Next.js routing. |
| ADR-015 | Use binary exposure methodology v1.0 | Superseded by ADR-023 and ADR-024 | The direct AR6-change versus DEM comparison is prohibited; the target product reports AR6 projections without classifying terrain. |
| ADR-016 | Support three SSP scenarios | Accepted | `ssp1-26`, `ssp2-45`, and `ssp5-85`. |
| ADR-017 | Default to SSP2-4.5 / 2050 | Accepted | Defaults remain `ssp2-45` and `2050`; the URL makes them explicit when shared. |
| ADR-018 | Use a 25 km coastal analysis zone | Accepted, amended by ADR-024 | The versioned Natural Earth-derived zone defines product scope only; it is not a flood-reach or exposure boundary. |
| ADR-021 | Adopt static-first offline geospatial architecture | **Accepted; product contract amended by ADR-024** | Offline build plane, immutable open artifacts, React/Vite browser runtime, local search/lookup, Cloudflare Static Assets + R2, and no runtime API/database/tile server. |
| ADR-023 | Use an uncertainty-aware EGM2008 mean-water baseline | Superseded for publication by ADR-024 | Historical acquisition and no-go evidence is retained; its terrain-classification path cannot produce a release. |
| ADR-024 | Report AR6 regional relative sea-level projections | **Accepted; recovery gate approved** | Use one source-native 1° grid for map and point lookup, report q0.167/q0.5/q0.833 relative to 1995–2014, and never classify flooding or terrain exposure. Trusted #110 evidence and the owner disposition opened Phase 1. |
| ADR-025 | Accelerate repository cutover to the static runtime | **Accepted** | Phase 2 removes the superseded repository runtime after target coverage exists. Git history is the source rollback; external cloud cleanup still requires separate explicit approval. |

## Historical safety-gate decision

| ID | Decision | Status | Current interpretation |
|---|---|---|---|
| ADR-022 | Stop publication at the Phase 0 source/geography gate | Superseded for publication by ADR-024 | Its fail-closed terrain/datum evidence remains immutable, but terrain reconciliation and independent scientific review are not inputs to the AR6 projection product. |

## Decisions superseded by ADR-021

ADR-021 replaces the active use of these choices:

| Earlier ID | Superseded choice | Accepted replacement |
|---|---|---|
| ADR-001 | Next.js App Router and server runtime | Static React 19 + TypeScript application built with Vite 8 |
| ADR-003 | TanStack Query for runtime API/server state | Direct immutable artifact loading with browser/Service Worker caches |
| ADR-004 | ASP.NET Core application API | Deterministic in-browser assessment over published artifacts |
| ADR-005, ADR-008 | Runtime PostgreSQL/PostGIS | DuckDB Spatial in the offline build plane; no production database |
| ADR-006 | TiTiler runtime tile service | PMTiles/CDN delivery plus analysis-grade COG lookup |
| ADR-007 | COG as the only raster delivery representation | COG for exact analysis and PMTiles for visual map delivery until bit-exact consolidation is proven |
| ADR-009 | Anonymous API and rate limiting | Anonymous static application with CDN/object-storage abuse controls only |
| ADR-011 | Database-backed dataset history | Immutable release directories, manifest, static STAC, provenance, and signatures |
| ADR-012 | API stale-request suppression | Browser cancellation/version checks and pinned immutable release IDs |
| ADR-013 | Avoid CDN in early production | Edge-cached static/object delivery is the production baseline |
| ADR-019 | Azure Maps geocoder | Pinned GeoNames catalogs and a prebuilt Web Worker search index |
| ADR-020 | Azure Maps basemap | MapLibre with OpenFreeMap as non-authoritative visual context |

These rows do not authorize keeping the old services in the target state.
ADR-025 amends the ADR-021 sequence: their repository implementation is removed
during Phase 2 after equivalent-or-stronger static coverage exists.

## Decision rules

A new ADR is required before introducing any of the following:

- a runtime API, edge business logic, database, queue, or tile server;
- user accounts, user-generated content, authentication, or server-side state;
- paid exact-address geocoding or collection of user search/coordinate data;
- a change to supported scenarios, horizons, defaults, domain states, coastal
  scope, or scientific methodology;
- a proprietary artifact format that breaks the hosting portability contract;
- paid always-on compute or a material recurring-cost increase;
- removal of analysis COGs in favour of direct PMTiles lookup without bit-exact
  parity evidence.

Implementation details that stay inside ADR-021 constraints—such as choosing
between measured open-source search libraries—may be recorded in a short design
note and fitness tests rather than a new ADR.

## ADR lifecycle

Use `Proposed`, `Accepted`, `Superseded`, or `Rejected`. An accepted ADR is not
silently edited to reverse a decision; create a superseding ADR and update this
register. Every ADR states the decision, context, alternatives, consequences,
migration/rollback impact, and measurable acceptance criteria.
