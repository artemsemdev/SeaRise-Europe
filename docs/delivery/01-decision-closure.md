# Epic 01 — Decision Closure and Delivery Baseline

| Field            | Value                                              |
| ---------------- | -------------------------------------------------- |
| Epic ID          | E-01                                               |
| Phase            | 0 — Pre-Implementation                             |
| Status           | Not Started                                        |
| Effort           | ~4 days                                            |
| Dependencies     | None — this is the entry point for all other epics |
| Stories          | 7 (S01-01 through S01-07)                          |

---

## 1  Objective

Resolve all blocking open questions and produce a documented decision baseline that unblocks all downstream implementation epics.

The current recommended starting point for that baseline is [17-open-question-closure-proposal.md](../architecture/17-open-question-closure-proposal.md). This epic still owns converting that proposal into approved ADRs, seed data, and final committed decisions.

---

## 2  Why This Epic Exists

Six open questions (OQ-02 through OQ-07) block schema design, pipeline logic, API contracts, and frontend controls. Without resolving these first, every downstream epic risks mid-stream rework. This epic forces all decisions to be made, documented, and committed before implementation begins. It is the cheapest point in the project to change direction, and the most expensive set of decisions to defer.

---

## 3  Scope

### 3.1 In Scope

- Resolution and documentation of OQ-02 through OQ-07.
- Methodology specification (binary vs. continuous, threshold, interpretation rules).
- Seed data specification (scenarios, horizons, methodology version, geography boundaries).
- Decision log entries or Architecture Decision Records (ADRs) for every resolved question.
- Coastal zone geometry sourcing and validation.
- Draft methodology panel text ("what it does" / "what it does not account for").

### 3.2 Out of Scope

- Any implementation code (backend, frontend, pipeline).
- Infrastructure provisioning (database, blob storage, hosting).
- Pipeline execution or data processing.
- UI implementation.
- Pre-launch open questions (OQ-08 through OQ-12).

---

## 4  Blocking Open Questions

This epic exists specifically to close the following questions. Each is mapped to one or more user stories below.

| OQ   | Question                                    | Story   |
| ---- | ------------------------------------------- | ------- |
| OQ-02 | MVP scenario set (exact IDs, display names, descriptions). Illustrative candidates: `ssp1-26`, `ssp2-45`, `ssp5-85`. Must confirm exact values. | S01-01 |
| OQ-03 | Default scenario and default time horizon. Must select one scenario and one horizon as defaults. | S01-02 |
| OQ-04 | Coastal analysis zone definition. Must select source geometry (Natural Earth coastline buffer, EEA coastal zone shapefile, or custom). Must document source. | S01-03 |
| OQ-05 | Exposure methodology — binary (0/1) vs. continuous threshold. Current assumption is binary. | S01-04 |
| OQ-06 | Production geocoding provider. Candidates: Pelias, Mapbox, HERE, Azure Maps, Photon. Nominatim is dev-only. | S01-05 |
| OQ-07 | Basemap tile provider. Candidates: Mapbox, MapTiler, Stadia Maps, OpenFreeMap. | S01-06 |

---

## 5  Traceability

### 5.1 Product Requirement Traceability

| Requirement | Description                                           |
| ----------- | ----------------------------------------------------- |
| FR-014      | Scenario selection control                            |
| FR-015      | Time horizon selection control                        |
| FR-016      | Default scenario and horizon on initial load          |
| BR-003      | Geography — Europe-only scope                         |
| BR-004      | Coastal zone boundary definition                      |
| BR-005      | Sensible defaults for scenario and horizon            |
| BR-010      | Scenario set contents                                 |
| BR-011      | Result state definitions (exposed / not exposed / N/A)|
| NFR-021     | Methodology versioning                                |
| NFR-022     | Reproducibility of exposure results                   |

### 5.2 Architecture Traceability

