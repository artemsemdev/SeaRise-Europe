# SeaRise Europe (Working Title) — PRD

## 1. Title and Document Metadata

| Field | Value |
|---|---|
| Product / feature name | **SeaRise Europe** *(working title; to be confirmed)* |
| Owner | **Artem** *(assumed portfolio owner)* |
| Status | Draft |
| Version | 0.1 |
| Last updated | 2026-03-30 |
| Platforms | Responsive web application |
| Short description | Europe-only, portfolio-first web application that lets a user enter a location and view scenario-based coastal sea-level exposure on an interactive map across selected future time horizons |

**Related links / references**

- NASA IPCC AR6 Sea Level Projection Tool and AR6 licensing.
- Climate-ADAPT metadata for the NASA AR6 tool and the PROTECT sea level projection tool. https://climate-adapt.eea.europa.eu/en/metadata/tools/sea-level-projection-tool
- Copernicus DEM product information and EEA note that EU-DEM is no longer maintained. https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM
- Copernicus Climate Data Store API and sea-level change indicator dataset. https://cds.climate.copernicus.eu/how-to-api
- EEA indicator on extreme sea levels and coastal flooding in Europe. https://www.eea.europa.eu/en/analysis/indicators/extreme-sea-levels-and-coastal-flooding
- Next.js, MapLibre GL JS, deck.gl, and ASP.NET Core official documentation. https://nextjs.org/docs/app/getting-started
- Azure Container Apps, Azure Blob Storage, Azure Database for PostgreSQL, and TiTiler references. https://learn.microsoft.com/en-us/azure/container-apps/
- Nominatim public usage policy. https://operations.osmfoundation.org/policies/nominatim/

---

## 2. Executive Summary

SeaRise Europe is a portfolio-first web application that helps a user enter a European location and view scenario-based coastal sea-level exposure on an interactive map at selected future time horizons. It is intended for people who want a place-based view of coastal risk rather than abstract climate charts, while also serving as a high-signal portfolio project that demonstrates modern .NET, Azure, frontend mapping, geospatial data handling, and solution architecture. The product aims to bridge the gap between authoritative but fragmented climate datasets and a clear, visually strong, scientifically cautious user experience. The intended outcome is a trustworthy explorer that makes coastal exposure easier to understand without overstating certainty or implying parcel-level guarantees.

---

## 3. Problem Statement

Climate change and sea-level rise are often communicated through regional reports, scientific tools, and technical datasets that are difficult for a non-specialist user to connect to a specific place. A person may reasonably ask, “What does this mean for this address?” but today the answer is often fragmented across projection tools, elevation datasets, coastal flood indicators, and narrative reports. That fragmentation creates two problems: ordinary users struggle to interpret the data, and many simplified visualizations on the internet overpromise certainty or hide methodology.

This matters because coastal exposure is not just an abstract climate concept. The EEA reports that extreme sea levels have increased at many European coastline locations and that even relatively small increases in sea level can substantially increase the frequency of historically rare coastal flood events. At the same time, authoritative tools such as the NASA AR6 Sea Level Projection Tool and the PROTECT tool are valuable but are not packaged as a focused, consumer-style, Europe-only address explorer.

If nothing changes, users will continue to rely on either highly technical sources that are hard to interpret or visually impressive maps that may imply more certainty than the data supports. For the business objective of this project, that also means missing an opportunity to demonstrate strong product thinking, data transparency, and end-to-end engineering quality in a portfolio setting.

---

## 4. Goals

### Product Goals
1. Let a user search for a European location and receive a clear, scenario-based coastal exposure result.
2. Show the result on a high-quality interactive map with strong visual clarity.
3. Present results in language that is understandable to a non-specialist user without making unsupported claims.
4. Make the methodology, data sources, and limitations visible in-product.
5. Restrict MVP behavior so that the application remains scientifically cautious and fact-based.

### Business Goals
1. Create a portfolio-grade product that demonstrates strength in .NET, Azure, solution architecture, frontend engineering, and geospatial product design.
2. Build a foundation that can later expand into a broader climate-risk product.
3. Produce a demo that can be shown reliably in interviews, GitHub reviews, and portfolio discussions without requiring the audience to infer missing behavior.
4. Favor a low-operations MVP deployment model over unnecessary infrastructure complexity.

---

## 5. Non-Goals

This PRD does **not** cover the following for MVP:

