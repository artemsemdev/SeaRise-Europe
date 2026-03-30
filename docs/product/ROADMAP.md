# SeaRise Europe — Product Roadmap

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

> **Note:** This roadmap reflects product thinking and prioritization logic, not committed delivery dates. All timelines are TBD until blocking open questions (OQ-02 through OQ-06 in the PRD) are resolved and infrastructure decisions are finalized.

---

## Roadmap Philosophy

This product follows a **depth-first** roadmap strategy. Each phase must be complete and polished before the next expands scope. Adding a capability before the current one is reliable and trustworthy is a quality and trust risk — not a progress indicator.

**Phase gate criteria:** A phase is complete when all its acceptance criteria pass, all performance NFRs are met in a production-like environment, and the application can be demonstrated reliably to an external reviewer without preparation or manual intervention.

---

## Phase Overview

| Phase | Theme | Status | Goal |
|---|---|---|---|
| Phase 0 | Foundation & Data Pipeline | Not started | Data sourcing, processing pipeline, and deployment scaffolding are in place |
| Phase 1 | MVP — Core Exposure Explorer | Not started | Fully functional, publicly deployable MVP matching PRD v0.1 scope |
| Phase 2 | Quality & Depth | Not started | Improve result quality, UX polish, and observability for ongoing portfolio use |
| Phase 3 | Expansion | Backlog | Extend hazard types, geographic coverage, or user features based on validated need |

---

## Phase 0 — Foundation & Data Pipeline

### Goal

Establish the data processing pipeline, hosting infrastructure, and deployment tooling before any user-facing feature work begins. Phase 0 is not user-visible — it produces the platform that Phase 1 is built on.

### Scope

**Data**
- [ ] Source and license-validate IPCC AR6 sea-level projection data (NASA AR6 tool or equivalent).
- [ ] Source Copernicus DEM tiles for the Europe extent.
- [ ] Define and document the coastal analysis zone boundary.
- [ ] Define and document the exposure methodology: how projection data and elevation data are combined to produce a result state.
- [ ] Produce and validate initial map layers for at least the three MVP time horizons (2030, 2050, 2100) and the selected scenario set.
- [ ] Establish a reproducible layer-generation workflow (documented, version-controlled, re-runnable).

**Infrastructure**
- [ ] Set up Azure infrastructure: Container Apps, Blob Storage, PostgreSQL, Container Registry.
- [ ] Configure TiTiler (or equivalent) for dynamic tile serving from cloud-optimized geospatial assets.
- [ ] Set up CI/CD pipeline with build, test, and deployment stages.
- [ ] Configure environment separation (development, staging, production-like demo).

**Resolving Blocking Open Questions**
- [ ] Confirm product name (OQ-01).
- [ ] Confirm MVP scenario set (OQ-02).
- [ ] Confirm default scenario and default time horizon (OQ-03).
- [ ] Confirm coastal analysis zone definition (OQ-04).
- [ ] Confirm exposure methodology and boundary behavior (OQ-05).
- [ ] Select geocoding provider strategy (OQ-06).
- [ ] Select base map and tile provider (OQ-07).

### Phase 0 Exit Criteria

- All blocking open questions (OQ-02 through OQ-06) are resolved and documented.
- At least one complete map layer (one scenario, one horizon) is served from cloud infrastructure and renderable in a browser.
- Layer-generation workflow is documented and reproducible.
- CI/CD pipeline is operational.

---

## Phase 1 — MVP: Core Exposure Explorer

### Goal

Ship a publicly accessible, portfolio-ready exposure explorer that fully implements PRD v0.1. Every requirement in the PRD must pass its acceptance criteria. The product must be demonstrable to an external reviewer without preparation.

### Feature Areas

#### Search and Location Selection
- Free-text European address search.
- Up to 5 ranked geocoding candidates.
- Map-based candidate selection and marker placement.
- Manual map refinement by clicking/tapping.
- Europe geography validation (Unsupported Geography state).
- Coastal zone validation (Out of Scope state).

#### Scenario and Time Horizon Controls
- Scenario selector (configured MVP scenario set).
- Time horizon selector: 2030, 2050, 2100.
- Configured default scenario and default time horizon.
- Live refresh of map and result when controls change.

#### Assessment and Results
- Five result states: Modeled Coastal Exposure Detected, No Modeled Coastal Exposure Detected, Data Unavailable, Out of Scope, Unsupported Geography.
- Plain-language result summary with location, scenario, horizon, and state.
- Map overlay for Modeled Coastal Exposure Detected state.
- Legend synchronized to active layer.
- Stale-response handling for rapid control changes.

#### Transparency and Methodology
- "How to interpret this result" entry point.
- Methodology/details panel with source names, methodology version, interpretation guidance, and key limitations.
- Data source and map provider attribution.
- Methodology version visible in UI and assessment response.
- Required disclaimer (not engineering/legal/insurance determination).

#### Empty, Loading, and Error States
- Meaningful initial empty state.
- Loading states for geocoding and assessment.
- No-results state with guidance.
- Retry action for recoverable errors.
- Reset action returning to initial state.

#### Accessibility and Responsive Layout
- Core flows keyboard-operable.
- WCAG 2.2 AA criteria met for contrast, labeling, and non-color-dependent communication.
- Desktop primary; tablet and mobile functional.

### Phase 1 Exit Criteria

