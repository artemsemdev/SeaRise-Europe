# SeaRise Europe — UX Content Guidelines

> **Owner:** Artem Sem
>
> **Status:** Active
>
> **Version:** 2.0
>
> **Last updated:** 2026-08-04

This document governs user-facing labels, result summaries, map legends,
loading and offline states, methodology text, and architecture-page claims.
The canonical domain states and product scope come from
[ADR-024](../architecture/adr/ADR-024-ar6-regional-projection-contract.md),
[ADR-021](../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md),
and the [PRD](PRD.md).

## 1. Voice

- **Clear:** plain language; explain a scientific term when first used.
- **Honest:** name limitations next to the claim they qualify.
- **Calm:** neither dramatize projected change nor minimize it.
- **Direct:** lead with the median, likely range, scenario, and horizon.
- **Precise about uncertainty:** distinguish AR6's likely range, source nodata,
  product scope, delivery failure, and unsupported geography.

## 2. Non-negotiable scientific rules

### Say what the model supports

| Use | Do not use |
|---|---|
| “Near this point, AR6 projects a median regional relative sea-level change of [value] by 2050 under SSP2-4.5.” | “Sea level at this property will be [value] higher in 2050.” |
| “The likely range published by AR6 is [lower] to [upper], relative to the 1995–2014 mean.” | “There is a 66% chance this place floods.” |
| “This value comes from a 1° source-grid location [distance] km from the marker.” | “This marker has property-level precision.” |

Use **projected regional relative sea-level change**, not “flooding,”
“inundation,” or “exposure.” The product does not compare with terrain or model
a flood event. Never call an output a regulatory flood zone or property risk.

### Keep scenario and horizon visible

Every completed result names:

- the selected place or point;
- the SSP scenario;
- the absolute horizon (`2030`, `2050`, or `2100`);
- median and likely range in metres relative to the 1995–2014 mean;
- source-grid location, distance, and native 1° resolution;
- the methodology version and data release.

Do not use relative horizons such as “+50 years.” They become ambiguous and do
not match the accepted artifact contract.

### Name scenarios accurately

| ID | Preferred short label | Supporting description |
|---|---|---|
| `ssp1-26` | Lower-emissions scenario (SSP1-2.6) | One possible pathway with lower emissions than the other product scenarios |
| `ssp2-45` | Intermediate-emissions scenario (SSP2-4.5) | The default comparison pathway; not a prediction or “most likely” future |
| `ssp5-85` | Higher-emissions scenario (SSP5-8.5) | One possible pathway with higher emissions than the other product scenarios |

Do not label these “NASA,” “Copernicus,” or “IPCC” forecasts. Those names
identify organizations or data roles, not three competing scenario models.
Avoid “optimistic,” “moderate,” and “worst case” unless approved scientific
review establishes exact meanings.

## 3. Four result states

Internal state IDs must remain stable. User-facing headlines may be localized,
but must preserve the meaning below.

### `ProjectionAvailable`

**Headline:** `Projected regional sea-level change available`

**Template:**

> Near this point, IPCC AR6 projects a median regional relative sea-level
> change of **[Median] m** by **[Year]** under **[Scenario label]**. Its
> medium-confidence likely range is **[Lower]–[Upper] m**, relative to the
> **1995–2014 mean**. The source-grid location is **[Distance] km** from the
> marker at native **1°** resolution. This is not a flood, inundation,
> terrain-exposure, or property-risk assessment.

### `DataUnavailable`

**Headline:** `Model data unavailable for this point`

**Template:**

> The active dataset has no usable value for this point under **[Scenario
> label]** in **[Year]**. No other scenario, year, or dataset was substituted.
> This is not a zero-change or no-risk result.

Nodata is a scientific domain state. A failed network request is described
separately as a delivery problem.

### `OutOfScope`

**Headline:** `Outside the coastal analysis area`

**Template:**

> This point is inside the supported Europe geometry but outside the versioned
> coastal analysis area. SeaRise Europe does not assess inland hazards. Search
> another settlement or choose a point closer to the coast.

Do not imply that “too far from the coast” means no coastal or climate risk.

### `UnsupportedGeography`

**Headline:** `Outside the supported Europe area`

**Template:**

> This point is outside the geography supported by the current SeaRise Europe
> release. Search a supported European settlement or choose another point.

Do not describe this as an application error.

## 4. Transient and degraded states

Transient states are not additional scientific outcomes.

| Context | Preferred copy |
|---|---|
| Search index initialization | `Loading the place index…` |
| Query processing | `Searching places…` |
| Local boundary/point lookup | `Checking [Place] against the selected data…` |
| Search index unavailable | `Place search data could not be loaded. Check your connection and try again.` |
| Required range not cached while offline | `This result is not available offline yet. Reconnect to load the selected data.` |
| Artifact request failed online | `The selected data could not be loaded. Try again.` |
| Basemap unavailable | `The background map is unavailable. Search and projection lookup can still be used.` |
| Release/schema invalid | `This data release cannot be used safely. Try again later.` |