1. Global coverage outside Europe.
2. Inland climate risks such as heat, drought, wildfire, river flooding, or insurance pricing.
3. Parcel-level, engineering-grade, mortgage-grade, insurance-grade, or legal determinations.
4. Real-time weather, live flood alerts, or operational emergency forecasting.
5. Annual or single-year precision across every future year.
6. Street-level photorealistic flood simulations or before/after renders.
7. Native mobile applications.
8. User accounts, saved searches, collaboration, or dashboards.
9. User-uploaded shapefiles, GIS layers, or custom datasets.
10. Kubernetes-based deployment as an MVP requirement.

---

## 6. Target Users

**Note:** Primary and secondary personas were not explicitly provided in the source brief. The personas below are working assumptions for MVP and should be validated before implementation.

### Primary User Persona

| Persona | Needs | Motivations | Frustrations | Context of Use |
|---|---|---|---|---|
| Climate-aware resident, renter, buyer, or property researcher evaluating a European coastal location | Enter a location and understand whether it appears exposed under selected future scenarios and horizons | Wants a concrete, place-based view of coastal exposure instead of reading broad climate reports | Scientific tools feel fragmented or overly technical; many maps feel misleading or too generic | Browsing on desktop or mobile, often during exploratory research or casual curiosity |

### Secondary User Personas

| Persona | Needs | Motivations | Frustrations | Context of Use |
|---|---|---|---|---|
| Educator, researcher, or journalist explaining coastal climate risk | A simple, transparent visualization that can be shown to others | Needs a fast way to illustrate how scenario-based coastal exposure changes over time | Raw datasets are hard to communicate visually; lightweight tools often hide assumptions | Presentation, teaching, article prep, or stakeholder discussions |
| Portfolio reviewer, hiring manager, recruiter, or technical evaluator | A polished demo that clearly shows product thinking, architecture quality, visual execution, and data honesty | Wants to quickly assess the creator’s seniority and end-to-end capability | Toy demos often look impressive but break under scrutiny or hide limitations | Short review sessions, GitHub exploration, live demo, interview discussion |

---

## 7. Scope

### In Scope
1. Europe-only coverage.
2. Anonymous, public-facing responsive web application.
3. Free-text location search for Europe.
4. Map-based location refinement.
5. Coastal-only MVP gating via a configured coastal analysis zone.
6. Scenario selector.
7. Time-horizon selector for MVP-supported horizons.
8. Interactive map with selected location marker, overlay, and legend.
9. Plain-language result summary.
10. Visible data-source and methodology disclosure.
11. Clear unsupported, out-of-scope, empty, loading, and error states.
12. English-language UI.
13. Low-ops cloud deployment suitable for portfolio demonstration.

### Out of Scope
1. Worldwide address support.
2. Inland hazards.
3. User authentication and saved history.
4. Export reports, PDFs, or shareable branded reports.
5. Advanced GIS workflows.
6. Real estate valuation workflows.
7. Admin UI for dataset management.
8. User-to-user sharing or social features.
9. Full multilingual localization.

### Future Considerations
1. Additional time horizons or interpolated timeline behavior.
2. Additional scenario presets.
3. Inland climate-risk modes.
4. Country-specific overlays such as adaptation infrastructure or protected areas.
5. 3D terrain or cinematic visualization modes.
6. Save/share features.
7. Public methodology page and downloadable technical appendix.
8. Expanded global coverage.

---

## 8. Functional Requirements

### Search and Location Selection

**FR-001** The system shall display a landing view that contains a search input and an interactive Europe-focused map.

**FR-002** The search input shall accept a free-text location query between 1 and 200 characters.

**FR-003** The system shall block empty submission and display inline validation when the user attempts to search with no input.

**FR-004** When a valid query is submitted, the system shall request geocoding results from the configured geocoding provider.

**FR-005** If the geocoding provider returns multiple candidate matches, the system shall display up to 5 ranked candidates for user selection.

**FR-006** When the user selects a candidate location, the system shall center the map on that location and place a marker.

**FR-007** After a location has been selected, the user shall be able to refine the location by clicking or tapping on the map to move the marker.

**FR-008** When the marker location changes, the system shall update the active assessment using the current scenario and time horizon.

### Geography and Scope Validation

**FR-009** The system shall validate whether the selected location is within the supported Europe geography.

**FR-010** If the selected location is outside supported Europe geography, the system shall display an **Unsupported Geography** state and shall not run exposure assessment.

**FR-011** The system shall validate whether the selected location falls within the configured coastal analysis zone.