| Architecture Document                                      | Relevance                          |
| ---------------------------------------------------------- | ---------------------------------- |
| `docs/architecture/11-architecture-decisions.md`           | ADR records for each decision      |
| `docs/architecture/12-risks-assumptions-and-open-questions.md` | Blocking question definitions  |
| `docs/architecture/17-open-question-closure-proposal.md`   | Proposed closure set and rationale |
| `docs/architecture/05-data-architecture.md`                | Schema seed values                 |
| `docs/architecture/16-geospatial-data-pipeline.md`         | Methodology definition             |
| `docs/architecture/13-domain-model.md`                     | Entity definitions                 |
| `docs/architecture/06-api-and-contracts.md`                | API contracts affected by defaults |
| `docs/architecture/03-component-view.md`                   | Component contracts                |
| `docs/architecture/03a-frontend-architecture.md`           | Frontend map surface               |
| `docs/architecture/07-security-architecture.md`            | API key management                 |
| `docs/architecture/14-integration-patterns.md`             | Geocoding integration patterns     |

---

## 6  Implementation Plan

Work through stories in the following recommended order, chosen to maximize downstream unblocking:

1. **S01-04 — Confirm Exposure Methodology.** Has the broadest downstream impact on pipeline logic, domain model, and result interpretation.
2. **S01-01 — Confirm MVP Scenario Set.** Defines the core dimension that flows into schema, blob paths, and API contracts.
3. **S01-02 — Confirm Default Scenario and Time Horizon.** Depends on S01-01 output.
4. **S01-03 — Define Coastal Analysis Zone Geometry.** Independent research task; can be parallelized with S01-01/S01-02 if time allows.
5. **S01-05 — Select Production Geocoding Provider.** Independent infrastructure decision.
6. **S01-06 — Select Basemap Tile Provider.** Independent infrastructure decision.
7. **S01-07 — Produce Seed Data Specification.** Consolidates all prior decisions into a single implementation-ready artifact. Must be last.

### Execution Order Map

```
S01-04 (Exposure Methodology)     S01-03 (Coastal Zone Geometry)
  │                                  │
  └──► S01-01 (Scenario Set)         │  ◄── parallel track, independent research
         │                           │
         └──► S01-02 (Defaults)      │
                │                    │
                │   S01-05 (Geocoding Provider)  ◄── independent, any time after S01-04
                │     │
                │   S01-06 (Basemap Provider)    ◄── independent, any time after S01-04
                │     │
                └─────┴──────────────┘
                         │
                         ▼
                S01-07 (Seed Data Spec)  ◄── MUST BE LAST: consolidates all decisions
```

**Rationale:** S01-04 (methodology) runs first because it has the broadest downstream impact. S01-03 (coastal zone) is independent research and can run on a parallel track. S01-05 and S01-06 are independent provider decisions that can happen any time. S01-07 must be last because it consolidates outputs from S01-01 through S01-04 into a single implementation-ready artifact.

---

## 7  User Stories

---

### S01-01 — Confirm MVP Scenario Set

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S01-01                 |
| Type           | Technical Enabler      |
| Effort         | ~0.5 days              |
| Dependencies   | None                   |

**Statement**

As the engineer maintaining delivery quality, I want the MVP scenario set confirmed with exact IDs, display names, and descriptions, so that schema seed data, COG blob paths, and API contracts can be finalized without risk of rework.

**Why**

The scenario set is the primary dimension in the data model. Scenario IDs appear in database rows, blob storage paths, API response payloads, and frontend dropdown controls. Changing them after implementation has begun triggers rework across every layer of the stack. Confirming them now eliminates that risk.

**Scope Notes**

- Confirm exact string IDs (e.g., `ssp1-26`, `ssp2-45`, `ssp5-85`).
- Write human-readable display names (e.g., "SSP1-2.6 — Sustainability").
- Write brief descriptions suitable for a tooltip or info panel.
- Define sort order for UI display.
- At least 2 and at most 5 scenarios.

**Traceability**

- Open Questions: OQ-02
- Requirements: FR-014, BR-010
- Architecture: `docs/architecture/05-data-architecture.md`, `docs/architecture/06-api-and-contracts.md`

**Implementation Notes**

