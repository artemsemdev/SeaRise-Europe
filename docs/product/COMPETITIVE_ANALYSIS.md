# SeaRise Europe — Product Landscape and Positioning

> **Owner:** Artem Sem
>
> **Status:** Active positioning hypothesis
>
> **Version:** 1.0
>
> **Last updated:** 2026-08-04

## Purpose and limits

This document guides positioning and product priorities. It is not a complete
or continuously monitored market survey. Features, availability, licences, and
geographic coverage of external tools can change; verify them against the
provider's current documentation before publishing a comparative claim.

SeaRise Europe should not claim to be “the only” product with a feature unless
a fresh, documented review supports it. Its defensible portfolio story does
not require that claim.

## Landscape

| Category | Representative products | Typical strength | Gap relevant to SeaRise Europe |
|---|---|---|---|
| Scientific projection explorers | NASA/IPCC AR6 Sea Level Projection Tool; PROTECT | Authoritative scenario exploration and scientific depth | Higher learning curve for a simple place-first journey |
| Institutional climate portals | Climate-ADAPT and national portals | Broad, curated policy and adaptation context | Discovery breadth can outweigh one focused interaction |
| Consumer coastal-risk maps | Climate Central Coastal Risk Screening Tool and similar products | Immediate visual exploration and broad reach | Methodology/state distinctions may not be central to the interaction |
| Simplified elevation “water level” maps | FloodMap-style tools | Very low interaction cost | Can encourage users to infer hydrodynamics or precision not represented by a simple threshold |
| Commercial property-risk products | Market-specific real-estate risk services | Property workflow integration and report-like outputs | Different geography, commercial model, and claims from this public educational product |

Useful primary starting points for periodic review:

- [NASA Sea Level Projection Tool](https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool/)
- [Climate-ADAPT sea-level projection tool record](https://climate-adapt.eea.europa.eu/en/metadata/tools/sea-level-projection-tool)
- [PROTECT project](https://protect-slr.eu/)
- [Climate Central Coastal Risk Screening Tool](https://coastal.climatecentral.org/)

These products are references, not endorsed dependencies of the target
runtime.

## Positioning axes

SeaRise Europe aims to combine four qualities:

1. **Scientific restraint:** five explicit outcomes, cautious copy, and no
   property-level claim.
2. **Place-based clarity:** local settlement search across European cities,
   towns, and coastal villages.
3. **Inspectable evidence:** source snapshots, licences, methodology, STAC,
   checksums, quality results, and signed provenance.
4. **Static-first delivery:** no application backend, runtime database,
   geocoding request, or tile server in the normal production path.

This combination is the product hypothesis to test. It should be described as
a deliberate focus, not as proof that every alternative lacks one of these
qualities.

## Differentiation

### For a place researcher

- A settlement search reaches a result without requiring SSP or GIS knowledge
  up front.
- `NoModeledExposureDetected`, `DataUnavailable`, `OutOfScope`, and
  `UnsupportedGeography` are visibly different.
- The result always carries scenario, horizon, release, resolution limits, and
  methodology.

### For an educator

- Shareable state pins a reproducible data release rather than silently moving
  to a later dataset.
- The experience can remain usable with cached shell, search, and data ranges.
- Sources and limitations are in the product, not only in repository notes.

### For a portfolio reviewer

- Architecture complexity is concentrated in a reproducible offline pipeline,
  where it creates value, and removed from the user request path.
- Open formats keep the product portable across static/object hosts.
- Executable budgets and signed provenance turn architecture claims into
  inspectable evidence.
- The product states whether the current data is synthetic, provisional, or a
  validated release.

## What is intentionally not a differentiator

- Parcel or street-address precision.
- Real-time flood warnings.
- A proprietary risk score.
- Global coverage.
- Photorealistic inundation simulation.
- A large cloud-service topology.

Competing on these dimensions would change the method, audience, risk, and
cost, and would require a separate product decision.

## Strategic risks

| Risk | Response |
|---|---|
| Institutional or consumer tools improve place-first UX and transparency | Compete on the complete evidence chain, offline/static delivery, and focused Europe experience; avoid unsupported exclusivity claims |
| Local settlement search feels less precise than an address geocoder | Set expectations clearly, retain map refinement, improve aliases/ranking, and treat exact address search as a separately justified capability |
| Static artifacts are mistaken for stale data | Show snapshot/build dates and release history; define an intentional refresh process |
| “Free” hosting becomes paid with traffic or dataset growth | Publish a dated cost model and portable host contract; do not promise free forever |
| Public basemap availability changes | Keep it non-authoritative and replaceable; assessment and search must degrade independently |
| Scientific method cannot support the intended visual claim | Let Phase 0 evidence change the method or block publication; visual ambition does not override validation |

## Positioning statement

For people who want to explore what scenario-based sea-level data means for a
European place, SeaRise Europe offers a clear, scientifically cautious result
with inspectable sources and limitations. It prebuilds and verifies the
geospatial data product, then delivers it through a fast, portable,
offline-capable browser experience without a request-time application backend.

## Review checklist

Before using this document in public copy:

- [ ] Re-open each referenced product and record the review date.
- [ ] Verify current geographic coverage, methodology, pricing, and licence
  claims from provider-owned sources.
- [ ] Remove “only,” “best,” or superiority language not supported by evidence.
- [ ] Compare equivalent capabilities rather than a research tool's scientific
  depth with a consumer tool's interaction speed.
- [ ] Re-check whether SeaRise Europe's claimed capabilities are implemented
  and measured, not merely accepted in ADR-021.