**FR-012** If the selected location is within Europe but outside the configured coastal analysis zone, the system shall display an **Out of Scope** state and shall not run exposure assessment.

**FR-013** If the selected location is within Europe and within the coastal analysis zone, the system shall run an exposure assessment for the active scenario and time horizon.

### Scenario and Time Horizon Controls

**FR-014** The system shall provide a scenario selector driven by a configured MVP scenario set.

**FR-015** The system shall provide a time-horizon control that supports exactly these MVP horizons: **2030**, **2050**, and **2100**.

**FR-016** The system shall apply a configured default scenario and default time horizon after the first valid in-scope location is selected.

**FR-017** When the user changes the active scenario or time horizon, the system shall refresh both the result summary and the map overlay without requiring a new location search.

**FR-018** The active scenario and active time horizon shall remain visibly indicated in the UI at all times while a result is displayed.

### Assessment and Result States

**FR-019** For an in-scope location, the system shall return exactly one of the following result states:
- **Modeled Coastal Exposure Detected**
- **No Modeled Coastal Exposure Detected**
- **Data Unavailable**
- **Out of Scope**
- **Unsupported Geography**

**FR-020** The result panel shall display a plain-language summary that includes:
- selected location label,
- active scenario,
- active time horizon,
- current result state.

**FR-021** If the result state is **Modeled Coastal Exposure Detected**, the map shall render the relevant exposure layer in relation to the selected marker.

**FR-022** If the result state is **No Modeled Coastal Exposure Detected**, the map shall still render the selected marker and a valid legend/context for the active layer.

**FR-023** If required data for the selected location/scenario/horizon combination is unavailable, the system shall return **Data Unavailable** and shall not silently substitute another dataset or horizon.

**FR-024** The system shall display a visible disclaimer that the result is scenario-based and not an engineering, legal, insurance, mortgage, or financial determination.

**FR-025** The system shall not use definitive copy such as “this property will be underwater” in MVP result messaging.

### Visualization and Map Behavior

**FR-026** The map shall render a Europe-focused base view on first load.

**FR-027** The map shall support pan and zoom interactions.

**FR-028** The selected location marker shall remain visually distinct from exposure overlays and base map content.

**FR-029** The system shall display a legend that updates to match the active layer and result context.

**FR-030** The scenario and time-horizon controls shall remain available after a result is displayed.

**FR-031** The map and result panel shall stay synchronized such that the visible overlay, legend, and text summary always reflect the same active scenario and time horizon.

### Transparency and Methodology

**FR-032** The system shall provide a visible “How to interpret this result” entry point.

**FR-033** The system shall provide a methodology/details panel or drawer that includes:
- source dataset names,
- methodology version,
- interpretation guidance,
- key limitations.

**FR-034** The system shall display data-source attribution required by the data providers and map providers used in MVP.

**FR-035** The system shall expose a methodology version identifier in both the UI and the assessment response payload.

### Empty, Loading, and Error States

**FR-036** Before any search is completed, the system shall display a meaningful empty state explaining what the user can do.

**FR-037** During geocoding or assessment processing, the system shall display a loading state.

**FR-038** If geocoding returns no matches, the system shall display a no-results state with guidance to try a different query.

**FR-039** If a recoverable geocoding or assessment request fails, the system shall display an error state with a retry action.

**FR-040** If the user changes the scenario, time horizon, or marker position while an earlier assessment request is still in progress, the system shall render only the latest completed request and ignore stale responses.

### Reset and Session Privacy

**FR-041** The system shall provide a reset action that clears the selected location, current result, and active overlay, and returns the UI to the initial state.

**FR-042** The system shall not persist raw entered addresses beyond request processing by default.

---

## 9. User Flows / Scenarios

### 9.1 Happy Path: Valid Coastal Location

1. User opens the application.
2. User sees the search box, map, and a short explanation of what the app does.
3. User enters a European coastal location query.
4. System returns one or more candidate matches.
5. User selects a candidate.
6. System centers the map, places a marker, validates Europe support and coastal-scope eligibility, and applies the default scenario and time horizon.
7. System returns the assessment result.
8. User sees:
   - result summary,
   - active scenario,
   - active time horizon,
   - map overlay,
   - legend,
   - methodology entry point.
9. User changes the time horizon.
10. System updates the map and summary without requiring a new search.
11. User changes the scenario.
12. System updates the map and summary again.

### 9.2 Alternate Flow: Ambiguous Address

