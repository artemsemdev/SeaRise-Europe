# 17 — Open Question Closure Proposal

> **Status:** Approved — all blocking proposals (OQ-02 through OQ-07) converted to ADRs (ADR-015 through ADR-020) on 2026-04-03
> **Purpose:** Recommend implementation-ready resolutions for the open questions referenced in the architecture set without rewriting the existing open-questions document until decisions are approved.
> **Decision lens:** Optimize for scientific caution, delivery realism, and low operational complexity for a solo-engineer MVP.

---

## 1. Scope and Consistency Notes

- This document proposes closures for the unresolved questions referenced from [12-risks-assumptions-and-open-questions.md](12-risks-assumptions-and-open-questions.md), [01-decision-closure.md](../delivery/01-decision-closure.md), and [ROADMAP.md](../delivery/ROADMAP.md).
- There is a numbering inconsistency in the current repo:
  - The PRD uses `OQ-01` for the final product name, which is already resolved as "SeaRise Europe".
  - The architecture open-questions document uses `OQ-01` for the browser support matrix.
- To avoid making that inconsistency worse, this proposal refers to the browser support matrix as `AQ-01` until the numbering is reconciled.

---

## 2. Recommended Closure Set

| ID | Proposed resolution | Why this is the best MVP choice |
|---|---|---|
| AQ-01 | Support latest 2 major desktop versions of Chrome, Edge, Firefox, Safari; latest iOS Safari and Android Chrome for functional mobile use | Aligns with desktop-first MVP, keeps testing scope realistic, avoids overcommitting to long-tail browsers |
| OQ-02 | Use 3 scenarios: `ssp1-26`, `ssp2-45`, `ssp5-85` | Best balance of scientific range, user comprehension, and UI simplicity |
| OQ-03 | Default to `ssp2-45` and `2050` | Middle-of-the-road scenario plus mid-century horizon gives the strongest first-run default |
| OQ-04 | Seed `coastal_analysis_zone` from Copernicus Coastal Zones 2018, dissolved into a single 10 km inland multipolygon | Official Europe-wide coastal dataset beats an arbitrary hand-tuned buffer |
| OQ-05 | Keep binary published COGs; `1` means modeled exposure detected by the `slr >= dem` rule inside the coastal zone | Best fit for the existing architecture, runtime simplicity, and reproducibility |
| OQ-06 | Use Azure Maps Search in production; keep Nominatim dev-only | Strong Europe coverage, clean field mapping, and best fit with the Azure deployment stack |
| OQ-07 | Use Azure Maps for basemap tiles with a light vector style and CORS origin-restricted subscription key | All services under Azure credits, overlay-friendly cartography, and consolidated key management with geocoding |
| OQ-08 | Do not ship deep links in MVP | Avoids coordinate-in-URL privacy/logging issues and reduces frontend state complexity |
| OQ-09 | No automatic refresh cadence; perform manual annual review and versioned rerun on source or methodology change | Realistic for static climate datasets and a solo-engineer operating model |
| OQ-10 | No client-side analytics in MVP; rely on server-side observability only | Lowest privacy risk and avoids the consent-banner workstream |
| OQ-11 | Show coordinates only in a collapsed Technical Details section, rounded to 4 decimals | Preserves transparency without turning coordinates into primary UI copy or false precision |
| OQ-12 | Desktop-first delivery; tablet/mobile must be functional, readable, and test-gated, but not pixel-parity with desktop | Matches the PRD and avoids turning responsive polish into a Phase 1 blocker |

---

## 3. Blocking Question Proposals

### OQ-02 — Scenario Set Definition

**Recommended decision**

Use exactly these three scenario rows:

| id | display_name | description | sort_order |
|---|---|---|---|
| `ssp1-26` | `Lower emissions (SSP1-2.6)` | Lower-emissions AR6 pathway used as the lower-bound scenario in MVP. | 1 |
| `ssp2-45` | `Intermediate emissions (SSP2-4.5)` | Mid-range AR6 pathway used as the default reference scenario in MVP. | 2 |
| `ssp5-85` | `Higher emissions (SSP5-8.5)` | Higher-emissions AR6 pathway used as the upper-bound scenario in MVP. | 3 |

**Rationale**

