# Static-First Migration Plan

> **Status:** Active
> **Last updated:** 2026-08-04
> **Decision source:** [ADR-021](../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)

## Purpose

This is the only active technical delivery plan for SeaRise Europe. The former
eight-epic Azure/backend plan was removed after ADR-021 replaced its target
architecture.

The repository is currently in a transition state:

- the checked-in application still implements the legacy Next.js, .NET,
  PostGIS, TiTiler, and Docker Compose stack;
- the accepted target is a React/Vite static application backed by immutable
  browser-ready artifacts;
- production migration has not started;
- the real IPCC/Copernicus pipeline has not passed its required end-to-end
  scientific validation;
- the current checked-in raster is demonstration data and must not be
  represented as a production scientific release.

The old runtime remains only as a comparison baseline until parity and quality
gates pass. New features must not increase its production footprint.

## Delivery principles

1. Prove real data before migrating the runtime.
2. Define and validate public artifact contracts before consuming them.
3. Keep every change reviewable and independently testable.
4. Maintain an executable local fixture release at every stage.
5. Run old/new parity checks before deleting legacy components.
6. Publish no scientific layer without licence, checksum, provenance, and
   golden-point evidence.
7. Prefer open-source tools and portable formats.
8. Keep the normal production request path backend-free.

Per `AGENTS.md`, implementation work should be split into focused pull requests,
normally 100–400 changed lines and no more than about 800 for mechanical work.
Use Conventional Commits and the repository pull-request template.

## Current baseline

| Area | Current repository | Accepted target |
|---|---|---|
| Frontend | Next.js 14 / React 18 | React 19 / Vite 8 static build |
| Search | Runtime geocoder through .NET API | GeoNames index in a Web Worker |
| Assessment | .NET orchestration + PostGIS + TiTiler | Browser boundary checks + exact COG lookup |
| Map layers | TiTiler reads COGs | MapLibre reads PMTiles ranges from object storage |
| Configuration | PostgreSQL via `/v1/config/*` | Versioned JSON manifest/config |
| Data processing | Python modules; synthetic local demo | Reproducible real-data offline release pipeline |
| Hosting | Azure design, not provisioned | Workers Static Assets + R2 custom domain |
| Infrastructure | Terraform for Azure | OpenTofu for static host/object delivery |
| Provenance | Source notes and tests | Checksums + STAC + SLSA + Cosign |

## Workstream 0 — scientific proof

This workstream blocks a production data release and destructive removal of the
legacy assessment path.

- [ ] Pin and download the exact IPCC AR6 source release.
- [ ] Record source URL, version/date, licence, size, and SHA-256.
- [ ] Inspect its actual dimensions, coordinate model, quantiles, units, and
  missing values.
- [ ] Pin the Copernicus DEM product and document vertical datum and licence.
- [ ] Compare the current Natural Earth-derived 25 km coastal approximation
  with the canonical Copernicus coastal product.
- [ ] Decide and version the Europe support geometry, including
  transcontinental-state handling.
- [ ] Build a representative regional slice end to end.
- [ ] Validate coordinate-to-pixel parity between Python and TypeScript.
- [ ] Review connectivity-related false positives and decide whether
  methodology `v1.0` remains valid.
- [ ] Record artifact size, build duration, browser memory, range-request count,
  and lookup latency.

Exit evidence:

- a source manifest with valid hashes and licences;
- a regional fixture release using the public artifact layout;
- reviewed golden locations covering exposed, unexposed, nodata, inland, and
  unsupported cases;
- a written methodology decision with no unresolved publication blocker.

## Workstream 1 — artifact contracts and pipeline

- [ ] Add JSON Schemas for release manifest, scenarios, methodology, source
  attribution, and search records.
- [ ] Add a deterministic release-directory builder.
- [ ] Use DuckDB Spatial for GeoNames normalization, support/coastal joins,
  duplicate checks, and GeoParquet output.
- [ ] Produce `europe-core` and `europe-coastal` search shards from a pinned
  GeoNames snapshot.
- [ ] Produce nine exact analysis COGs with nearest-neighbour class semantics.
- [ ] Produce nine visual PMTiles archives from the same classified arrays.
- [ ] Produce PMTiles support/coastal geometry.
- [ ] Generate and validate a static STAC catalog.
- [ ] Generate an artifact inventory, SHA-256 checksums, and data-quality
  summary.
- [ ] Generate SLSA-compatible provenance and sign the manifest with Cosign.
- [ ] Provide a small committed fixture release; keep large/raw data ignored.

Exit evidence:

- two consecutive builds from identical inputs produce identical public
  contracts and equivalent artifacts;
- all nine scenario/horizon combinations pass validation;
- all qualifying GeoNames records are accounted for;
- COG and PMTiles validators, schemas, STAC validation, licences, and hashes
  pass in CI.

## Workstream 2 — static browser application