1. User enters a location query that matches multiple places.
2. System displays ranked candidate matches.
3. User selects the intended place.
4. Flow continues from step 6 of the main happy path.

### 9.3 Alternate Flow: Manual Map Refinement

1. User selects a candidate location.
2. Marker is placed on the map.
3. User clicks/taps a nearby point on the map to refine the position.
4. System moves the marker and reruns the assessment using the same scenario and time horizon.

### 9.4 Alternate Flow: In-Scope Europe, but Outside Coastal MVP Scope

1. User enters an inland European location.
2. System validates that the location is in Europe.
3. System determines that the location is outside the configured coastal analysis zone.
4. System displays:
   - **Out of Scope** state,
   - explanation that MVP covers Europe coastal sea-level exposure only,
   - option to search another location.

### 9.5 Edge Case: Outside Supported Geography

1. User enters a non-European location.
2. System validates geography.
3. System displays **Unsupported Geography**.
4. No assessment is performed.

### 9.6 Edge Case: No Geocoding Result

1. User enters a query that returns no candidate matches.
2. System displays a no-results message and guidance to try a different query.
3. Prior valid result, if any, remains unchanged until the user resets or selects a new valid location.

### 9.7 Edge Case: Data Unavailable

1. User selects an in-scope coastal location.
2. System attempts assessment for the active scenario/horizon.
3. Required data is missing or unavailable.
4. System displays **Data Unavailable** with guidance and without substituting another horizon or scenario.

### 9.8 Error Flow: Recoverable Network or Service Error

1. User initiates search or assessment.
2. Upstream request fails due to a recoverable error.
3. System displays error messaging and a retry action.
4. User retries.
5. System repeats the failed step.

### 9.9 Edge Case: Rapid Control Changes

1. User selects a valid location.
2. User quickly changes horizon or scenario multiple times.
3. System may start multiple requests.
4. Only the latest request result is rendered.
5. Older responses are ignored.

---

## 10. UX / UI Expectations

### 10.1 Screens / Views

**A. Landing / Search View**
- Search input visible on first load.
- Europe-focused map visible on first load.
- Short supporting copy explains that the app shows scenario-based coastal exposure for Europe.

**B. Results View**
- Map remains the primary visual surface.
- Result summary panel is visible alongside the map on larger screens.
- On smaller screens, the summary panel may collapse into a bottom sheet or drawer.

**C. Methodology / Details View**
- Accessible from the result view.
- Contains source names, methodology version, interpretation guidance, and limitations.

### 10.2 Input Validation
- Empty search submission must show inline validation.
- Query length over 200 characters must be blocked with inline validation.
- If a candidate location cannot be resolved to coordinates, the system must show a no-results or error state.

### 10.3 Loading States
- Search/geocoding loading state must appear after submission.
- Assessment loading state must appear after a valid candidate or marker position is selected.
- Loading state must not misrepresent stale results as current.
- While loading, map pan/zoom may remain interactive, but stale result text must not be treated as active for the pending request.

### 10.4 Empty States
- Initial empty state must explain the app’s purpose and next action.
- No-results empty state must guide the user to refine or change the query.

### 10.5 Error States
- Error states must distinguish between:
  - unsupported geography,
  - out-of-scope inland/coastal gating,
  - data unavailable,
  - recoverable request failure,
  - no geocoding match.
- Error states must include a clear next step where applicable.

### 10.6 Confirmation States
- Successful location selection is confirmed by:
  - marker placement,
  - centered map,
  - visible result summary,
  - visible active scenario and horizon.
- Reset action returns the user to the initial empty state.

### 10.7 Accessibility Expectations
- Core flows must be operable by keyboard.
- Search input, candidate list, buttons, and methodology entry point must have accessible labels.
- Result meaning must not rely on color alone.
- The result summary must provide a text equivalent of the visual state shown on the map.
- Focus order must be logical and predictable.
- Status changes such as loading, error, and result update should be announced to assistive technologies where appropriate.

### 10.8 Responsive Behavior
- Desktop is the primary presentation target for MVP.
- Tablet and mobile layouts must remain functional and readable.
- On smaller screens, controls may stack or collapse into drawers, but the user must still be able to:
  - search,
  - select a location,
  - change scenario,
  - change time horizon,
  - read the result summary,
  - access methodology information.

---

## 11. Business Rules

**BR-001** MVP is public and anonymous. No user sign-in is required.

**BR-002** All end users have the same permissions in MVP. No role-based UI differences are exposed to users.

