# Visual Mock Reconciliation Map

> **Status:** Active migration guide
>
> **Last updated:** 2026-08-04
>
> **Behaviour authority:** [PRD](../PRD.md)
>
> **Architecture authority:** [ADR-021](../../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)
>
> **Copy authority:** [Content guidelines](../CONTENT_GUIDELINES.md)

## Authority

The HTML pages under `pages/` are **visual direction**, not an authoritative
functional or content specification. They remain useful for composition,
spacing, visual hierarchy, responsive intent, map/result relationships, and
interaction exploration.

They predate ADR-021 and contain legacy assumptions about a runtime geocoder,
assessment API, scenario labels, horizon count, and result wording. When a mock
conflicts with the PRD, content guidelines, or ADR, those current documents
win. Production implementation must not copy a known legacy label merely to
match a screenshot.

The mocks should be regenerated after the static frontend reaches visual
implementation. Until then, reviewers must use the reconciliation below.

## Global differences

| Legacy mock concept | Current product contract | Implementation treatment |
|---|---|---|
| Street-address/geocoder search | Local search of a versioned European settlement catalog | Say city, town, village, or place; no runtime geocoding request |
| `geocoding` state | Web Worker index initialization or local query processing | Keep a subtle loading pattern; replace runtime-provider wording |
| Assessment API wait | Local boundary check and exact artifact lookup | Loading appears only while local work or required ranges complete |
| Five relative horizons | `2030`, `2050`, `2100` | Replace timeline labels and remove the extra options |
| NASA/Copernicus/IPCC as three “forecast models” | SSP1-2.6, SSP2-4.5, SSP5-8.5 scenario pathways | Use accurate scenario labels/descriptions; providers belong in source attribution |
| “Risk detected” | `Modeled coastal exposure detected` | Replace badge and supporting copy |
| “No risk detected” | `No modeled coastal exposure detected` | Replace badge; never use a safety-green meaning without explicit caveat |
| Mock as final visual authority | Mock as direction | Validate final UI through responsive screenshots and accessibility checks |
| Generic About page | Methodology plus public `/about/architecture` evidence | Extend information architecture; do not hide portfolio evidence in repository docs |

## Screen inventory and current interpretation

| File | Preserve as visual direction | Replace or reinterpret |
|---|---|---|
| `01-landing.html` | Map-led composition, prominent search, concise introduction, visible attribution | Search promise becomes settlements; initial content must remain semantic before map JavaScript loads |
| `02-search-loading.html` | Non-blocking progress feedback over stable layout | Means “Loading the place index…” or “Searching places…”, never a geocoder call |
| `03-candidates.html` | Candidate list, visible geographic context, keyboard selection pattern | Candidates come from local GeoNames index; show country/admin1 and do not imply address precision |
| `04-no-results.html` | Clear empty result and recovery action | Use local-catalog wording; do not describe a provider response |
| `05-assessing.html` | Keep marker/map context while work completes | Means local checks and/or immutable range loading, not server-side calculation |
| `06-exposure.html` | Result/map hierarchy, source access, scenario/horizon controls | Replace “Risk detected,” projection-number claims not in the contract, five horizons, and provider-named models |
| `07-no-exposure.html` | Parallel layout for a negative class | Replace “No risk detected” and safety-green semantics with the approved cautious state |
| `08-data-unavailable.html` | Distinct missing-data state and recovery guidance | Do not suggest a substitute scenario/year; distinguish scientific nodata from uncached network data |
| `09-inland.html` | Clear, recoverable scope outcome | Use “Outside the coastal analysis area”; do not imply distance means safety |
| `10-unsupported.html` | Clear, recoverable support outcome | Tie wording to the versioned Europe support geometry |
| `11-methodology.html` | Progressive-disclosure drawer | Add release ID, exact sources/licences, limitations, resolution, STAC, and provenance; use three scenarios/years |
| `12-error-geocoding.html` | Recoverable search-data error composition | Reinterpret as search index load/schema failure; there is no runtime geocoder |
| `13-error-assessment.html` | Recoverable data-delivery error composition | Reinterpret as missing/corrupt artifact or range failure; scientific nodata remains `DataUnavailable` |
| `14-about.html` | Long-form reading layout and source cards | Split/extend into methodology content and `/about/architecture` measured evidence |
| `index.html` | Developer-only screen navigation | Keep out of the production route set |

## Current state model

The UI may use transient presentation states, but completed assessments use
exactly the five domain states below.

| State | Visual mock starting point | Required correction |
|---|---|---|
| `ModeledExposureDetected` | `06-exposure.html` | Use modeled-exposure wording and active release context |
| `NoModeledExposureDetected` | `07-no-exposure.html` | Remove “no risk”; state that this is not a safety guarantee |
| `DataUnavailable` | `08-data-unavailable.html` | Identify scientific nodata; never substitute another combination |
| `OutOfScope` | `09-inland.html` | Explain Europe-but-outside-coastal-scope semantics |
| `UnsupportedGeography` | `10-unsupported.html` | Explain outside-versioned-support semantics |

Transient states include initial, search-index loading, searching, local
assessment/range loading, no matches, basemap degraded, offline range missing,
invalid release, and unexpected client error. They are not additional
scientific outcomes.

## Interaction requirements carried forward

The following ideas remain valuable if they pass responsive and accessibility
validation:

- search and results stay visually connected to the map;
- the selected marker remains distinct from exposure data;
- candidates and controls are keyboard navigable;
- the active scenario and absolute year remain visible;
- result, overlay, legend, URL, methodology, and release are synchronized;
- methodology is available without forcing users through it before a result;
- reset/new-search is obvious from every outcome;
- error and degraded states preserve valid prior context where safe;
- map colour is never the sole carrier of meaning.

## Required new visual states

The legacy mock set does not fully cover the target architecture. Production
design and screenshot evidence must add:

1. lazy search-index initialization and core/coastal shard progress if it is
   perceptible;
2. basemap unavailable while local search/assessment remains usable;
3. required layer not yet cached while offline;
4. content confirmed as available offline;
5. invalid or incomplete data release blocked safely;
6. architecture page with current release, pipeline, checks, cost, STAC, and
   provenance;
7. explicit synthetic/provisional-data notice before the real-data gate passes;
8. narrow mobile layouts for candidate selection, map/results, methodology,
   and attribution.

## Visual acceptance checklist

- [ ] Exactly three scenarios and `2030`/`2050`/`2100` are visible where
  controls appear.
- [ ] No production screenshot contains “Risk detected,” “No risk detected,”
  “NASA optimistic,” “Copernicus moderate,” or “IPCC worst case.”
- [ ] Search copy does not promise street addresses or live geocoding.
- [ ] Loading/error copy does not claim that an application server is
  calculating the result.
- [ ] All five domain states have distinct, accessible text and non-colour
  cues.
- [ ] Scientific nodata, uncached-offline data, and optional basemap failure
  are visually distinct.
- [ ] The exact scenario, absolute horizon, methodology, and release are
  present on every completed result.
- [ ] Data and map attribution remains visible at the relevant surfaces.
- [ ] Keyboard focus, reduced motion, zoom, contrast, and screen-reader output
  pass WCAG 2.2 AA review.
- [ ] Final screenshots are captured from the implemented static frontend and
  replace legacy mock authority in review artifacts.
