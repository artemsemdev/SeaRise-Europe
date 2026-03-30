# SeaRise Europe — Competitive & Landscape Analysis

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

> **Scope note:** This analysis covers the landscape of publicly available sea-level and coastal flood visualization tools that a target user might encounter. It is not an exhaustive academic survey. The goal is to identify the gap that SeaRise Europe fills and ensure the product's differentiation is deliberate.

---

## 1. Landscape Overview

The tools in this space fall into four broad categories:

| Category | Characteristics | Examples |
|---|---|---|
| **Scientific / Research Tools** | Built for climate scientists and researchers; technically authoritative; not designed for public-facing UX | NASA AR6 Sea Level Projection Tool, PROTECT |
| **Authoritative Institutional Tools** | Built by government or inter-governmental bodies; comprehensive coverage; complex interface | Climate-ADAPT, EEA indicators, Copernicus Climate Data Store |
| **Consumer Flood Maps** | Designed for a general public; visually immediate; often sacrifice scientific rigor for accessibility | Climate Central Surging Seas, Flood Map (floodmap.net), CoastalDEM-based visualizations |
| **Property / Financial Risk Tools** | Designed for real estate, insurance, or mortgage professionals; focused on financial impact quantification | First Street Foundation (US), Moody's RMS, SwissRe Climate tools |

SeaRise Europe occupies a position that does not currently exist cleanly in this landscape: **consumer-grade UX + scientific caution + Europe-focus + transparent methodology.**

---

## 2. Tool Profiles

### 2.1 NASA IPCC AR6 Sea Level Projection Tool

| Dimension | Assessment |
|---|---|
| **URL** | https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool |
| **Owner** | NASA Sea Level Change Team / IPCC AR6 |
| **Primary audience** | Climate researchers, policy analysts |
| **Coverage** | Global |
| **Data** | IPCC AR6 sea-level projections; highly authoritative |
| **Scenarios** | SSP1-1.9, SSP2-4.5, SSP3-7.0, SSP5-8.5 and others |
| **Time horizons** | 2050, 2100, and others; selectable |
| **Visualization** | Charts and tabular data; not a map-first explorer |
| **Methodology transparency** | Very high — full IPCC documentation available |
| **UX accessibility** | Low — requires understanding of SSP scenarios, probabilistic projections, and confidence intervals |
| **Mobile-friendly** | No |
| **Address search** | No — users select from pre-defined gauge stations or regions |

**Gap it leaves:** No free-text address search; no Europe-focused consumer experience; SSP terminology is opaque to non-specialists; no integrated elevation overlay; no plain-language result.

---

### 2.2 PROTECT Sea Level Projection Tool

| Dimension | Assessment |
|---|---|
| **Owner** | EU-funded PROTECT project / Horizon 2020 |
| **Primary audience** | Policy makers, researchers, coastal managers |
| **Coverage** | Global with European focus |
| **Data** | PROTECT multi-model sea-level projections |
| **Scenarios** | RCP/SSP-aligned |
| **Visualization** | Charts and time series; limited map integration |
| **Methodology transparency** | High |
| **UX accessibility** | Low — similar to AR6 tool in complexity |

**Gap it leaves:** No address-level UX; European focus is an orientation, not a consumer product; not designed for a non-specialist user completing a 2-minute task.

---

### 2.3 Climate-ADAPT (EEA)

| Dimension | Assessment |
|---|---|
| **URL** | https://climate-adapt.eea.europa.eu |
| **Owner** | European Environment Agency |
| **Primary audience** | EU policy makers, national adaptation planners, researchers |
| **Coverage** | Europe |
| **Data** | Aggregates many datasets including sea-level indicators |
| **Visualization** | Indicator dashboards, maps, and reports |
| **Methodology transparency** | High — EEA documentation |
| **UX accessibility** | Low — built for policy professionals; not a consumer tool |
| **Address search** | No |

**Gap it leaves:** No address-level search; not a direct exposure explorer; designed for institutional users preparing adaptation strategies, not individuals evaluating a location.

---

### 2.4 Climate Central — Surging Seas Risk Zone Map

| Dimension | Assessment |
|---|---|
| **URL** | https://ss2.climatecentral.org |
| **Owner** | Climate Central (US nonprofit) |
| **Primary audience** | General public, journalists, educators |
| **Coverage** | Global (with better coverage in US; European coverage varies) |
| **Data** | CoastalDEM elevation model + sea-level projections |
| **Scenarios** | 1.5°C, 2°C, 3°C, 4°C warming-based |
| **Visualization** | Map with flood zone overlay; street-level zoom |
| **Methodology transparency** | Partial — methodology page exists but is not in-product |
| **UX accessibility** | High — public-facing, address-searchable |
| **Mobile-friendly** | Yes |
| **European coverage quality** | Variable; CoastalDEM accuracy varies by country |

**Strengths:** Most accessible existing tool; address-level search; visually impactful.

**Weaknesses:** Global-first tool, not Europe-optimized; CoastalDEM has known accuracy issues in some European coastal areas; warming-degree scenarios are harder to interpret than time-horizon scenarios; methodology is documented externally, not surfaced in-product; European coverage and data freshness are not consistently communicated.

**Gap it leaves:** Europe-first data quality and sourcing; in-product methodology transparency; scenario framing aligned with IPCC AR6 European projections; explicit scientific caution in result copy.