- The IPCC AR6 core set contains five illustrative SSP scenarios, but a consumer-facing MVP does not benefit from showing all five.
- Three evenly spaced scenarios give a clear lower / middle / upper range without overloading the selector.
- `SSP1-1.9` is valuable for 1.5°C-oriented analysis, but it is too close to `SSP1-2.6` for this MVP's three-option control.
- `SSP3-7.0` adds complexity with limited incremental user value once `SSP5-8.5` is already present as the upper-bound scenario.

**Important wording choice**

- Do **not** use the IPCC storyline labels such as "fossil-fuelled development" in the primary UI labels.
- That is an intentional inference from the IPCC guidance: the IPCC notes those narrative labels mainly refer to reference futures without additional climate policies and should not be over-read as literal user-facing descriptors.

**Implementation notes**

- Treat the three `id` values above as stable keys across the database, API contract, and blob layout.
- Keep descriptions short and content-guideline compliant; avoid "best case", "worst case", or present-day policy claims.

---

### OQ-03 — Default Scenario and Horizon

**Recommended decision**

- `defaults.scenarioId = "ssp2-45"`
- `defaults.horizonYear = 2050`

**Rationale**

- `ssp2-45` is the least opinionated default. It neither front-loads the most alarming scenario nor minimizes the signal.
- `2050` is the strongest MVP default horizon because:
  - `2030` risks under-showing differences and making the tool feel uninformative.
  - `2100` is scientifically useful but too distant for a first interaction.
  - `2050` is close enough to feel relevant and far enough to reveal meaningful change.

**Implementation notes**

- Set `is_default = true` only on `ssp2-45` in `scenarios`.
- Set `is_default = true` only on `2050` in `horizons`.

---

### OQ-04 — Coastal Analysis Zone Definition

**Recommended decision**

Define `coastal_analysis_zone` from the **Copernicus Land Monitoring Service Coastal Zones 2018** dataset:

1. Download the vector Coastal Zones dataset.
2. Dissolve all coastal-land polygons into a single geometry.
3. Clean topology in a projected CRS.
4. Reproject to EPSG:4326.
5. Clip to the final `europe` support geometry before seeding PostGIS.

**Why this is better than a hand-built buffer**

- It is an official Europe-wide coastal product rather than an arbitrary engineering heuristic.
- It already expresses a coherent coastal territory definition at **10 km inland**, which is conservative and easy to explain.
- It is reproducible: another engineer can rebuild the same geometry from a named source dataset.

**Tradeoff**

- This is still a product-scope boundary, not a hydrodynamic truth boundary.
- Some estuarine or lagoon cases beyond the 10 km inland extent may remain out of scope for MVP. That is acceptable and should be documented explicitly.

**Validation set**

Use at minimum these checks before seeding:

| Location | Expected |
|---|---|
| Amsterdam | In coastal zone |
| Barcelona | In coastal zone |
| Copenhagen | In coastal zone |
| Lisbon | In coastal zone |
| Venice | In coastal zone |
| Prague | Out of scope |
| Zurich | Out of scope |
| Vienna | Out of scope |
| Munich | Out of scope |
| Bratislava | Out of scope |

**Implementation note**

- This recommendation is an inference from the available official coastal dataset, not a claim that Copernicus intended it specifically as a flood-gating mask.
- For MVP, that tradeoff is worth taking because it is more defensible than choosing an unreferenced 20 km or 50 km custom buffer.

---

### OQ-05 — Exposure Threshold Methodology

**Recommended decision**

Keep the published runtime layers **binary**.

Pixel semantics for methodology `v1.0`:

- `1` = the selected grid cell is classified as exposed because projected mean sea-level rise for the selected scenario and horizon is greater than or equal to the DEM-derived elevation, after masking to `coastal_analysis_zone`
- `0` = the selected grid cell is inside `coastal_analysis_zone` but does not meet that exposure condition
- `NoData` = outside `coastal_analysis_zone` or missing source data

**Why**

- This is the best fit for the current architecture across:
  - TiTiler `/point` evaluation
  - COG storage layout
  - API contracts
  - result-state determination
  - reproducibility and versioning
- A continuous runtime layer would add real complexity without improving the MVP user contract, which is already binary at the result level.

**Recommended methodology metadata**

- `methodologyVersion = "v1.0"`
- `exposure_threshold = NULL`
- `exposure_threshold_desc = "No separate runtime threshold. Binary exposure is precomputed offline using the rule projected mean sea-level rise >= terrain elevation within the coastal analysis zone."`