Never say “the server is calculating,” “geocoding,” or “calling the assessment
service” in the target product. Search and lookup are local; network waits
are for immutable data artifacts or optional map context.

## 5. Search copy

### Initial state

**Heading:** `Explore regional sea-level projections across Europe`

**Body:**

> Search for a European city, town, or village, then compare IPCC AR6 regional
> relative sea-level projections for three scenarios and three horizons.

**Support text:**

> Results show regional projected change and a likely range, not flooding,
> property risk, or engineering assessments.

### Search control

- Label: `Find a city, town, or village`
- Placeholder: `Try Rotterdam, Porto, or Galway`
- No matches: `No matching places found. Check the spelling or try a nearby
  city, town, or village.`

Do not promise street addresses, postcodes, landmarks, or every real-world
settlement. Results come from a versioned local GeoNames catalog.

Candidate rows show place name, country, and first-level administration.

## 6. Required disclaimer

Show this disclaimer, or an editorial revision preserving every exclusion, on
every completed projection:

> This regional sea-level projection is for informational and educational use.
> It does not determine flooding, inundation, terrain exposure, or property
> risk. It is not an engineering assessment, structural
> survey, legal determination, insurance evaluation, mortgage guidance, or
> financial advice. Do not use it as a substitute for appropriate professional
> or local evidence.

The disclaimer supports, but does not replace, cautious result language.

## 7. Methodology and source content

The methodology surface includes:

| Element | Requirement |
|---|---|
| Release identity | Data release ID, build date, and methodology version |
| Scenario/horizon | Exact SSP pathway and absolute year |
| Sea-level source | Dataset name, version/snapshot, role, licence, and required acknowledgement |
| Support/coastal geometry | Source/version and the current coastal-zone rule |
| Method summary | Plain-language description of the source-native grid-only lookup |
| Not modeled | Flood defences, storm surge, local drainage, hydrodynamic connectivity, subsidence, and other omitted effects as applicable |
| Resolution | What source resolution permits and why a precise marker is not property precision |
| Integrity | Manifest, STAC catalog, checksums, and signed provenance links |

Before the scientific validation gate passes, explicitly state that checked-in
data is synthetic or provisional. Do not use a planned source or method in the
past tense.

## 8. Architecture page claims

Lead with outcomes:

> SeaRise Europe precomputes deterministic geospatial work, publishes
> verifiable data artifacts, and lets the browser search and look up projections
> locally—so the normal user journey has no application backend, database, or
> tile server.

Then support the statement with measured bundle size, timings, network traces,
artifact sizes, current cost model, release identity, licences, and provenance.

Use “target,” “planned,” or “migration in progress” until an architecture
fitness function has passed in production-like conditions. Use “zero or
near-zero idle cost within current free allowances,” not “free forever.” Use
“offline-capable after required data is cached,” not “works fully offline.”

## 9. Visual mock status

The self-contained [SeaRise Flight mock](Mock/SeaRise-Flight.html) is the active
visual and interaction direction. It replaces the legacy multi-page mock set.
The mock uses synthetic illustrative values and remains subordinate to this
guide, the PRD, methodology, release contracts, accessibility requirements, and
ADR-021. Fixture counts, release IDs, artifact paths, timings, coordinates, and
classifications must not be copied into production as constants. See
[MOCK_REQUIREMENTS_MAP.md](Mock/MOCK_REQUIREMENTS_MAP.md) for the implementation
scope, required corrections, missing states, and GitHub issue links.

## 10. Prohibited language

| Prohibited wording | Why |
|---|---|
| `will flood`, `will be underwater` | Claims future certainty |
| `safe`, `protected`, `no risk`, `risk detected` | Claims a risk or safety determination the product does not make |
| `flood zone` | Can imply a regulatory or legal designation |
| `your home`, `your property` | The product evaluates a point at dataset resolution |
| `100% accurate` | Unsupported precision |
| `all European settlements` | Overstates a source-defined catalog |
| `fully offline` | Overstates uncached layer availability |
| `free forever` | Hosting terms and usage can change |
| `real data` without release evidence | Hides fixture/provisional status |

## 11. Glossary

| Term | Product definition |
|---|---|
| Scenario | One possible emissions pathway used to select a sea-level projection; not a forecast of which future will occur |
| Horizon | The absolute year (`2030`, `2050`, or `2100`) evaluated for the selected scenario |
| Projected regional relative sea-level change | AR6 change at the selected source-grid location relative to the 1995–2014 mean; not an absolute water level |
| Likely range | The source-published medium-confidence q0.167–q0.833 interval; not a project-derived flood probability |
| Coastal analysis area | The versioned product geometry within which projection lookup is offered; it is a scope rule, not a flood-reach claim |
| Support geometry | The versioned boundary defining which European coordinates the product supports |
| Data release | An immutable, identified set of artifacts, metadata, checksums, and provenance |
| Available offline | The browser has cached every artifact required for the stated interaction |