- Review IPCC AR6 WG1 Chapter 9 (Ocean, Cryosphere, and Sea Level Change) for authoritative scenario naming.
- Cross-check display names and descriptions against `CONTENT_GUIDELINES` scientific language rules.
- Record the decision as an ADR entry or decision log entry in the repository.

**Acceptance Criteria**

1. Scenario IDs, display names, descriptions, and sort order are documented in a decision record.
2. Display names and descriptions comply with `CONTENT_GUIDELINES` scientific language rules.
3. At least 2 and at most 5 scenarios are selected.
4. Decision is recorded as an ADR or decision log entry and committed to the repository.

**Definition of Done**

- Decision record committed to repository.
- Values reviewed for scientific accuracy and language guideline compliance.

**Testing Approach**

- Document review.

**Evidence Required**

- Decision log entry containing the scenario table (ID, display name, description, sort order).

---

### S01-02 — Confirm Default Scenario and Time Horizon

| Field          | Value                          |
| -------------- | ------------------------------ |
| ID             | S01-02                         |
| Type           | Technical Enabler              |
| Effort         | ~0.5 days                      |
| Dependencies   | S01-01 (scenario set must exist to select a default) |

**Statement**

As the engineer maintaining delivery quality, I want the default scenario and default time horizon selected, so that the config API response and initial UI state can be implemented deterministically.

**Why**

The application must render a meaningful initial state on first load without requiring user interaction. The config API endpoint returns defaults that the frontend uses to populate controls and trigger the first exposure query. Without confirmed defaults, the frontend team (or future self) must guess, and the config API contract cannot be finalized.

**Scope Notes**

- Select exactly one scenario from the confirmed set (S01-01) as the default.
- Select exactly one time horizon from the set {2030, 2050, 2100} as the default.
- Document the rationale for each default selection.

**Traceability**

- Open Questions: OQ-03
- Requirements: FR-016, BR-005
- Architecture: `docs/architecture/05-data-architecture.md` (`is_default` fields), `docs/architecture/06-api-and-contracts.md` (defaults in config response)

**Implementation Notes**

- The default scenario should represent a "middle-of-the-road" projection to avoid alarming or dismissive first impressions.
- The default horizon should balance relevance (not too far) with visibility of impact (not too near).
- Record the decision as an ADR entry or decision log entry.

**Acceptance Criteria**

1. Exactly one scenario is marked as default.
2. Exactly one horizon (from 2030, 2050, 2100) is marked as default.
3. Rationale for each default selection is documented.
4. Decision is recorded and committed.

**Definition of Done**

- Decision record committed to repository.
- Default values are consistent with S01-01 scenario set.

**Testing Approach**

- Document review.

**Evidence Required**

- Decision log entry specifying the default scenario, default horizon, and rationale.

---

### S01-03 — Define Coastal Analysis Zone Geometry

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S01-03                 |
| Type           | Data                   |
| Effort         | ~1 day                 |
| Dependencies   | None                   |

**Statement**

As the system, I need the coastal analysis zone boundary defined and sourced, so that geography validation can distinguish coastal from inland European locations.

**Why**

The application must determine whether a queried location is within the coastal analysis zone (eligible for exposure assessment) or inland (returns a "not applicable" result). This boundary is a core data dependency for the `CoastalZoneValidator` component and the `geography_boundaries` table. Without it, the system cannot classify locations correctly.

**Scope Notes**

- Evaluate candidate source geometries:
  - Natural Earth 10m coastline buffered to N km.
  - EEA coastal zone shapefile.
  - Custom geometry derived from another authoritative source.
- Select one approach and document the source, license, and transformation method.
- Produce a GeoJSON (or Shapefile) artifact and commit it to version control.
- Validate the geometry against known coastal and inland reference points.

**Traceability**

- Open Questions: OQ-04
- Requirements: FR-011, FR-012, BR-004
- Architecture: `docs/architecture/05-data-architecture.md` (`geography_boundaries` table), `docs/architecture/03-component-view.md` (`CoastalZoneValidator`)

**Implementation Notes**

