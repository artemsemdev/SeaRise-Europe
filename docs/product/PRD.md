# SeaRise Europe — Product Requirements

> **Owner:** Artem Sem
>
> **Status:** Active target scope
>
> **Version:** 1.0
>
> **Last updated:** 2026-08-04
>
> **Architecture:** [ADR-021 — Static-First Offline Geospatial Architecture](../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md),
> amended by [ADR-024 — AR6 Regional Projection Contract](../architecture/adr/ADR-024-ar6-regional-projection-contract.md)
>
> **Visual and interaction authority:** [SeaRise Flight](Mock/SeaRise-Flight.html),
> governed by its [active reconciliation contract](Mock/MOCK_REQUIREMENTS_MAP.md)

## 1. Product summary

SeaRise Europe is a public, Europe-focused web explorer for scenario-based
regional relative sea-level projections. A user searches a city, town, or
village, selects one of three scenarios and one of three time horizons, and
receives a cautious, traceable AR6 median and likely range on an interactive
map.

The product is also a portfolio case study. It demonstrates how a data-heavy
geospatial experience can be fast, inexpensive, reproducible, and transparent
without a production application server, database, tile server, or runtime
geocoder. Scientific processing happens before publication; the browser reads
versioned artifacts and performs bounded search and projection lookup locally.

The static target is implemented under `src/web` and is the only product
baseline. Any legacy runtime code still present during Phase 2 removal is
neither a baseline nor a rollback path. The committed synthetic fixture proves
the application and release contracts, but it is not evidence of a
production-ready scientific release.

### Experience contract

The static application preserves the canonical Flight experience: its
editorial full-viewport and map-first composition, destination-led information
hierarchy, dominant settlement search, geographic flight/arrival character,
layered result panel, visible scenario/horizon controls, progressive evidence
disclosure, and responsive reprioritization. Reduced-motion and skip paths must
provide the same task without delay.

Only scientifically invalid mock content is replaced. Both binary exposure
cards map to `ProjectionAvailable`; the mock's unavailable and out-of-scope
cards map to `DataUnavailable` and `OutOfScope`; and
`UnsupportedGeography` is added as the fourth normal outcome. Terrain
comparison, modeled-water/flood meaning, binary classification, and property
or hazard claims are prohibited. ADR-024 changes those semantics, not the
canonical layout or interaction character.

## 2. Problem

Authoritative climate sources are valuable but difficult for non-specialists to
connect to a familiar place. Consumer maps can be easier to use, but often hide
methodology or imply property-level certainty. SeaRise Europe must make a
place-based result understandable without turning a scenario model into a
forecast, safety statement, or regulated flood-zone determination.

The existing multi-service implementation also imposes cold starts, network
chains, and operational cost on a read-only product whose source data changes
only by release. These costs delay the user's first result and weaken the
portfolio story. The product therefore distributes prebuilt, verifiable data
rather than recomputing static facts for every request.

## 3. Goals

### Product goals

1. Let a user find a European settlement and understand the IPCC AR6 projected
   regional relative sea-level change near it under a selected scenario and
   horizon.
2. Return useful local search results quickly, including small coastal villages
   and inland places that should resolve to `OutOfScope`.
3. Keep result language understandable, calm, and scientifically cautious.
4. Make source versions, licences, methodology, limitations, and data release
   visible in the product.
5. Remain useful after the application shell, search index, and required data
   ranges have been cached.

### Portfolio goals

1. Demonstrate mature architecture through appropriate simplification rather
   than service count.
2. Show reproducible geospatial processing, open formats, immutable releases,
   signed provenance, and executable quality budgets.
3. Provide a public `/about/architecture` page that connects technology choices
   to user value, cost, portability, and scientific integrity.
4. Keep a reliable, low-cost demo that does not depend on backend warm-up or
   cloud credentials in the browser.

## 4. Product invariants

- Scenarios are `ssp1-26`, `ssp2-45`, and `ssp5-85`.
- Horizons are exactly `2030`, `2050`, and `2100`.
- Defaults are `ssp2-45` and `2050`.
- A completed lookup has exactly one domain state: `ProjectionAvailable`,
  `DataUnavailable`, `OutOfScope`, or `UnsupportedGeography`.
- `OutOfScope` and `UnsupportedGeography` are valid outcomes, not errors.
- No result is a property-level forecast, probability, safety guarantee,
  engineering assessment, legal determination, insurance evaluation, mortgage
  guidance, or financial advice.
