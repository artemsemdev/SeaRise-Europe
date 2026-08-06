# SeaRise Europe — Product Vision and Strategy

> **Owner:** Artem Sem
>
> **Status:** Active
>
> **Version:** 1.0
>
> **Last updated:** 2026-08-04

## Vision

> Make scenario-based regional sea-level projections understandable for people
> exploring European places, without overstating what the science can say.

SeaRise Europe connects authoritative climate data to a familiar city, town,
or village. It gives a non-specialist a clear result, visible assumptions, and
an honest reason when the product cannot answer.

The project has a second, equally explicit purpose: it is a portfolio case
study in architectural judgement. Its engineering story is that deterministic
geospatial work is moved out of the user request path, published as verifiable
open artifacts, and delivered quickly without a runtime backend, database, or
tile server.

## The problem

Climate tools commonly fail in one of two ways:

- authoritative research interfaces require substantial domain knowledge;
- simple consumer maps hide methodology or imply property-level certainty.

SeaRise Europe occupies the space between them: consumer-level clarity with
scientific restraint and inspectable evidence. It is not trying to turn a
regional scenario model into an address-level prediction.

The former multi-service architecture created a similar mismatch on the
engineering side. A read-only data product did not need a database and several
request-time services. Static-first delivery improves the first interaction,
offline resilience, cost, and explainability while keeping the complex
scientific work in a reproducible build pipeline.

## Strategic pillars

### 1. Scientific honesty

Every result is scenario-based, release-specific, and bounded by known
limitations. The four result states remain distinct. `ProjectionAvailable`
reports a median and likely range; it never implies flooding, exposure, or
safety, and missing data is never treated as a zero result.

### 2. Place-based clarity

The primary interaction is “find a settlement, compare scenarios, understand
the result.” Users do not need to know coordinates, file formats, or projection
terminology before they can start. Search includes coastal villages as well as
larger cities and inland places needed to explain scope.

### 3. Transparency as product value

Every result links to source versions, methodology, limitations, attribution,
and the pinned data release. The architecture page exposes artifact sizes,
quality gates, performance, cost, STAC metadata, and signed provenance.

### 4. Fast and offline-capable by design

The application shell and search are local after download. Assessment reads
only the required immutable artifact ranges. Cached places and data remain
usable without a connection, while uncached data fails honestly rather than
being guessed.

### 5. Minimal scope, maximum depth

The baseline is Europe, regional relative sea-level projection near the coast,
three scenarios, and three
horizons. Street addresses, inland hazards, accounts, and live alerts are not
quietly pulled into the MVP.

### 6. Modern technology with a reason

React, Vite, MapLibre, PMTiles, COG, DuckDB Spatial, GeoParquet, STAC,
OpenTofu, SLSA, and Sigstore are used where they improve user experience,
portability, reproducibility, or trust. Component count is not treated as a
measure of seniority.

## Audience

| Audience | Primary need | Product promise |
|---|---|---|
| Climate-aware resident or place researcher | Understand a European place without GIS expertise | A quick, cautious first-pass result with visible limitations |
| Educator or science communicator | Explain scenarios and uncertainty reliably | Stable visual comparison with citable sources and methodology |
| Portfolio reviewer or technical evaluator | Assess end-to-end judgement | Measured evidence of product, data, architecture, and operational quality |

These audiences are working hypotheses until validated through research; see
[PERSONAS.md](PERSONAS.md).

## Positioning

SeaRise Europe is a transparent, scenario-based regional sea-level projection explorer for
European settlements. It combines a simple place-search experience with
versioned scientific artifacts and explicit limitations. Unlike a conventional
request-time application, it precomputes deterministic geospatial work and
delivers a portable, backend-free browser experience.

This is a positioning hypothesis, not a claim that no other product shares any
of these attributes. Comparative claims require current evidence; see
[COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md).

## Product principles

1. **Honest before dramatic.** Remove or qualify a visualization that implies
   unsupported certainty.
2. **Answer before detail.** Give the result first; make methodology easy to
   inspect without blocking the core journey.
3. **Explicit state before silent fallback.** Show scope, nodata, connectivity,
   and degraded-map conditions directly.
4. **Version what a user can rely on.** Pin the data release, methodology,
   scenarios, horizons, and source attribution.
5. **Local computation before operational infrastructure.** Add a runtime
   service only after measurement proves a static solution insufficient and a
   separate ADR accepts the trade-off.
6. **Evidence before portfolio claims.** Show actual checks, sizes, timings,
   licences, and provenance; label planned work as planned.
7. **Portability before provider lock-in.** The product contract is static
   HTTPS plus open formats, not a particular cloud API.

## Long-term direction

Possible future modules include storm-surge context, land subsidence,
adaptation infrastructure, additional geographies, localization, and
user-controlled regional offline packs. Each requires suitable data,
methodology, licences, performance evidence, and a product decision. The
baseline must not present these as implied coverage.

Exact street-address search is a separate future capability because it changes
privacy, dataset requirements, offline behaviour, and cost.

## What the product is not

- Not a property, engineering, insurance, mortgage, legal, or financial tool.
- Not a real-time weather, flood-alert, or emergency service.
- Not a probabilistic forecast of a specific flood event.
- Not a claim to enumerate every real-world European settlement.
- Not a global or inland-hazard product in the baseline.
- Not a scientific research environment or substitute for peer review.
- Not a showcase of infrastructure for its own sake.