**BR-003** Supported geography is Europe only. The exact country/territory boundary definition must be captured in the implementation methodology.

**BR-004** Coastal analysis is performed only for locations within a configured coastal analysis zone. The exact definition of that zone is an open question and must be documented before implementation.

**BR-005** The default scenario and default time horizon are configuration-driven. Final defaults are not yet specified.

**BR-006** Candidate locations returned from geocoding are displayed in provider-ranked order.

**BR-007** A maximum of 5 geocoding candidates are shown for a query.

**BR-008** Search input length is limited to 200 characters.

**BR-009** If multiple geocoding candidates have similar or identical labels, the UI must include enough locality/country detail to distinguish them.

**BR-010** The result state taxonomy is fixed to:
- Modeled Coastal Exposure Detected
- No Modeled Coastal Exposure Detected
- Data Unavailable
- Out of Scope
- Unsupported Geography

**BR-011** “Modeled Coastal Exposure Detected” means the selected point intersects the active modeled exposure layer according to the current methodology version.

**BR-012** “No Modeled Coastal Exposure Detected” means the selected point does not intersect the active modeled exposure layer according to the current methodology version.

**BR-013** If the selected point falls in an area with missing data for the active layer, the system returns **Data Unavailable**.

**BR-014** The system must not silently interpolate, substitute, or downgrade to another scenario, horizon, or dataset when the requested one is unavailable.

**BR-015** Results must always display the active methodology version and source attribution.

**BR-016** Raw address strings are not stored by default.

**BR-017** MVP language is English only.

**BR-018** Dataset refresh is assumed to be an internal/manual operational workflow for MVP and is not exposed as a user feature.

---

## 12. Data and Integrations

### 12.1 Main Entities / Data

| Entity | Description | Key Fields |
|---|---|---|
| Search Query | Raw user-entered location text | queryText, timestamp |
| Geocode Candidate | Candidate match returned from geocoding | label, country, latitude, longitude, providerRank |
| Selected Location | User-confirmed map point | latitude, longitude, displayLabel |
| Scenario | Supported projection scenario option | scenarioId, displayName, sourceMapping |
| Time Horizon | Supported future horizon | horizonId, displayLabel |
| Exposure Assessment | Result for selected location + scenario + horizon | resultState, methodologyVersion, sourceSet, generatedAt |
| Layer Metadata | Information about the active map layer | layerId, sourceName, versionDate, legendSpec |
| Methodology Metadata | Human-readable interpretation and version details | methodologyVersion, assumptions, limitations |

### 12.2 Key Inputs and Outputs

**Inputs**
- Free-text location query.
- User-selected candidate or map-refined coordinates.
- Active scenario.
- Active time horizon.

**Outputs**
- Result state.
- Plain-language summary.
- Visible map overlay.
- Legend.
- Source attribution.
- Methodology version and limitations.

### 12.3 External Data Sources and Systems

**Sea-level projection sources**  
MVP should be based on authoritative public climate sources. The NASA AR6 Sea Level Projection Tool provides access to IPCC AR6 sea-level projection data, and Climate-ADAPT also references both the NASA tool and the PROTECT sea level projection tool as relevant sources for future sea-level scenarios. https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool

**Elevation source**  
Copernicus DEM is the recommended public elevation source for MVP. Copernicus describes it as a Digital Surface Model that includes buildings, infrastructure, and vegetation. The EEA also states that EU-DEM is not maintained anymore and points users to Copernicus DEM instead. https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM

**Supporting coastal indicators**  
The Copernicus Climate Data Store provides programmatic API access and offers global sea-level change indicator datasets that include tides, storm surges, and sea-level indicators useful for contextual or supporting layers. These are suitable as supporting data but should not be treated as a substitute for clearly documented methodology. https://cds.climate.copernicus.eu/how-to-api

**Geocoding**  
A geocoding provider is required for free-text search. The public Nominatim service is governed by an acceptable-use policy and should be treated as development/low-volume infrastructure only. Final MVP geocoding strategy remains open; a self-hosted or production-suitable alternative should be selected before launch. https://operations.osmfoundation.org/policies/nominatim/

**Frontend / map libraries**  
The planned implementation assumes Next.js for the web application shell, MapLibre GL JS for interactive browser mapping, and deck.gl for high-performance geospatial visualization. https://nextjs.org/docs/app/getting-started

