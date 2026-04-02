# Mock-to-Requirements Traceability Map

> **Status:** Active
> **Last updated:** 2026-04-02
> **Purpose:** Maps each clickable prototype screen to its corresponding PRD requirements (FR, BR, NFR), user flows, acceptance criteria, content guidelines sections, and delivery epic stories. The production application must visually match these mocks.

---

## Authority

The mock pages in `docs/product/Mock/pages/` are the **authoritative visual specification** for the production frontend. Where the mocks diverge from earlier text-based descriptions in the PRD or architecture docs, the mocks take precedence for visual design, layout, and user-facing copy. See [Simplified Language Decision](#simplified-language-decision) for copy reconciliation details.

---

## Screen Inventory

| # | File | Screen Name | UI State / Phase |
|---|------|------------|-----------------|
| 01 | `01-landing.html` | Landing | `idle` |
| 02 | `02-search-loading.html` | Search Loading | `geocoding` |
| 03 | `03-candidates.html` | Candidate Selection | `candidate_selection` |
| 04 | `04-no-results.html` | No Search Results | `no_geocoding_results` |
| 05 | `05-assessing.html` | Assessment Loading | `assessing` |
| 06 | `06-exposure.html` | Exposure Detected | `result` (ModeledExposureDetected) |
| 07 | `07-no-exposure.html` | No Exposure | `result` (NoModeledExposureDetected) |
| 08 | `08-data-unavailable.html` | Data Unavailable | `result` (DataUnavailable) |
| 09 | `09-inland.html` | Inland / Out of Scope | `result` (OutOfScope) |
| 10 | `10-unsupported.html` | Outside Europe | `result` (UnsupportedGeography) |
| 11 | `11-methodology.html` | Methodology Drawer | Overlay on any result |
| 12 | `12-error-geocoding.html` | Geocoding Error | `geocoding_error` |
| 13 | `13-error-assessment.html` | Assessment Error | `assessment_error` |
| 14 | `14-about.html` | About Data | Static info page |
| — | `index.html` | Prototype Index | Navigation hub (dev only) |

---

## Per-Screen Traceability

### 01 — Landing (`01-landing.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-001, FR-002, FR-003, FR-026, FR-036 |
| **Business Rules** | BR-001, BR-008, BR-017 |
| **NFRs** | NFR-001, NFR-008, NFR-010, NFR-015 |
| **User Flow** | PRD §9.1 step 1–3 |
| **Acceptance Criteria** | AC-001, AC-015, AC-023 |
| **Content Guidelines** | CG-§6 (empty state copy) |
| **Epic / Stories** | E-05: S05-01, S05-03, S05-04, S05-07 |
| **Key Visual Elements** | Hero overlay with gradient text, search input centered on map, Europe-focused dark basemap, footer with attribution |

### 02 — Search Loading (`02-search-loading.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-004, FR-037 |
| **Business Rules** | BR-016 |
| **NFRs** | NFR-002, NFR-010 |
| **User Flow** | PRD §9.1 step 4 |
| **Acceptance Criteria** | AC-016 |
| **Content Guidelines** | CG-§7 (loading state — "Searching for locations...") |
| **Epic / Stories** | E-05: S05-04, S05-07 |
| **Key Visual Elements** | Spinner centered on map, "Searching for locations..." label, map remains visible behind |

### 03 — Candidate Selection (`03-candidates.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-005, FR-006 |
| **Business Rules** | BR-006, BR-007, BR-009 |
| **NFRs** | NFR-010, NFR-015 |
| **User Flow** | PRD §9.1 step 4–5, §9.2 |
| **Acceptance Criteria** | AC-002, AC-003 |
| **Content Guidelines** | — |
| **Epic / Stories** | E-05: S05-05 |
| **Key Visual Elements** | Dropdown list over map, up to 5 candidates with location + country context, keyboard navigable |

### 04 — No Search Results (`04-no-results.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-038 |
| **Business Rules** | — |
| **NFRs** | NFR-010 |
| **User Flow** | PRD §9.6 |
| **Acceptance Criteria** | AC-017 |
| **Content Guidelines** | CG-§6 (no geocoding results copy) |
| **Epic / Stories** | E-05: S05-07 |
| **Key Visual Elements** | Center card with "No locations found" heading, guidance to try different query, retry action |

### 05 — Assessment Loading (`05-assessing.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-013, FR-037 |
| **Business Rules** | — |
| **NFRs** | NFR-003, NFR-010 |
| **User Flow** | PRD §9.1 step 6–7 |
| **Acceptance Criteria** | AC-016, AC-028 |
| **Content Guidelines** | CG-§7 (loading state — "Calculating exposure for [Location]...") |
| **Epic / Stories** | E-06: S06-02, S06-05 |
| **Key Visual Elements** | Map zoomed to location with marker, spinner + "Calculating..." card, map pan/zoom remains interactive |

### 06 — Exposure Detected (`06-exposure.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-007, FR-008, FR-014, FR-015, FR-017, FR-018, FR-019, FR-020, FR-021, FR-024, FR-025, FR-028, FR-029, FR-030, FR-031, FR-032, FR-034, FR-041 |
| **Business Rules** | BR-010, BR-011, BR-015 |
| **NFRs** | NFR-004, NFR-010, NFR-015, NFR-016, NFR-021 |
| **User Flow** | PRD §9.1 steps 8–12, §9.3 |
| **Acceptance Criteria** | AC-004, AC-007, AC-008, AC-009, AC-010, AC-013, AC-014, AC-022, AC-024, AC-025, AC-026, AC-027, AC-020 |
| **Content Guidelines** | CG-§3.1 (Modeled Coastal Exposure Detected), CG-§4 (disclaimer) |
| **Epic / Stories** | E-06: S06-01, S06-02, S06-03, S06-04, S06-05, S06-06 |
| **Key Visual Elements** | Sidebar with timeline selector + forecast model list, map with exposure polygon overlay + warn marker, floating result card with "Risk detected" badge, big number (+0.85 m), confidence range row, source attribution, disclaimer, "How is this calculated?" link |

### 07 — No Exposure (`07-no-exposure.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-019, FR-020, FR-022, FR-024, FR-028, FR-029, FR-030 |
| **Business Rules** | BR-010, BR-012, BR-015 |
| **NFRs** | NFR-010, NFR-015, NFR-016 |
| **User Flow** | PRD §9.1 (variant: no exposure result) |
| **Acceptance Criteria** | AC-009, AC-011, AC-013 |
| **Content Guidelines** | CG-§3.2 (No Modeled Coastal Exposure Detected), CG-§2.5 (never describe as safe) |
| **Epic / Stories** | E-06: S06-03 |
| **Key Visual Elements** | Green "No risk detected" badge, +0.12 m value in green, sidebar with timeline at +50yr and Copernicus model active, explicit "does not mean it is safe" caveat, no exposure overlay on map |

### 08 — Data Unavailable (`08-data-unavailable.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-019, FR-023 |
| **Business Rules** | BR-010, BR-013, BR-014 |
| **NFRs** | NFR-010 |
| **User Flow** | PRD §9.7 |
| **Acceptance Criteria** | AC-012 |
| **Content Guidelines** | CG-§3.3 (Data Unavailable), CG-§2.6 (distinguish from No Exposure) |
| **Epic / Stories** | E-06: S06-03 |
| **Key Visual Elements** | Blue "Data not available" badge, guidance to try different model or timeframe, "Try +50 yr" / "Try IPCC model" action buttons, no exposure overlay |

### 09 — Inland / Out of Scope (`09-inland.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-011, FR-012, FR-019 |
| **Business Rules** | BR-004, BR-010 |
| **NFRs** | NFR-010 |
| **User Flow** | PRD §9.4 |
| **Acceptance Criteria** | AC-006 |
| **Content Guidelines** | CG-§3.4 (Out of Scope) |
| **Epic / Stories** | E-06: S06-03 |
| **Key Visual Elements** | Center card with "This location is too far from the coast" message, "New search" action button, map with marker but no overlay |

### 10 — Outside Europe (`10-unsupported.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-009, FR-010, FR-019 |
| **Business Rules** | BR-003, BR-010 |
| **NFRs** | NFR-010 |
| **User Flow** | PRD §9.5 |
| **Acceptance Criteria** | AC-005 |
| **Content Guidelines** | CG-§3.5 (Unsupported Geography) |
| **Epic / Stories** | E-06: S06-03 |
| **Key Visual Elements** | Center card with "This location is outside Europe" message, "New search" action button, map zoomed to non-European location |

### 11 — Methodology Drawer (`11-methodology.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-032, FR-033, FR-034, FR-035 |
| **Business Rules** | BR-015 |
| **NFRs** | NFR-015, NFR-021 |
| **User Flow** | PRD §9.1 step 8 (methodology entry point) |
| **Acceptance Criteria** | AC-013 |
| **Content Guidelines** | CG-§5 (methodology panel content) |
| **Epic / Stories** | E-07: S07-01 |
| **Key Visual Elements** | Right-side drawer overlay with dimmed background, "How is this calculated?" heading, data sources section, three forecast model cards, "What this does NOT include" list, educational disclaimer warning box, methodology version, close button |

### 12 — Geocoding Error (`12-error-geocoding.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-039 |
| **Business Rules** | — |
| **NFRs** | NFR-010 |
| **User Flow** | PRD §9.8 |
| **Acceptance Criteria** | AC-018 |
| **Content Guidelines** | CG-§8 (error state — geocoding failure) |
| **Epic / Stories** | E-05: S05-07 |
| **Key Visual Elements** | Center card with error icon, "Something went wrong" heading, retry and clear actions, map still visible behind |

### 13 — Assessment Error (`13-error-assessment.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-039 |
| **Business Rules** | — |
| **NFRs** | NFR-010 |
| **User Flow** | PRD §9.8 |
| **Acceptance Criteria** | AC-018 |
| **Content Guidelines** | CG-§8 (error state — assessment failure) |
| **Epic / Stories** | E-06: S06-05 |
| **Key Visual Elements** | Sidebar with controls visible, error card on map area with retry action, map zoomed to location with marker |

### 14 — About Data (`14-about.html`)

| Dimension | References |
|-----------|-----------|
| **Requirements** | FR-033, FR-034 |
| **Business Rules** | BR-015 |
| **NFRs** | NFR-021 |
| **User Flow** | — (standalone info page, linked from footer) |
| **Acceptance Criteria** | AC-013, AC-014 |
| **Content Guidelines** | CG-§5 (methodology content, extended) |
| **Epic / Stories** | E-07: S07-01 |
| **Key Visual Elements** | Full-page content layout with methodology explanation, data source details, three model explanations, limitations list, disclaimer |

---

## Simplified Language Decision

The mocks intentionally use simplified, user-friendly language that differs from the formal PRD terminology. This is a deliberate design decision to maximize comprehensibility for non-specialist users (PRD §4 Goal 3, CONTENT_GUIDELINES §1 Voice: "Clear").

### Scenario Labels

| PRD / API Internal | Mock User-Facing Label | Rationale |
|---|---|---|
| SSP1-1.9 (or configured optimistic scenario) | **NASA (optimistic)** | Named after recognizable institution; emotion-neutral qualifier |
| SSP2-4.5 (or configured moderate scenario) | **Copernicus (moderate)** | Named after EU program; signals middle ground |
| SSP5-8.5 (or configured worst-case scenario) | **IPCC (worst case)** | Named after authoritative body; honest worst-case framing |

### Time Horizon Labels

| PRD Specification | Mock User-Facing Label | Absolute Year |
|---|---|---|
| 2030 → 2036 | **+10 yr** | 2036 |
| 2040 → 2046 | **+20 yr** | 2046 |
| 2050 → 2056 | **+30 yr** | 2056 |
| 2070 → 2076 | **+50 yr** | 2076 |
| 2100 → 2126 | **+100 yr** | 2126 |

> **Note:** The PRD specifies 3 horizons (2030, 2050, 2100). The mocks expand this to 5 horizons (+10, +20, +30, +50, +100 yr) for a richer user experience. This is a product decision that supersedes PRD FR-015 and updates the MVP horizon set. FR-015 should be updated accordingly.

### Result State Headlines

| CONTENT_GUIDELINES Formal Headline | Mock Simplified Version |
|---|---|
| Modeled Coastal Exposure Detected | **Risk detected** |
| No Modeled Coastal Exposure Detected | **No risk detected** |
| Data Unavailable | **Data not available** |
| Outside MVP Coverage Area | **This location is too far from the coast** |
| Location Outside Supported Area | **This location is outside Europe** |

### Sidebar Label

| CONTENT_GUIDELINES Term | Mock Simplified Version |
|---|---|
| "Time horizon" | **How far into the future?** |
| "Scenario" | **Forecast model** |

### Reconciliation Rule

The production application **must use the simplified mock language** for all user-facing surfaces. The formal CONTENT_GUIDELINES terminology remains the canonical internal/API vocabulary. The `lib/i18n/en.ts` string file should map formal API result states to simplified display strings as shown above.

---

## Design System Reference

All mocks use `design-system.css` which implements the "Precision Observatory" design system from `docs/product/Mock/DESIGN.md`:

- **Color palette:** Dark surface (`#0f1418`), primary blue (`#9dcaff`), amber warn (`#ffba38`), green ok (`#7dd99b`)
- **Typography:** Manrope (display/headings) + Inter (body)
- **Map:** Leaflet.js + CartoDB Dark Matter tiles
- **Layout:** Sidebar (280px) + map area with floating result card
- **Timeline selector:** Flexbox-based horizontal track with gradient fill, dot indicators, and year labels

---

## Coverage Matrix

### PRD User Flows → Mock Screens

| User Flow (PRD §9) | Mock Screen(s) |
|---|---|
| §9.1 Happy Path | 01 → 02 → 03 → 05 → 06 |
| §9.2 Ambiguous Address | 01 → 02 → 03 (multiple candidates) |
| §9.3 Manual Map Refinement | 06 (map click re-assessment) |
| §9.4 Inland / Out of Scope | 09 |
| §9.5 Outside Europe | 10 |
| §9.6 No Geocoding Result | 04 |
| §9.7 Data Unavailable | 08 |
| §9.8 Recoverable Error | 12 (geocoding), 13 (assessment) |
| §9.9 Rapid Control Changes | 06 (stale request handling — behavioral, not visual) |

### Result States (BR-010) → Mock Screens

| Result State | Mock Screen |
|---|---|
| ModeledExposureDetected | 06-exposure.html |
| NoModeledExposureDetected | 07-no-exposure.html |
| DataUnavailable | 08-data-unavailable.html |
| OutOfScope | 09-inland.html |
| UnsupportedGeography | 10-unsupported.html |

### UI States (03a §5) → Mock Screens

| UI State | Mock Screen |
|---|---|
| Initial Empty | 01-landing.html |
| Geocoding Loading | 02-search-loading.html |
| No Results | 04-no-results.html |
| Candidate Selection | 03-candidates.html |
| Assessment Loading | 05-assessing.html |
| Modeled Exposure Detected | 06-exposure.html |
| No Modeled Exposure | 07-no-exposure.html |
| Data Unavailable | 08-data-unavailable.html |
| Out of Scope | 09-inland.html |
| Unsupported Geography | 10-unsupported.html |
| Recoverable Error (geocoding) | 12-error-geocoding.html |
| Recoverable Error (assessment) | 13-error-assessment.html |
| Methodology Panel | 11-methodology.html |
