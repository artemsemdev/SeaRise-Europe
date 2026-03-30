# SeaRise Europe — Product Vision & Strategy

## Document Metadata

| Field | Value |
|---|---|
| Owner | Artem Sem |
| Status | Draft |
| Version | 0.1 |
| Last updated | 2026-03-30 |

**Version History**

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 0.1 | 2026-03-30 | Artem Sem | Initial draft |

---

## 1. Vision Statement

> **Make coastal sea-level exposure understandable for anyone, anywhere in Europe — without overpromising what the science can say.**

SeaRise Europe closes the gap between authoritative climate science and the question every coastal resident eventually asks: *"What does this mean for where I live?"*

---

## 2. Problem We Are Solving

### The core tension

Climate change projections are increasingly precise at a regional scale, but the tools that expose them to the public fall into two failure modes:

| Failure Mode | Examples | Problem |
|---|---|---|
| **Too technical** | NASA AR6 projection tool, PROTECT, raw IPCC datasets | Valuable but built for scientists; require domain knowledge to interpret |
| **Too confident** | Many consumer flood maps and media visualizations | Visually compelling but imply parcel-level certainty the data cannot support |

Neither mode serves the growing population of non-specialist users — residents, renters, researchers, journalists — who want a *trustworthy*, *place-based*, *accessible* view of coastal exposure.

### Why Europe, why now

- The EEA documents that extreme sea levels have increased at many European coastline locations and that small mean sea-level rises can substantially amplify the frequency of historically rare flood events.
- Europe has strong authoritative data coverage (Copernicus DEM, IPCC AR6, PROTECT) but no single consumer-grade explorer that combines projection scenarios with elevation data for a specific address.
- European coastal populations are dense and diverse — from Amsterdam to Naples to Lisbon — yet most tools treat the continent as context rather than focus.

---

## 3. Strategic Pillars

### Pillar 1 — Scientific Honesty
Every result is scenario-based, model-based, and bounded by clearly stated limitations. The product never implies certainty the underlying data does not support. Disclaimer language, methodology versioning, and explicit result-state taxonomy enforce this at every layer.

### Pillar 2 — Place-Based Clarity
The primary UX pattern is simple: enter a place, get a result for that place. The product does not ask users to understand IPCC terminology, GIS coordinates, or percentile bands before they can see a useful answer.

### Pillar 3 — Data Transparency
Users can always trace any result back to its source dataset, methodology version, and key limitations. Transparency is not an afterthought or a footer link — it is a first-class feature.

### Pillar 4 — Engineering Quality
The architecture, data pipeline, and frontend are built to professional standards. This directly serves the portfolio goal: demonstrating that strong product thinking and strong engineering can coexist.

### Pillar 5 — Minimal Scope, Maximum Depth
MVP covers one problem well rather than many problems poorly. Europe. Coastal. Sea-level exposure. Three time horizons. That constraint is a feature, not a limitation.

---

## 4. Target Market

### Primary audience (MVP)

**Climate-aware individuals evaluating European coastal locations.** This includes property researchers, renters, homeowners, and curious residents who want to understand coastal exposure for a specific place in a way that is honest about what is and is not known.

### Secondary audience (MVP)

**Educators, researchers, and journalists** who need a transparent, citable visualization tool to support communication about coastal risk.

**Portfolio reviewers and technical evaluators** who use the product to assess the creator's capability across product design, geospatial engineering, and data communication.

### Audience growth path (post-MVP)

As the product matures: climate-adjacent professionals (urban planners, NGO analysts, local government staff), and eventually a broader European public audience if the product achieves sufficient trust and distribution.

---

## 5. Product Positioning

| Dimension | SeaRise Europe |
|---|---|
| **What it is** | A scenario-based coastal sea-level exposure explorer for European locations |
| **Who it is for** | Non-specialist individuals who want a place-based, honest view of coastal risk |
| **What makes it different** | Scientific caution is a product feature, not a caveat; methodology is transparent and versioned; Europe-only focus produces depth over breadth |
| **What it is not** | An engineering assessment tool, an insurance product, a real-time flood alert, or a parcel-level guarantee |

---

## 6. Design Principles

These principles govern product and design decisions at every level. When a decision is unclear, return to these.

### 1. Honest over impressive
If a visualization could mislead, simplify it. If copy implies more certainty than the data supports, rewrite it. A trustworthy product is more valuable than a visually dramatic one.

### 2. Explain without overwhelming
The methodology is accessible to anyone who wants it, but the primary user flow does not require reading it. Surface complexity on demand, not by default.

### 3. Explicit states over silent behavior
Every meaningful system state — loading, empty, error, out-of-scope, data unavailable — is shown clearly. The product never silently substitutes a different result or fails without telling the user why.

### 4. Europe and coastlines as identity
The product does not aspire to be everything. Saying "we cover Europe coastal exposure" is a positioning statement, not a limitation.

### 5. Version everything the user sees
Methodology, result states, and source attributions are versioned. A user should be able to understand, retroactively, which methodology version produced a result they saw.

### 6. Defaults are decisions
Default scenario, default time horizon, and default map view are product decisions, not engineering defaults. They shape what most users see first and must be chosen deliberately.

---

## 7. Long-Term Vision

The MVP is a focused, high-quality starting point. The long-term direction — if the product proves valuable — is toward a broader European climate-risk explorer that can:

- Extend to additional coastal hazard layers (storm surge frequency, tidal range interaction).
- Add inland climate-risk modes (river flooding, heat stress) as separate, clearly scoped modules.
- Offer country-specific contextual overlays (coastal adaptation infrastructure, protected zones).
- Support shareable results and public methodology documentation for research use cases.
- Expand globally if authoritative data reaches comparable quality and licensing terms.

In every phase, the same principles apply: scientific honesty, transparent methodology, and a user experience built for non-specialists.

---

## 8. What This Product Is Not

This section is as important as the vision itself. Keeping these boundaries explicit prevents scope drift and user expectation errors.

- **Not an engineering assessment.** Results are not suitable for construction, infrastructure, or planning decisions.
- **Not an insurance or mortgage tool.** No result implies financial risk quantification or property valuation impact.
- **Not a real-time system.** Results are based on pre-processed model runs, not live sensor data or weather feeds.
- **Not a flood prediction service.** The product shows scenario-based modeled exposure, not probabilistic flood event forecasting.
- **Not a global product (MVP).** Coverage is Europe only.
- **Not a scientific research platform.** It communicates science; it does not replace peer-reviewed analysis.