**Backend / hosting / storage**  
The planned implementation assumes ASP.NET Core for the backend API, Azure Container Apps for low-ops container hosting, Azure Blob Storage for object storage of large geospatial assets, Azure Database for PostgreSQL for structured application data, and TiTiler or equivalent for dynamic map tile serving from cloud-optimized geospatial assets. https://learn.microsoft.com/en-us/aspnet/core/?view=aspnetcore-10.0

### 12.4 Events / Triggers

**User-triggered**
- Search submitted
- Candidate selected
- Marker moved
- Scenario changed
- Time horizon changed
- Reset invoked
- Methodology panel opened

**System-triggered**
- Geocoding started/completed/failed
- Assessment started/completed/failed
- Data unavailable state returned
- Unsupported/out-of-scope validation returned

### 12.5 Privacy and Security Implications

1. A raw address can be sensitive user input and must be treated accordingly.
2. MVP should avoid retaining raw addresses by default.
3. If analytics are added later, they should prefer aggregated, non-identifying events over raw search storage.
4. Secrets, service credentials, and dataset access tokens must not be exposed in client-side code.
5. A privacy notice may be required if analytics or logging practices go beyond operational necessity.

---

## 13. Non-Functional Requirements

### Performance
**NFR-001** Initial app shell load on a modern desktop browser over broadband should reach interactive state within **4 seconds p75**.  
**NFR-002** Geocoding response time should be **2.5 seconds p95** or better, excluding upstream provider outages.  
**NFR-003** Exposure assessment response time should be **3.5 seconds p95** or better for normal in-scope requests.  
**NFR-004** Scenario or time-horizon switches after the initial result should update the visible result within **1.5 seconds p95** when required assets are already available.  

### Security
**NFR-005** All client-server communication must use HTTPS.  
**NFR-006** No secrets may be embedded in client-side source.  
**NFR-007** Raw user-entered addresses must not be stored by default.  

### Reliability / Availability
**NFR-008** Target availability for the public MVP is **99.5% monthly**, excluding planned maintenance.  
**NFR-009** The system must fail gracefully by returning clear user-visible error or unavailable states rather than blank or broken UI.  
**NFR-010** The deployed backend services must expose health/readiness endpoints for operations monitoring.  

### Observability / Logging
**NFR-011** The backend must emit structured logs for geocoding, assessment, errors, and result-state generation.  
**NFR-012** Assessment requests must include correlation identifiers in logs.  
**NFR-013** Logs must be sufficient to distinguish geocoding failures, validation failures, data-unavailable states, and internal service errors.  

### Accessibility
**NFR-014** Core MVP flows should meet **WCAG 2.2 AA** intent for keyboard access, contrast, labeling, and non-color-dependent communication.  
**NFR-015** Every result shown visually on the map must also have a text equivalent in the summary panel.  

### Localization
**NFR-016** MVP UI is English only.  
**NFR-017** UI copy should be stored in a way that supports later localization without major UI rewrites.  

### Scalability
**NFR-018** Application services should be stateless where practical so they can scale horizontally if traffic increases.  
**NFR-019** Large geospatial assets should be stored and served in a way that does not require full-file transfer for each map interaction.  

### Maintainability
**NFR-020** Methodology versioning must be explicit and visible in both the UI and service outputs.  
**NFR-021** The data-processing workflow must be reproducible and documented outside the UI so that layer generation can be re-run without manual guesswork.  
**NFR-022** MVP deployment should favor managed services and low operational complexity over infrastructure that is unnecessary for portfolio goals.

---

## 14. Success Metrics

### Product and User Metrics
1. **Search-to-result completion rate:** At least **85%** of valid in-scope QA test addresses return a completed result without manual retry.
2. **First-use task completion:** At least **90%** of pilot users can search a location and interpret the returned state within **2 minutes** without external explanation.
3. **Result comprehension quality:** In moderated testing, at least **80%** of users correctly distinguish between:
   - Unsupported Geography,
   - Out of Scope,
   - No Modeled Coastal Exposure Detected,
   - Modeled Coastal Exposure Detected.

### Performance and Reliability Metrics
4. **Search-to-first-result latency:** p95 time from candidate selection to visible result is **5 seconds or less**.
5. **Control-switch latency:** p95 time from scenario/horizon change to visible updated result is **1.5 seconds or less** after initial result.
6. **Unhandled error rate:** Less than **2%** of sessions end in an unhandled client-visible failure.