- Every displayed projection identifies its scenario, horizon, baseline,
  likely-range semantics, source grid location and distance, native resolution,
  methodology version, and data release.
- No result determines flooding, inundation, terrain exposure, property risk,
  or an absolute water level.
- The browser must not call `/assess`, `/geocode`, or `/config` in the target
  production flow.

## 5. Users

### Primary

Climate-aware residents, renters, buyers, and place researchers who want an
honest first-pass view of a European coastal location without GIS expertise.

### Secondary

- Educators, journalists, and science communicators who need a stable,
  explainable visual aid.
- Portfolio reviewers and technical evaluators who need evidence of product
  judgement, data integrity, architecture quality, and graceful edge cases.

Personas remain research hypotheses; see [PERSONAS.md](PERSONAS.md).

## 6. Scope

### In scope

- Anonymous, responsive, English-language web application.
- Search of a pinned, prebuilt GeoNames settlement catalog.
- Europe-wide core search plus complete active populated-place coverage within
  the versioned coastal analysis zone, subject to the source snapshot.
- Search by canonical, ASCII, and alternate place names, with country and
  first-level administration shown for disambiguation.
- Optional point refinement on the map after settlement selection.
- Local support/coastal boundary checks and exact source-grid projection lookup.
- Nine validated scenario/horizon combinations.
- MapLibre map, PMTiles overlay, marker, and accessible textual result.
- Data/methodology details, required attribution, static STAC catalog, and
  signed release provenance.
- Shareable URL state for location, scenario, horizon, and data release.
- Offline-capable shell, configuration, boundaries, loaded search index, and
  previously cached artifact ranges.

### Out of scope

- Street-address or parcel search in the baseline.
- Claims that GeoNames contains every real-world settlement.
- Coverage outside the versioned Europe support geometry.
- Inland hazards, river flooding, storm forecasting, or live alerts.
- Parcel-, engineering-, insurance-, mortgage-, or legal-grade conclusions.
- User accounts, server-side history, collaboration, or an administration UI.
- Full offline download of all Europe-wide layers on every device.
- Runtime scientific processing, application APIs, databases, and tile servers.

## 7. Functional requirements

### 7.1 Search and selection

**FR-001** The initial route shall show a meaningful text introduction, a
search control, and a Europe-focused map or map placeholder.

**FR-002** Focusing search or browser idle time shall initialize the prebuilt
core settlement index in a Web Worker without blocking first render.

**FR-003** Search shall be accent-insensitive and rank exact canonical names,
exact aliases, prefixes, then fuzzy matches. Population and administrative
importance are tie-breakers; coastal proximity is a final tie-breaker.

**FR-004** Results shall identify country and first-level administration and
shall remain keyboard accessible.

**FR-005** The core shard shall cover active European populated places with
population at least 500 plus national and administrative capitals. The coastal
shard shall add every qualifying active populated place in the coastal zone,
without a population threshold.

**FR-006** Selecting a settlement shall center the map, place a marker, write
shareable URL state, and start local scope validation.

**FR-007** A user may refine the selected point on the map. The product shall
make clear that a precise marker does not imply parcel-level model accuracy.

**FR-008** Empty and unmatched queries shall produce inline guidance without
removing the last valid result.

### 7.2 Scope and projection lookup

**FR-009** The browser shall validate coordinates and the versioned Europe
support geometry before reading projection data.

**FR-010** A point outside the support geometry shall return
`UnsupportedGeography`.

**FR-011** A point inside Europe but outside the versioned coastal analysis zone
shall return `OutOfScope`.

**FR-012** An in-scope point shall resolve the exact artifact for the active
scenario and horizon from the pinned release manifest.

**FR-013** Exact lookup shall choose the nearest source-native 1° grid location
using the ADR-024 haversine operator and shall return `ProjectionAvailable`
only when q0.167, q0.5, and q0.833 all exist at that location. It shall not
skip nodata, interpolate, or fall back to a tide-gauge location.

**FR-014** The UI shall never derive a scientific value from rendered colour.
It reads exact published projection values and source identity from the
analysis artifact.

**FR-015** A missing network range is a delivery/connectivity condition, not
evidence of zero sea-level change. The UI shall not guess or silently
substitute another artifact, grid location, scenario, or horizon.

### 7.3 Scenarios and horizons

**FR-016** The scenario control shall expose `ssp1-26`, `ssp2-45`, and
`ssp5-85` with accurate plain-language descriptions that do not rename a
scenario after a data provider.