**Draft methodology panel text**

- `whatItDoes`:
  - "This methodology combines IPCC AR6 mean sea-level rise projections with Copernicus DEM surface elevation to identify locations in the coastal analysis zone where projected mean sea-level rise reaches or exceeds terrain elevation under the selected scenario and time horizon."
- `whatItDoesNotAccountFor`:
  - "Flood defenses or adaptation infrastructure"
  - "Hydrodynamic flow behavior or detailed water pathways"
  - "Storm surge or tidal variability"
  - "Land subsidence or uplift"
  - "Local drainage systems or pumping infrastructure"

**Follow-up safeguard**

- During Phase 0 validation, if the simple binary rule produces obvious inland false positives, promote a `v1.1` methodology that adds a coastal-connectivity screen in the offline pipeline while keeping the published COG output binary.

---

### OQ-06 — Production Geocoding Provider

**Recommended decision**

Use **Azure Maps Search** as the production geocoder. Keep `NominatimGeocodingClient` for local development only.

**Why Azure Maps is the best fit here**

- The project already runs on Azure, so procurement, secrets, and operations stay within one platform.
- Azure Maps documents broad European geocoding coverage, including strong address and house-number support across the main target countries.
- The response shape maps cleanly to the internal `GeocodingCandidate` model.
- The API key stays server-side because all geocoding happens behind the backend API.

**Recommended normalization**

| Azure Maps field | Internal field |
|---|---|
| provider result order | `Rank` |
| `formattedAddress` | `Label` |
| `countryRegion.ISO` | `Country` |
| coordinate pair | `Latitude`, `Longitude` |
| `locality` + first relevant admin field + country name | `DisplayContext` |

**Important behavior**

- Post-filter results to a Europe allowlist before returning candidates to the client.
- This is critical for BR-003 and materially improves ambiguous searches such as "Amsterdam" or "Tbilisi".
- Keep `limit = 5` at the app boundary even if the provider returns more.

**Fallback position**

- If a Phase 0 spike shows weak result quality for representative European queries, the best fallback is **HERE Geocoding**, not a self-hosted geocoder.
- Self-hosting Pelias or Photon is not justified for this MVP.

---

### OQ-07 — Basemap Tile Provider

**Recommended decision**

Use **Azure Maps** as the basemap provider with:

- a light, overlay-friendly vector style (road_light or grayscale_light)
- a **subscription key** with CORS origin restriction
- MapLibre GL JS as already planned in the frontend architecture

**Why this is the best fit**

- Azure Maps is a first-party Azure service — fully covered by Azure startup credits, unlike third-party SaaS providers (MapTiler, Mapbox) which are not.
- Consolidates both geocoding (ADR-019) and basemap under a single Azure Maps account — one key, one billing, one dashboard.
- Azure Maps provides MapLibre-compatible vector tile endpoints with documented integration paths.
- Light/grayscale styles are overlay-friendly — suitable for exposure data visualization.
- CORS origin restriction matches the security architecture for browser-visible basemap credentials.

**Recommended configuration**

- `NEXT_PUBLIC_BASEMAP_STYLE_URL = <Azure Maps style endpoint URL with subscription key>`
- Key protection:
  - CORS origin restriction in Azure Portal (production + staging domains)
  - optional localhost access for development

**Attribution**

- Keep the MapLibre attribution control enabled.
- Ensure the visible attribution satisfies Azure Maps and OpenStreetMap requirements.
- Attribution text: "© Microsoft, © OpenStreetMap contributors"

**Why not MapTiler**

- MapTiler is a third-party SaaS not covered by Azure startup credits — would be the only non-Azure runtime cost.
- Azure Maps provides equivalent functionality for basemap tiles while staying within the Azure credit budget.

---

## 4. Pre-Launch / Non-Blocking Question Proposals

### AQ-01 — Browser Support Matrix

**Recommended decision**

Support policy for Phase 1:

- Desktop: latest 2 major versions of Chrome, Edge, Firefox, Safari
- Mobile/tablet functional support: latest iOS Safari and latest Android Chrome
- No Internet Explorer support
- No commitment to pixel-parity on legacy mobile browsers

**Why**

- This is the narrowest support matrix that still covers normal public usage for a modern web GIS application.
- It keeps QA scope aligned with a solo-engineer delivery model.