### Trust / Transparency Metrics
7. **Source visibility:** **100%** of displayed results include visible source attribution and methodology version.
8. **Copy integrity:** **0** approved QA findings where the UI copy overstates certainty beyond the underlying methodology.

### Portfolio / Demo Readiness Metrics
9. **Demo pass rate:** The application can complete scripted demo flows for at least **3 coastal European locations** and **3 inland European locations** without manual data manipulation.
10. **Reviewer clarity:** In portfolio review sessions, technical reviewers can identify the app’s core value, limitations, and architecture scope within a **3-minute** walkthrough.

---

## 15. Risks, Assumptions, and Dependencies

### Risks
1. **False precision risk:** Users may interpret model outputs as parcel-level certainty if copy or visuals are too strong.
2. **Data-resolution risk:** Public elevation and projection datasets may be too coarse for certain coastlines or urban contexts.
3. **Methodology risk:** Simplified exposure logic may not fully capture hydrological connectivity, defenses, or local conditions.
4. **Provider risk:** Public geocoding or map services may impose rate limits or usage constraints.
5. **Performance risk:** Large geospatial assets may degrade result latency or map responsiveness.
6. **Attribution/licensing risk:** Incorrect or incomplete attribution could create compliance problems.
7. **Scope creep risk:** Requests for global coverage, annual projections, 3D simulation, or inland hazards could dilute MVP quality.

### Assumptions
1. The product is portfolio-first and not initially a commercial SaaS offering.
2. MVP is Europe-only.
3. MVP is coastal-only.
4. MVP supports exactly three time horizons: 2030, 2050, and 2100.
5. MVP uses a configured scenario set, but final scenario labels are still to be confirmed.
6. Anonymous public access is sufficient for MVP.
7. Managed cloud hosting is preferred over Kubernetes for MVP.
8. Authoritative public datasets are sufficient to build a credible MVP.
9. Data refresh is an internal/manual workflow in MVP.
10. English-only UI is acceptable for MVP.

### Dependencies
1. Final selection and licensing validation of sea-level projection sources.
2. Final selection of geocoding provider and search strategy.
3. Definition of the coastal analysis zone.
4. Definition of the exact exposure methodology and boundary behavior.
5. Availability of geospatial preprocessing pipeline and layer-generation workflow.
6. Final design system and map visual design decisions.
7. Cloud infrastructure, CI/CD, and deployment configuration.
8. Final disclaimer and methodology copy review.

---

## 16. Open Questions

1. What is the final product name?
2. What exact scenario set should MVP expose to users?
3. What should the default scenario and default time horizon be?
4. How is the coastal analysis zone defined for MVP?
5. What exact methodology determines “Modeled Coastal Exposure Detected” for a point near a boundary?
6. Will the MVP use a self-hosted geocoder, a managed provider, or a development-only public geocoder during early stages?
7. What base map and tile provider will be used in production-like demo environments?
8. Will the app expose shareable URLs or deep links in MVP?
9. What dataset refresh cadence is expected after initial launch?
10. Should analytics be enabled in MVP, and if yes, what consent/privacy model applies?
11. Will the app expose raw coordinates to the user in addition to the display label?
12. Is tablet/mobile visual parity required, or is desktop-first sufficient provided all core flows work?

---

## 17. Acceptance Criteria

### 17.1 Feature-Level Acceptance Criteria

#### A. Search and Location Selection
**AC-001** *(FR-001, FR-002, FR-003)*  
**Given** the user is on the landing page  
**When** the user attempts to submit an empty query  
**Then** the system blocks submission and shows inline validation.

**AC-002** *(FR-004, FR-005)*  
**Given** the user submits a valid query and the geocoder returns multiple candidate matches  
**When** the results are displayed  
**Then** the system shows no more than 5 ranked candidates.

**AC-003** *(FR-006)*  
**Given** a candidate location is selected  
**When** the selection is confirmed  
**Then** the map centers on that location and a marker is displayed.

**AC-004** *(FR-007, FR-008)*  
**Given** a valid selected location already exists  
**When** the user clicks or taps another point on the map  
**Then** the marker moves to the new point and the assessment reruns using the active scenario and horizon.

#### B. Geography and Scope Validation
**AC-005** *(FR-009, FR-010)*  
**Given** the selected location is outside supported Europe geography  
**When** validation runs  
**Then** the system displays **Unsupported Geography** and does not run exposure assessment.