**FR-017** The horizon control shall expose exactly `2030`, `2050`, and `2100`.

**FR-018** The first eligible projection lookup shall default to `ssp2-45` and
`2050`.

**FR-019** Changing scenario or horizon shall update the summary, overlay,
legend, URL, and source context as one consistent state without a new search.

### 7.4 Results and map

**FR-020** Every `ProjectionAvailable` result shall show the selected
place/point, scenario, horizon, q0.167/q0.5/q0.833 in metres, 1995–2014
baseline, medium-confidence likely-range meaning, source location and distance,
native 1° resolution, methodology version, and data release.

**FR-021** Every map-only meaning shall have an equivalent text representation.

**FR-022** Projection overlays shall remain visually distinct from the selected
marker and basemap, and the legend shall match the active scenario, horizon,
and displayed statistic.

**FR-023** Basemap failure shall not prevent local search, scope validation, or
projection lookup; the UI shall show a clear degraded-map state.

**FR-024** Result copy shall follow
[CONTENT_GUIDELINES.md](CONTENT_GUIDELINES.md) and shall never call a location
safe, flooded, or free from risk.

### 7.5 Transparency and portfolio evidence

**FR-025** Every result shall provide a direct path to methodology, sources,
limitations, licence attribution, and the pinned release manifest.

**FR-026** `/about/architecture` shall explain the static-first architecture,
data pipeline, artifact types, current release and commit, quality gates,
representative performance, cost, portability, STAC catalog, and signed
provenance.

**FR-027** The architecture page shall distinguish synthetic/demo data from a
validated scientific release and shall not claim a completed gate that has not
passed.

### 7.6 Offline and recovery

**FR-028** The service worker shall version caches by application build and
`dataReleaseId` and shall never mix ranges from different releases.

**FR-029** The product may label content “available offline” only when the
required shell, index, boundaries, and data ranges are actually cached.

**FR-030** When uncached data is unavailable, the UI shall identify what is
missing and offer a retry when connectivity returns.

**FR-031** Reset shall clear the selected location, result, and overlay and
return to the initial state. It need not erase immutable application caches.

## 8. Core user journeys

### Coastal settlement

1. The user opens the static application; no backend warm-up is required.
2. Search initializes locally and returns ranked settlements.
3. The user selects a place; the browser validates support and coastal scope.
4. The browser reads only the ranges required for the default
   `ssp2-45`/`2050` projection.
5. The UI shows one result state, synchronized map context, sources, and
   limitations.
6. Scenario/horizon changes reuse the selected point and update local state.

### Inland settlement

The local core index returns the place, after which boundary validation returns
`OutOfScope`. This is useful feedback, not a failed search.

### Unsupported coordinates

A point outside the versioned support geometry returns
`UnsupportedGeography`. The baseline local catalog is Europe-scoped, so this
flow is most commonly reached through a shared URL or map refinement.

### Offline return visit

The cached shell and loaded index remain usable. A lookup succeeds only
when its required boundaries and artifact ranges are cached; otherwise the UI
states the connectivity limitation and preserves the selection for retry.

## 9. Data and external dependencies

| Need | Target source or component | Runtime role |
|---|---|---|
| Settlements | Pinned GeoNames snapshot and alternate names | Serialized local index; no geocoder request |
| Sea-level inputs | Pinned IPCC AR6 release | Offline processing only |
| Support/coastal geometry | Versioned approved geometry | Local scope validation |
| Basemap | OpenFreeMap with required OSM/OpenMapTiles attribution | Optional visual context; non-authoritative |
| Projection | Nine exact AR6 projection COGs plus visual PMTiles | Byte-range reads from immutable object storage |
| Discovery/provenance | Manifest, static STAC, SLSA/Cosign bundle | Transparency and release verification |

Raw sources remain in ignored local/CI storage unless redistribution is
explicitly permitted. Public artifacts are versioned and immutable.

## 10. Non-functional requirements

### Performance and delivery

- Initial application JavaScript: at most 250 KiB Brotli, excluding lazy
  map/search chunks.
- Lighthouse performance, accessibility, best practices, and SEO: at least 90
  on the agreed mobile profile.
- Search p95 after worker initialization: under 50 ms.
- Search worker initialization on reference mobile hardware: under 1 second.
- Local projection lookup p95 after required data is cached: under 100 ms.
- Large artifacts must support `HEAD` and byte-range `GET` with correct CORS,
  ETag, and immutable cache headers.
