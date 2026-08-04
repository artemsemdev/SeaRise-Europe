# Architecture Decision Register

> **Status:** Current
> **Last reviewed:** 2026-08-04

This register contains only decisions that remain active in the accepted target
architecture. [ADR-021 — Static-First Offline Geospatial Architecture](adr/ADR-021-static-first-offline-geospatial-architecture.md)
is the authoritative architecture decision and resolves conflicts with earlier
records. Superseded implementation choices remain available in Git history,
not as active guidance in this document.

## Active decisions

| ID | Decision | Status | Current interpretation |
|---|---|---|---|
| ADR-002 | Keep client state minimal | Accepted | Use React local state by default; Zustand only for genuinely shared state. Immutable files are not a reason to add a server-state cache. |
| ADR-010 | Model five domain result states | Accepted | Preserve `ModeledExposureDetected`, `NoModeledExposureDetected`, `DataUnavailable`, `OutOfScope`, and `UnsupportedGeography` in the local browser engine. |
| ADR-014 | Keep explorer state in the URL | Accepted, amended | Browser URL APIs carry location, scenario, horizon, and pinned release; there is no dependency on Next.js routing. |
| ADR-015 | Use binary exposure methodology v1.0 | Accepted with validation gate | Remains provisional until ADR-021 Phase 0 proves source shape, datum, coastline connectivity, nodata, and representative control points. A failed spike requires a superseding methodology ADR. |
| ADR-016 | Support three SSP scenarios | Accepted | `ssp1-26`, `ssp2-45`, and `ssp5-85`. |
| ADR-017 | Default to SSP2-4.5 / 2050 | Accepted | Defaults remain `ssp2-45` and `2050`; the URL makes them explicit when shared. |
| ADR-018 | Use a 25 km coastal analysis zone | Accepted with validation gate | The current Natural Earth-derived zone is explicitly approximate. Reconfirm or replace it after comparison with the canonical Copernicus coastal product. |
| ADR-021 | Adopt static-first offline geospatial architecture | **Accepted; authoritative** | Offline build plane, immutable open artifacts, React/Vite browser runtime, local search/assessment, Cloudflare Static Assets + R2, and no runtime API/database/tile server. |

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

These rows do not authorize keeping the old services during the final target
state. The staged migration and parity gates in ADR-021 determine when their
implementation may be removed.

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