- All 28 acceptance criteria (AC-001 through AC-028) pass.
- All NFRs (NFR-001 through NFR-023) verified in a production-like environment.
- All 10 success metrics validated (see Metrics Plan).
- Demo script passes for ≥3 coastal and ≥3 inland European locations.
- Attribution and disclaimer reviewed and approved.
- No unhandled error states observable under normal and edge-case operation.

---

## Phase 2 — Quality and Depth

### Goal

Improve result depth, observability, and UX quality based on feedback from Phase 1 portfolio use. No new scope categories are added in Phase 2 — the theme is doing existing things better.

### Candidate Features

Items in this phase are candidates, not commitments. Priority order should be set after Phase 1 is live and feedback is gathered.

**Result quality**
- Expand scenario set beyond MVP minimum if additional scenarios improve decision value.
- Improve coastal analysis zone boundaries based on observed edge cases.
- Add contextual result layer showing the elevation of the selected point relative to the exposure threshold.
- Document and expose confidence/uncertainty bands where projection data supports it.

**UX and information design**
- Shareable/deep-link URLs for a specific location, scenario, and horizon combination.
- Improved result panel layout based on usability test findings.
- Timeline slider or animation between horizons (2030 → 2050 → 2100) for visual continuity.
- Improved empty and no-results state copy based on observed search patterns.

**Observability and operations**
- Analytics integration (pending OQ-10 resolution and privacy model decision).
- Performance monitoring dashboard connected to NFR targets.
- Automated layer-generation pipeline replacing the manual Phase 0 workflow.
- Dataset freshness indicator in the UI (when was this layer last updated).

**Methodology page**
- Standalone public methodology page with full technical appendix.
- Downloadable methodology version document for citation purposes.

### Phase 2 Exit Criteria

Each candidate feature has its own acceptance criteria, defined at the time it is committed.

---

## Phase 3 — Expansion

### Goal

Extend the product into adjacent problem spaces if Phase 1 and Phase 2 demonstrate sustained portfolio value and user interest.

### Candidate Directions

These are strategic options, not prioritized plans. Each requires its own scoping, feasibility assessment, and PRD amendment before implementation.

| Direction | Description | Dependency |
|---|---|---|
| Additional coastal hazard layers | Storm surge frequency, tidal range, coastal flood return periods | Additional data sourcing and methodology work |
| Inland climate risk modes | River flooding, heat stress, wildfire risk as separate scoped modules | Significant new data pipeline and methodology scope |
| Country-specific overlays | Coastal adaptation infrastructure, protected zone boundaries, flood defense assets | Country-level data sourcing |
| 3D visualization mode | Terrain-aware rendering of exposure at a location | Significant frontend engineering scope |
| Expanded geographic coverage | Non-European coastlines using comparable authoritative data | Global data availability assessment |
| User accounts and saved searches | Save, name, and revisit locations across sessions | Backend identity and storage scope |
| Multilingual UI | European language localization (at minimum: French, German, Spanish, Portuguese, Dutch) | UI copy externalization (NFR-018) required first |

---

## Prioritization Principles

When ordering features within a phase or deciding whether something enters the roadmap, apply these criteria in order:

1. **Does it serve the primary user goal?** Features that help Marina (P-01) get a clearer, more trustworthy result take priority over features that improve aesthetics or add scope.
2. **Does it preserve scientific honesty?** Features that could increase false precision risk are deprioritized or rejected.
3. **Is it required for demo readiness?** Phase 1 features that would cause the demo to fail in a review session are P0.
4. **Does it reduce a blocking open question or known risk?** Resolving OQ-02 through OQ-06 unlocks implementation; they are always higher priority than feature work.
5. **Is the data and methodology ready?** No user-facing feature ships before its underlying data pipeline and methodology are validated and documented.

---

## What Is Not on This Roadmap

The following items are explicitly excluded from all phases of this roadmap unless a new PRD amendment is made:

- Real-time flood alerts or live weather integration.
- Insurance, mortgage, or financial risk scoring.
- Parcel-level precision claims.
- User-uploaded GIS data.
- Native mobile applications.
- Admin UI for dataset management.

---

## Demo Script (Phase 1 Readiness Reference)

The following scenarios must pass without manual intervention before Phase 1 is declared complete:

| # | Input | Expected State | Notes |
|---|---|---|---|
| D-01 | A known coastal location in the Netherlands | Modeled Coastal Exposure Detected (at least one scenario/horizon) | Validates core happy path |
| D-02 | A known coastal location in Portugal | Modeled Coastal Exposure Detected or No Exposure Detected | Validates southern Europe coverage |
| D-03 | A known coastal city in Italy | Modeled Coastal Exposure Detected or No Exposure Detected | Validates Mediterranean coverage |
| D-04 | An inland European city (e.g., Prague) | Out of Scope | Validates coastal zone gating |
| D-05 | An inland European location far from any coast | Out of Scope | Validates inland detection |
| D-06 | A non-European location (e.g., New York) | Unsupported Geography | Validates geography gating |
| D-07 | An ambiguous query returning multiple candidates | Up to 5 ranked candidates displayed | Validates multi-result handling |
| D-08 | An empty search submission | Inline validation, no request fired | Validates input validation |
| D-09 | Change scenario after initial result | Map and summary update, no new search required | Validates control-change flow |
| D-10 | Change time horizon after initial result | Map and summary update, no new search required | Validates horizon-change flow |