**AC-006** *(FR-011, FR-012)*  
**Given** the selected location is inside Europe but outside the configured coastal analysis zone  
**When** validation runs  
**Then** the system displays **Out of Scope**, explains that MVP covers Europe coastal sea-level exposure only, and does not run exposure assessment.

#### C. Scenario and Time Horizon
**AC-007** *(FR-014, FR-015, FR-016, FR-018)*  
**Given** the user selects an in-scope location for the first time  
**When** the result is returned  
**Then** a configured default scenario and configured default horizon are visibly active.

**AC-008** *(FR-017, FR-031)*  
**Given** a result is already displayed  
**When** the user changes the scenario or time horizon  
**Then** the map overlay, legend, and text summary all update to the same active state without requiring a new location search.

#### D. Assessment and Result States
**AC-009** *(FR-019, FR-020)*  
**Given** an in-scope location with valid data  
**When** assessment completes  
**Then** the system returns exactly one defined result state and the summary includes location, scenario, horizon, and result state.

**AC-010** *(FR-021)*  
**Given** the result state is **Modeled Coastal Exposure Detected**  
**When** the result is rendered  
**Then** the map shows the relevant exposure layer in relation to the selected marker.

**AC-011** *(FR-022)*  
**Given** the result state is **No Modeled Coastal Exposure Detected**  
**When** the result is rendered  
**Then** the map shows the selected marker and a valid legend/context for the active layer.

**AC-012** *(FR-023)*  
**Given** the selected location/scenario/horizon has missing required data  
**When** assessment completes  
**Then** the system returns **Data Unavailable** and does not silently switch to another dataset, scenario, or horizon.

#### E. Transparency and Methodology
**AC-013** *(FR-024, FR-025, FR-032, FR-033, FR-035)*  
**Given** any result is displayed  
**When** the user opens methodology/details  
**Then** the UI shows source names, methodology version, limitations, and a disclaimer that the result is not an engineering, legal, insurance, mortgage, or financial determination.

**AC-014** *(FR-034)*  
**Given** the map and result view are visible  
**When** the user inspects the screen footer/attribution area  
**Then** required data-source and map-provider attribution is visible.

#### F. Empty, Loading, and Error States
**AC-015** *(FR-036)*  
**Given** the user has not completed a search yet  
**When** the landing page loads  
**Then** the UI shows an initial empty state that explains the app’s purpose and next step.

**AC-016** *(FR-037)*  
**Given** geocoding or assessment is in progress  
**When** the request has not completed yet  
**Then** the system shows a loading state.

**AC-017** *(FR-038)*  
**Given** a query returns no geocoding matches  
**When** the response is received  
**Then** the UI shows a no-results state with guidance to try another query.

**AC-018** *(FR-039)*  
**Given** a recoverable request failure occurs  
**When** the error is shown  
**Then** the UI presents a retry action that reruns the failed step.

**AC-019** *(FR-040)*  
**Given** multiple assessment requests are in flight due to rapid user changes  
**When** earlier responses arrive after a later request has completed  
**Then** only the latest request result is rendered.

#### G. Reset and Privacy
**AC-020** *(FR-041)*  
**Given** a result is currently displayed  
**When** the user activates reset  
**Then** the marker, overlay, and result state are cleared and the UI returns to the initial empty state.

**AC-021** *(FR-042, BR-016)*  
**Condition:** Inspect application behavior and configured storage/logging behavior for default MVP operation.  
**Expected Result:** Raw entered address strings are not persisted beyond request processing by default.

#### H. Accessibility
**AC-022** *(UX / Accessibility, NFR-014, NFR-015)*  
**Given** a keyboard-only user navigates the core flow  
**When** the user searches, selects a candidate, changes scenario/horizon, and opens methodology  
**Then** all of those actions are possible without requiring a mouse, and the result meaning is available as text outside the map.

### 17.2 PRD Quality Acceptance Checklist

This PRD is acceptable only if all items below are true:

- [x] The problem and target users are clearly defined.
- [x] Scope is bounded and consistent with MVP intent.
- [x] Non-goals are explicit.
- [x] Key requirements are specific, numbered, and testable.
- [x] Main user flows are covered.
- [x] Edge cases and error states are covered.
- [x] Business rules are defined and visible.
- [x] Dependencies, assumptions, and risks are explicit.
- [x] Success metrics are defined.
- [x] Every major feature has testable acceptance criteria.
- [x] Ambiguities are exposed as assumptions or open questions rather than hidden.
- [x] The document is implementation-ready for engineering and QA at the product-requirements level.