---

### OQ-08 — Shareable URLs / Deep Links

**Recommended decision**

Do **not** ship deep links in MVP.

**Why**

- The current architecture deliberately avoids putting raw user input in URLs.
- If lat/lng are later encoded into URLs, they are likely to appear in browser history, referrers, and infrastructure logs unless treated very carefully.
- Deep-linking is useful, but it is not core to the MVP value loop.

**Revisit condition**

- Revisit in Phase 2 only if implemented with a privacy-safe design, for example client-only hash state or short opaque IDs resolved server-side.

---

### OQ-09 — Dataset Refresh Cadence

**Recommended decision**

- No automatic scheduled refresh in MVP
- Manual annual review of upstream source availability and methodology fitness
- New layer generation only when:
  - an upstream source materially changes
  - the methodology changes
  - a data defect is found

**Why**

- Sea-level projection source data is not a daily-operational dataset.
- Versioned manual refresh fits `methodology_versions` much better than a background automation loop.

---

### OQ-10 — Analytics Implementation

**Recommended decision**

Do **not** add client-side product analytics in MVP.

Use only:

- structured backend logs
- API timing metrics
- Azure Log Analytics / KQL dashboards

**Why**

- This eliminates the need to introduce cookies, client identifiers, or a consent-banner workstream during MVP.
- It is enough to measure uptime, latency, error rates, and endpoint usage.

**When to revisit**

- Revisit only if the product moves beyond portfolio/demo use and genuinely needs user-behavior analysis.
- If revisited later, prefer a privacy-first tool such as Plausible before considering heavier analytics stacks.

---

### OQ-11 — Raw Coordinates in the UI

**Recommended decision**

Show coordinates only in a collapsed **Technical details** block on the result view.

Display format:

- latitude and longitude rounded to **4 decimal places**
- copy-to-clipboard action allowed

**Why**

- This preserves transparency and reproducibility without making coordinates primary UI content.
- Rounding avoids implying sub-meter precision that the methodology does not actually support.

---

### OQ-12 — Mobile-First vs Desktop-First Priority

**Recommended decision**

Adopt **desktop-first** as the design priority for MVP, with a hard requirement that mobile and tablet remain functional and readable.

**Minimum responsive acceptance bar**

- At `390px` width:
  - search works
  - candidate selection works
  - scenario and horizon controls work
  - result summary is readable
  - methodology panel is reachable
- At `768px` width:
  - all desktop core flows remain available without hidden dead ends

**Why**

- This matches the PRD directly and avoids spending Phase 1 time chasing full visual parity across breakpoints.

---

## 5. Recommended Next Actions

1. Convert OQ-02 through OQ-07 into ADR entries in [11-architecture-decisions.md](11-architecture-decisions.md).
2. Use this proposal to draft the seed-data spec described in [01-decision-closure.md](../delivery/01-decision-closure.md).
3. Reconcile the `OQ-01` numbering conflict between the PRD and architecture docs before implementation begins.
4. Add the final chosen external URLs and source metadata to `methodology_versions` and `geography_boundaries.source`.

---

## 6. External Source Notes

These sources informed the recommendations above:

- IPCC AR6 WGI Chapter 1 and Cross-Chapter Box 1.4 on the core SSP scenario set:
  - https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-1/
  - https://www.ipcc.ch/report/ar6/wg1/figures/chapter-1/ccbox-1-4-figure-1/
- NASA AR6 sea-level projection tool:
  - https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool
- Copernicus / EEA Coastal Zones product:
  - https://land.copernicus.eu/en/products/coastal-zones
  - https://www.eea.europa.eu/en/datahub/datahubitem-view/46fccbdc-d848-47a7-a58d-2aabc21c07cf
- Azure Maps geocoding coverage and API model:
  - https://learn.microsoft.com/azure/azure-maps/geographic-coverage
  - https://learn.microsoft.com/azure/azure-maps/geocoding-coverage
  - https://learn.microsoft.com/rest/api/maps/search/get-geocoding
- Azure Maps tile rendering and MapLibre integration:
  - https://learn.microsoft.com/azure/azure-maps/how-to-use-map-control
  - https://learn.microsoft.com/azure/azure-maps/choose-map-style
  - https://learn.microsoft.com/azure/azure-maps/geographic-coverage