- Start with the simplest viable approach: Natural Earth 10m coastline with a buffer distance.
- Buffer distance will likely be in the range of 10–50 km; document the chosen value and rationale.
- Use QGIS, GDAL/OGR, or a Python script (GeoPandas/Shapely) to produce the geometry.
- Spot-check at minimum 10 coordinates (5 known-coastal, 5 known-inland).
- Mandatory test cases: Amsterdam (coastal), Prague (inland), Barcelona (coastal), Zurich (inland), Copenhagen (coastal).

**Acceptance Criteria**

1. Source geometry is identified with license and attribution noted.
2. The geometry correctly classifies Amsterdam as coastal and Prague as inland.
3. The geometry source, transformation method, and buffer distance (if applicable) are documented.
4. A GeoJSON or Shapefile is produced and committed to version control.
5. Spot-check results for 10+ coordinates are documented.

**Definition of Done**

- Geometry file committed to repository.
- Documentation of source, method, and validation results committed.
- All spot-check coordinates pass.

**Testing Approach**

- Data validation: spot-check 10+ coordinates (5 coastal, 5 inland) against the produced geometry.

**Evidence Required**

- GeoJSON file in the repository.
- Spot-check results table (coordinate, expected classification, actual classification, pass/fail).
- Documentation of source dataset, license, buffer distance, and transformation method.

---

### S01-04 — Confirm Exposure Methodology

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S01-04                 |
| Type           | Technical Enabler      |
| Effort         | ~0.5 days              |
| Dependencies   | None                   |

**Statement**

As the engineer maintaining delivery quality, I want the exposure methodology confirmed (binary vs. continuous, threshold definition, interpretation rules), so that the pipeline processing logic and `ExposureEvaluator` can be implemented correctly.

**Why**

The exposure methodology determines how raw sea-level rise projection data is translated into user-facing results. It affects the COG pixel value semantics, the `ExposureEvaluator` component logic, the `ResultState` domain model, and the methodology panel displayed to users. It must be locked before pipeline code is written.

**Scope Notes**

- Confirm binary (0/1) or continuous approach.
- If binary: document pixel value mapping (0 = no exposure, 1 = exposure, NoData = outside zone).
- If continuous: document threshold value, comparison logic, and units.
- Draft the methodology panel text: "what it does" and "what it does not account for."
- Document the methodology version identifier (e.g., `v1.0`).

**Traceability**