- The normal production flow must make zero application API calls.

### Quality, accessibility, and browsers

- Core flows meet WCAG 2.2 AA and work without a mouse.
- Core meaning remains available without colour and outside the map.
- Support the two most recent stable releases of Chrome, Firefox, Safari, and
  Edge at launch.
- All nine scenario/horizon artifacts, approved golden points, schemas,
  checksums, licences, and attribution must pass release gates.

### Privacy and security

- No provider keys or secrets in the browser bundle.
- No project-controlled server receives user search text or coordinates in the
  baseline.
- Analytics, if added, must be privacy reviewed, aggregate-only or opt-in, and
  must exclude raw queries, place names, coordinates, and shareable URL state.
- Frontend dependencies and published artifacts must be locked, scanned,
  checksummed, and covered by release provenance.

## 11. Success criteria

1. At least 90% of first-time pilot users can find a test place, obtain a
   result, and correctly explain that it is scenario-based within two minutes.
2. At least 80% can distinguish all four domain states in comprehension tests.
3. Every tested result shows its scenario, horizon, methodology, release, and
   required attribution.
4. The defined search, projection lookup, Lighthouse, artifact, scientific, and
   offline fitness functions pass before release.
5. Scripted demos cover at least three coastal, three inland, one nodata, and
   one unsupported case without backend services or cloud credentials in the
   browser.
6. A portfolio reviewer can identify the product value, scientific limits,
   static-first trade-off, and data provenance within a three-minute walkthrough.

Detailed measurement is in [METRICS_PLAN.md](METRICS_PLAN.md).

## 12. Risks and dependencies

| Risk | Mitigation |
|---|---|
| Users infer parcel-level certainty | Conservative copy, resolution disclosure, persistent methodology access, and comprehension testing |
| Users interpret a coarse regional projection as a local flood result | Show native 1° resolution, source-grid distance, likely-range meaning, and persistent no-flood/no-property-risk copy |
| Upstream dimensions or vertical datums differ from pipeline assumptions | Inspect pinned real sources before Europe-wide processing; fail publication on unresolved semantics |
| The settlement source is incomplete or ambiguous | Define coverage operationally, show administration/country, preserve aliases, and publish snapshot/QA statistics |
| Large artifacts exceed device/network budgets | Measure regional spike, use range requests and lazy loading, set cache limits, and avoid mandatory full-Europe download |
| Public basemap is unavailable | Treat it as optional context and retain textual/local projection functionality |
| Source licence or attribution is incomplete | Block publication until every artifact maps to reviewed source metadata |
| Portfolio claims get ahead of implementation | Generate evidence from manifests/CI and label migration/demo state honestly |

## 13. Open product decisions

ADR-021 closes the runtime architecture, search strategy, scenario set,
horizons, defaults, baseline host, and baseline basemap. The remaining product
decisions are:

1. Final Europe support geometry, including transcontinental-state handling.
2. Whether the current Natural Earth-derived 25 km coastal zone is confirmed
   or replaced after comparison with the canonical Copernicus product.
3. Final plain-language scenario descriptions after scientific/content review.
4. Whether privacy-respecting analytics provide enough value to enable at all.
5. Whether a measured, user-initiated regional offline download fits browser
   storage budgets.

Street-address search is not an open MVP decision. It is a future capability
that requires a separate ADR because it changes privacy, cost, and offline
behaviour.

## 14. Release acceptance criteria

- [ ] The locked IPCC AR6 members have completed offline source and
  implementation parity; synthetic fixtures are clearly labelled.
- [ ] Search finds the approved multilingual, duplicate-name, coastal-village,
  inland, and boundary test fixtures with deterministic ranking.
- [ ] Each of the four domain states is covered by an accessible end-to-end
  browser test.
- [ ] Exactly nine scenario/horizon combinations pass manifest, schema,
  checksum, range, and golden-point tests.
- [ ] Scenario/horizon changes keep result, overlay, legend, URL, methodology,
  and release identity synchronized.
- [ ] Offline tests prove supported cached flows and honest failure for missing
  ranges.
- [ ] Network assertions show no calls to `/assess`, `/geocode`, or `/config`.
- [ ] Required data and basemap attribution is visible.
- [ ] Product copy passes the prohibited-language and disclaimer review.
- [ ] `/about/architecture` shows measured evidence and current implementation
  status rather than planned claims.
- [ ] All performance, accessibility, privacy, security, and provenance gates
  in ADR-021 pass.