---

### 2.5 FloodMap.net and Similar Elevation-Based Web Tools

| Dimension | Assessment |
|---|---|
| **Primary audience** | General public |
| **Coverage** | Global |
| **Data** | SRTM and similar public elevation datasets |
| **Methodology transparency** | Very low — no explanation of data source or methodology |
| **UX accessibility** | High — simple, fast |
| **Accuracy** | Low — SRTM has known biases, particularly over vegetation and buildings |
| **Scientific credibility** | Low |

**Gap it leaves:** These tools are often the first result a non-specialist finds. Their visual simplicity creates high perceived precision with very low actual accuracy. They represent the "false certainty" failure mode that SeaRise Europe explicitly avoids.

---

### 2.6 First Street Foundation — Flood Factor (US-only reference)

| Dimension | Assessment |
|---|---|
| **Owner** | First Street Foundation |
| **Coverage** | United States only |
| **Primary audience** | Homeowners, real estate professionals |
| **Data** | Proprietary flood model |
| **Visualization** | Property-level flood risk score + map |
| **Methodology transparency** | Moderate — public methodology report available |
| **UX accessibility** | High |

**Relevance to SeaRise Europe:** This is the closest example of a well-executed consumer-grade coastal/flood risk product. It demonstrates that scientific credibility and consumer UX are compatible. However, it is US-only, property-value-focused, and does not align with the scientific caution positioning SeaRise Europe requires. It represents a future state SeaRise Europe could grow toward — not a direct competitor for MVP.

---

## 3. Feature Comparison Matrix

| Feature | SeaRise Europe (MVP) | NASA AR6 | Surging Seas | FloodMap.net | First Street |
|---|---|---|---|---|---|
| Address-level search | Yes | No | Yes | Yes | Yes |
| Europe focus | Yes | Global | Global | Global | US only |
| Authoritative projection data | Yes (AR6/Copernicus) | Yes | Partial | No | Proprietary |
| Scenario selector | Yes | Yes | Yes (warming) | No | No |
| Time horizon selector | Yes | Yes | Partial | No | No |
| In-product methodology | Yes | External | External | None | External |
| Plain-language result summary | Yes | No | Partial | No | Yes |
| Scientific caution as UX feature | Yes | N/A (research tool) | Partial | No | Partial |
| Explicit limitation disclosure | Yes | Yes | Partial | No | Partial |
| Mobile responsive | Yes | No | Yes | Yes | Yes |
| Europe data quality | High (Copernicus DEM) | N/A | Variable | Low (SRTM) | N/A |

---

## 4. SeaRise Europe's Differentiation

Based on this landscape, SeaRise Europe holds a defensible and currently unoccupied position at the intersection of four attributes:

```
Scientific Caution × Consumer UX × Europe Depth × In-Product Transparency
```

No existing tool combines all four:
- Research tools have scientific rigor but not consumer UX.
- Consumer tools have UX but sacrifice rigor or transparency.
- Institutional tools have coverage but not address-level experience.
- US-market products like First Street have the right UX model but wrong geography and a different risk framing.

### Differentiation statements

1. **Europe-first data:** SeaRise Europe uses Copernicus DEM (recommended by EEA) rather than global SRTM-derived products with known accuracy gaps in European urban and coastal contexts.

2. **Scientific caution as a feature:** The product's result-state taxonomy, result copy rules, and in-product disclaimers are a product design decision, not an afterthought. This is the single strongest differentiator from most consumer tools.

3. **In-product methodology:** The methodology panel surfaces source names, version, assumptions, and limitations inside the product — not as an external PDF. This directly serves both P-01 (Marina wants to trust the result) and P-02 (Tobias needs to explain it in a classroom).

4. **Honest scope restriction:** The product's explicit MVP scope — Europe, coastal, sea-level only — is an integrity signal. Saying "we do not cover inland risk" is more trustworthy than a tool that implies it covers everything.

---

## 5. Risks from the Competitive Landscape

| Risk | Detail |
|---|---|
| Climate Central expands European data quality | If Surging Seas significantly improves European coverage and adds in-product methodology, it closes the main differentiation gap. Mitigation: SeaRise Europe's AR6/Copernicus combination and scientific caution positioning would still differentiate. |
| EEA or Copernicus launches a consumer tool | An authoritative European agency launching a consumer-grade explorer would be a direct competitive threat. Mitigation: Unlikely in the MVP timeframe; government tools typically move slowly into consumer UX. |
| Google or similar platform adds sea-level layers | A major platform adding projected flood zones would commoditize address-level search. Mitigation: Methodology transparency and scientific caution would remain differentiated; large platforms typically do not take strong scientific caution positions. |
| Data licensing changes | If IPCC AR6 or Copernicus licensing changes affect redistribution rights, the data pipeline could be disrupted. Mitigation: Monitor licensing terms; ensure attribution is compliant from the start (Dependency #1 in PRD). |

---

## 6. Positioning Statement

SeaRise Europe is the only European coastal sea-level exposure explorer that treats scientific honesty as a design constraint — not a disclaimer. For climate-aware individuals who want to understand what sea-level projections actually mean for a specific European address, SeaRise Europe provides a scenario-based, methodology-transparent result that is clear about what the data can and cannot say, backed by authoritative European datasets.