- Open Questions: OQ-05
- Requirements: BR-011, BR-012, NFR-021
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` (processing logic), `docs/architecture/03-component-view.md` (`ExposureEvaluator`), `docs/architecture/13-domain-model.md` (`ResultState`)

**Implementation Notes**

- The current assumption is binary. If binary is confirmed, the pipeline logic is simpler: compare DEM elevation against projected sea level, output 0 or 1.
- The methodology panel text is user-facing and must be clear, honest, and free of false precision. State what the model does not account for (storm surge, local subsidence, tidal variation, defense infrastructure).
- Record the decision as an ADR or decision log entry.

**Acceptance Criteria**

1. Binary vs. continuous approach is confirmed with rationale.
2. If binary: pixel value mapping (0 = no exposure, 1 = exposure, NoData = outside zone) is documented.
3. If continuous: threshold value, comparison logic, and units are documented.
4. The "what it does" and "what it does not account for" methodology panel text is drafted.
5. Methodology version identifier is assigned.
6. Decision is recorded.

**Definition of Done**

- Methodology specification committed.
- Draft methodology panel text committed.
- Decision record committed.

**Testing Approach**

- Document review.

**Evidence Required**

- Methodology specification document.
- Draft methodology panel text.
- Decision log entry.

---

### S01-05 — Select Production Geocoding Provider

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S01-05                 |
| Type           | Infrastructure         |
| Effort         | ~0.5 days              |
| Dependencies   | None                   |

**Statement**

As the engineer maintaining delivery quality, I want the production geocoding provider selected, so that the `GeocodingClient` implementation, API key procurement, and `displayContext` field mapping can proceed.

**Why**

The geocoding provider is a runtime external dependency. The `IGeocodingService` interface in the component architecture defines a contract, but the concrete implementation depends on the selected provider's response format, authentication model, rate limits, and pricing. Selecting the provider now allows the integration pattern and API key management approach to be finalized before backend implementation begins.

**Scope Notes**

- Evaluate candidates: Pelias (self-hosted), Mapbox Geocoding, HERE Geocoding, Azure Maps, Photon.
- Nominatim is acceptable for development only, not production (usage policy restrictions).
- Selection criteria: European address coverage quality, pricing at expected volume, response format richness, self-hostability, license terms.
- Map provider response format to the `GeocodingCandidate` model fields: `Rank`, `Label`, `Country`, `Latitude`, `Longitude`, `DisplayContext`.

**Traceability**

- Open Questions: OQ-06
- Requirements: FR-004, FR-005, BR-006, BR-007, BR-009
- Architecture: `docs/architecture/03-component-view.md` (`IGeocodingService`), `docs/architecture/14-integration-patterns.md` (geocoding integration), `docs/architecture/07-security-architecture.md` (API key management)

**Implementation Notes**

- Test at least 3 candidate providers with representative European queries (e.g., "Amsterdam", "Barcelona, Spain", "Thessaloniki").
- Document response latency, result quality, and field mapping for each tested provider.
- If a paid provider is selected, document the pricing tier and expected monthly cost at projected volume.
- Record the decision as an ADR.

**Acceptance Criteria**

1. Provider is selected with documented rationale (coverage, pricing, format, license).
2. API key is procured or procurement steps are documented.
3. Provider response format is mapped to the `GeocodingCandidate` model (`Rank`, `Label`, `Country`, `Latitude`, `Longitude`, `DisplayContext`).
4. Provider rate limits and pricing are documented.
5. Decision is recorded as an ADR.

**Definition of Done**

- ADR committed.
- Field mapping table committed.
- API key secured or procurement plan documented.

**Testing Approach**

- Document review.

**Evidence Required**

- ADR entry with rationale.
- Provider field mapping table.
- API key secured (or documented procurement plan with timeline).

---

### S01-06 — Select Basemap Tile Provider

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S01-06                 |
| Type           | Infrastructure         |
| Effort         | ~0.5 days              |
| Dependencies   | None                   |

**Statement**

As the engineer maintaining delivery quality, I want the basemap tile provider selected, so that the map style URL, attribution requirements, and key management approach can be finalized.

**Why**

The basemap is the visual foundation of the map interface. Provider selection determines the style URL format used by the `MapSurface` component, the attribution text required in the UI, and the key management approach (domain-restricted API key exposed to the browser vs. server-side proxy). These decisions affect frontend architecture, security architecture, and content layout.

**Scope Notes**

- Evaluate candidates: Mapbox, MapTiler, Stadia Maps, OpenFreeMap.
- Selection criteria: visual quality, European coverage detail, pricing, attribution requirements, key security model, vector tile support.
- Confirm the key management approach: domain-restricted browser key vs. server-side tile proxy.
- Document the exact style URL template.
- Document required attribution text and placement.

**Traceability**

- Open Questions: OQ-07
- Requirements: FR-026, FR-034
- Architecture: `docs/architecture/03a-frontend-architecture.md` (`MapSurface`), `docs/architecture/07-security-architecture.md` (basemap key), `docs/architecture/11-architecture-decisions.md`

**Implementation Notes**

- Load each candidate's default style in a test map viewer and assess European coverage quality (label density, terrain detail, coastline rendering).
- If Mapbox is selected, note that the GL JS license requires a Mapbox access token; alternatives like MapLibre GL JS with other providers avoid this coupling.
- Document whether the selected provider supports free-tier usage at expected portfolio traffic levels.
- Record the decision as an ADR.

**Acceptance Criteria**

1. Provider is selected with documented rationale (quality, pricing, attribution, key model).
2. Map style URL template is documented.
3. Attribution requirements (text and placement) are documented.
4. Key management approach (domain-restricted key vs. proxy) is confirmed.
5. Decision is recorded as an ADR.

**Definition of Done**

- ADR committed.
- Style URL template, attribution text, and key management approach documented.

**Testing Approach**

- Document review.

**Evidence Required**

- ADR entry with rationale.
- Style URL template.
- Attribution text.

---

### S01-07 — Produce Seed Data Specification

| Field          | Value                                         |
| -------------- | --------------------------------------------- |
| ID             | S01-07                                        |
| Type           | Technical Enabler                             |
| Effort         | ~0.5 days                                     |
| Dependencies   | S01-01, S01-02, S01-03, S01-04 (all decisions consolidated here) |

**Statement**

As the engineer maintaining delivery quality, I want a complete seed data specification produced, so that database seeding scripts can be written in Epic 02/03 without ambiguity.

**Why**

Multiple downstream epics (schema creation, pipeline configuration, API contract implementation) depend on exact seed values. Consolidating all decisions from S01-01 through S01-04 into a single, implementation-ready seed data specification eliminates interpretation gaps and ensures consistency across the stack.

**Scope Notes**

- Draft SQL `INSERT` statements (or equivalent structured format) for:
  - `scenarios` table: all confirmed scenarios with IDs, display names, descriptions, sort order, and `is_default` flag.
  - `horizons` table: 2030, 2050, 2100 with `is_default` flag.
  - `methodology_versions` table: v1.0 with methodology type, description, and all required metadata fields.
  - `geography_boundaries` table: `europe` and `coastal_analysis_zone` rows with geometry source references.
- All values must align with decisions from S01-01 through S01-04.

**Traceability**

- Open Questions: All OQ-02 through OQ-05 outputs
- Architecture: `docs/architecture/05-data-architecture.md` (all tables)

**Implementation Notes**

- Use the data architecture document as the schema reference.
- Cross-reference every value against the corresponding decision record.
- Include comments in the seed specification explaining the source decision for each value.
- The seed specification should be directly convertible to a migration script in Epic 02.

**Acceptance Criteria**

1. SQL `INSERT` statements (or equivalent) are drafted for `scenarios`, `horizons`, `methodology_versions`, and `geography_boundaries` tables.
2. All scenario values align with the S01-01 decision.
3. Default flags align with the S01-02 decision.
4. Methodology version fields align with the S01-04 decision.
5. Geography boundary rows reference the S01-03 geometry source.
6. All values are cross-referenced against their source decisions.

**Definition of Done**

- Seed data specification committed.
- Cross-reference review against all source decisions is complete with no inconsistencies.

**Testing Approach**

- Document review: cross-check every value against its source decision record.

**Evidence Required**

- Seed data specification document or SQL file.
- Cross-reference annotations linking each value to its decision source.

---

## 8  Technical Deliverables

| Deliverable                        | Format                    | Produced By |
| ---------------------------------- | ------------------------- | ----------- |
| ADR / decision log entries         | Markdown (committed)      | S01-01 through S01-06 |
| Coastal zone geometry              | GeoJSON (committed)       | S01-03      |
| Spot-check validation results      | Markdown table (committed)| S01-03      |
| Methodology specification          | Markdown (committed)      | S01-04      |
| Draft methodology panel text       | Markdown (committed)      | S01-04      |
| Geocoding provider field mapping   | Markdown table (committed)| S01-05      |
| Seed data specification            | SQL or Markdown (committed)| S01-07     |

---

## 9  Data, API, and Infrastructure Impact

No implementation changes are made in this epic. All deliverables are documentation and data artifacts that serve as specifications for downstream epics:

- **Epic 02 (Infrastructure and Schema)** consumes the seed data specification (S01-07) and coastal zone geometry (S01-03).
- **Epic 03 (Data Pipeline)** consumes the methodology specification (S01-04) and scenario set (S01-01).
- **Epic 04 (Backend API)** consumes the default selections (S01-02), geocoding provider mapping (S01-05), and scenario set (S01-01).
- **Epic 05 (Frontend)** consumes the basemap selection (S01-06), default selections (S01-02), and methodology panel text (S01-04).

---

## 10  Security and Privacy

- **Geocoding provider selection (S01-05):** The selected provider's authentication model determines whether API keys are stored server-side only or exposed to the browser. The decision must account for the API key management approach defined in the security architecture.
- **Basemap tile provider selection (S01-06):** Basemap keys are typically exposed to the browser. The decision must confirm whether a domain-restricted key is sufficient or whether a server-side tile proxy is required to avoid key leakage.
- No user data is processed or stored in this epic.

---

## 11  Observability

No runtime observability concerns in this epic. All deliverables are static documents and data files. Observability instrumentation will be defined in subsequent implementation epics.

---

## 12  Testing

| Story   | Testing Approach                                                        |
| ------- | ----------------------------------------------------------------------- |
| S01-01  | Document review                                                         |
| S01-02  | Document review                                                         |
| S01-03  | Data validation — spot-check 10+ coordinates against the geometry       |
| S01-04  | Document review                                                         |
| S01-05  | Document review                                                         |
| S01-06  | Document review                                                         |
| S01-07  | Document review — cross-check all values against source decisions       |

---

## 13  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| Decision paralysis on scenario set or methodology leads to time overrun | Medium | Medium | Time-box research to 0.5 days per question. Accept "good enough for MVP" and document the option to revisit. |
| Coastal zone geometry is complex to source and validate | Medium | Low | Start with the simplest viable approach (Natural Earth coastline buffer). Iterate on buffer distance if spot-checks fail. |
| Preferred geocoding provider has insufficient European coverage or prohibitive pricing | Medium | Low | Evaluate at least 3 candidates. Maintain a ranked fallback list. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| All data sources (NASA AR6 sea-level projections, Copernicus DEM) are accessible without institutional access barriers. | Epic 03 (Data Pipeline) is blocked until access is obtained. Escalate immediately if access is restricted. |
| A suitable geocoding provider with acceptable European coverage is available within portfolio budget. | May need to self-host Pelias, which increases infrastructure complexity in Epic 02. |
| The binary exposure methodology is sufficient for MVP. | If continuous is required, pipeline logic and domain model are more complex, affecting effort estimates for Epic 03. |

---

## 14  Epic Acceptance Criteria

1. All six blocking open questions (OQ-02 through OQ-07) have documented resolutions with rationale.
2. Scenario IDs are confirmed and compliant with `CONTENT_GUIDELINES` scientific language rules.
3. Default scenario and horizon are selected with documented rationale.
4. Coastal analysis zone geometry is sourced, documented, and validated against 10+ test coordinates.
5. Exposure methodology is specified (binary/continuous, threshold, interpretation).
6. Geocoding provider is selected with field mapping and API key procurement plan.
7. Basemap provider is selected with style URL, attribution, and key management approach.
8. Seed data specification is complete and cross-referenced against all decisions.
9. All decisions are recorded as ADRs or decision log entries.

---

## 15  Definition of Done

- All 7 user stories completed with evidence committed to the repository.
- All blocking open questions (OQ-02 through OQ-07) resolved and documented.
- Seed data specification reviewed for completeness and consistency against all source decisions.
- Coastal zone geometry validated against 10+ reference coordinates with all spot-checks passing.
- No unresolved blocker remains within this epic's scope.

---

## 16  Demo and Evidence Required

| Evidence                                              | Location (expected)                              |
| ----------------------------------------------------- | ------------------------------------------------ |
| Decision log / ADR entries for OQ-02 through OQ-07    | `docs/architecture/11-architecture-decisions.md`  |
| Coastal zone GeoJSON file                             | `data/geometry/coastal_analysis_zone.geojson`     |
| Coastal zone spot-check validation results            | Linked from S01-03 decision record                |
| Seed data specification (SQL or structured document)  | `docs/delivery/artifacts/seed-data-spec.sql`      |
| Methodology specification with draft panel text       | `docs/delivery/artifacts/methodology-spec.md`     |
| Geocoding provider field mapping table                | Included in S01-05 ADR entry                      |
| Basemap style URL and attribution text                | Included in S01-06 ADR entry                      |