- [ ] Establish the React 19, TypeScript, and Vite 8 application shell.
- [ ] Preserve semantic first paint, responsive layout, and WCAG 2.2 AA
  behaviour.
- [ ] Load the pinned release manifest and reject malformed/incomplete data.
- [ ] Add MapLibre and the PMTiles protocol as lazy chunks.
- [ ] Add the local search Web Worker and measured ranking fixtures.
- [ ] Implement local Europe/coastal boundary checks.
- [ ] Implement exact COG pixel lookup and five-state result mapping.
- [ ] Keep location, scenario, horizon, and release in shareable URL state.
- [ ] Add versioned service-worker caches and honest offline indicators.
- [ ] Add graceful basemap failure; assessment must remain functional.
- [ ] Add `/about/architecture` with release/provenance/quality evidence.
- [ ] Remove runtime requests to `/geocode`, `/assess`, and `/config`.

Exit evidence:

- the complete fixture journey passes without an application API;
- old/new parity is documented for the approved golden set;
- search and assessment performance budgets pass on the reference mobile
  profile;
- accessibility, content-language, responsive, and offline tests pass.

## Workstream 3 — delivery and operations

- [ ] Create OpenTofu for Workers Static Assets, R2, the data custom domain,
  CORS, cache policy, and DNS.
- [ ] Separate preview and production prefixes/buckets.
- [ ] Add CI jobs for build, schemas, scientific QA, range requests, Lighthouse,
  accessibility, dependency review, provenance, and signatures.
- [ ] Use protected environments and least-privilege publish credentials.
- [ ] Publish immutable release paths; never overwrite a released artifact.
- [ ] Add synthetic checks for site, manifest, search index, `HEAD`, and partial
  `GET`.
- [ ] Add cost/storage/request reporting and budget notifications.
- [ ] Exercise rollback to the previous app/release pairing.

Exit evidence:

- production-like preview serves correct CORS, range, ETag, and immutable cache
  headers;
- no secret appears in the frontend bundle or repository;
- measured monthly usage fits the recorded cost model;
- rollback is demonstrated, not merely documented.

## Workstream 4 — legacy removal

This work begins only when Workstreams 0–3 have passed their exit criteria.

- [ ] Remove the ASP.NET Core API and its tests/deployment definitions.
- [ ] Remove PostgreSQL/PostGIS schema, seeds, and infrastructure.
- [ ] Remove TiTiler and Azurite/blob-seed runtime scaffolding.
- [ ] Remove runtime geocoder clients and Azure Maps secret/configuration.
- [ ] Remove Next.js runtime configuration and unused server-state libraries.
- [ ] Reduce Docker/local tooling to pipeline-only needs, if still useful.
- [ ] Remove superseded Terraform and Azure deployment files.
- [ ] Re-run secret, dependency, licence, link, and documentation audits.
- [ ] Update repository structure diagrams to match the final filesystem.

Exit evidence:

- repository search finds no active production reference to the retired stack;
- build/test/deploy instructions use only the static architecture;
- a new contributor can run the fixture app without Docker or cloud keys;
- the public architecture page matches measured production behaviour.

## Recommended pull-request sequence

| Order | Focused change | Depends on |
|---:|---|---|
| 1 | Inspect and pin one real IPCC source snapshot | None |
| 2 | Build one-region scientific fixture and methodology evidence | 1 |
| 3 | Define manifest/config/search JSON Schemas | 2 |
| 4 | Build GeoNames core/coastal GeoParquet datasets | 3 |
| 5 | Serialize and benchmark the Web Worker search index | 4 |
| 6 | Produce/verify regional COG and PMTiles artifacts | 2–3 |
| 7 | Add STAC, checksums, provenance, and signing | 3, 6 |
| 8 | Introduce the Vite static shell beside the legacy frontend | 3 |
| 9 | Add local search and boundary validation | 4–5, 8 |
| 10 | Add exact exposure lookup and map overlay | 6, 8 |
| 11 | Add offline caching and architecture evidence page | 7, 9–10 |
| 12 | Provision preview static hosting and R2 via OpenTofu | 7–8 |
| 13 | Run parity, performance, accessibility, and cost gates | 9–12 |
| 14 | Switch production and delete the legacy runtime | 13 |

## Required pull-request evidence

Use the repository PR template. In addition:

- data changes include source/checksum/licence and before/after statistics;
- scientific changes include golden-point or array-level comparisons;
- UI changes include screenshots and accessibility verification;
- delivery changes include preview URLs, relevant headers, cost impact, and
  rollback notes;
- deletions name the passed gate that made each component safe to retire.

## Active reference artifacts

- [Methodology specification](../methodology.md) — provisional
  until Workstream 0 passes.
- Accessibility and content evidence for the legacy frontend is local build
  output, not an authoritative target-architecture artifact; both audits must
  be regenerated for the static frontend.

Completed work is tracked in pull requests and immutable release manifests,
not by preserving obsolete epic documents.
