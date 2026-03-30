# SeaRise Europe — UX Content & Writing Guidelines

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

> **Audience for this document:** Anyone writing UI copy, error messages, result summaries, disclaimers, or methodology content for SeaRise Europe. Applies to all surfaces: labels, tooltips, inline validation, results panel, methodology drawer, and empty/error states.

---

## 1. Voice and Tone

### Voice (consistent across all contexts)

SeaRise Europe's voice is:

- **Clear.** Uses plain language accessible to a non-specialist. Avoids scientific jargon unless the term is immediately explained.
- **Honest.** Never implies more certainty than the data supports. Acknowledges limitations as a matter of course, not as a legal disclaimer hidden in fine print.
- **Calm.** Coastal risk is a serious subject. The product does not dramatize, catastrophize, or use alarmist language. It also does not minimize or dismiss.
- **Direct.** Gets to the answer. Does not over-explain before delivering the result. Methodology is available on demand, not forced on the user before they see the result.
- **Precise about uncertainty.** There is a difference between "we don't know" and "this model shows no exposure." Both are specific. Use the specific language.

### Tone (adjusts by context)

| Context | Tone Adjustments |
|---|---|
| Landing / empty state | Welcoming, brief; invites action without overpromising |
| Loading state | Neutral, factual; acknowledges the user is waiting |
| Result summary | Measured and specific; factual, not dramatic |
| Methodology panel | Informative, slightly more technical; assumes the user wants detail |
| Out of scope / unsupported geography states | Matter-of-fact; no apology, no drama; clear next step |
| Error states | Calm; acknowledges the failure; offers a path forward |
| Disclaimers | Formal and precise; must not be vague or legalistic |

---

## 2. Scientific Language Rules

These rules apply to every result-related string in the product. They exist to prevent false precision and to maintain trust.

### 2.1 Always use modeled language for results

Every result must make clear that the output is based on a model, not a measurement of actual future conditions.

| Correct | Incorrect |
|---|---|
| "This location shows modeled coastal exposure under the selected scenario." | "This location will be flooded." |
| "No coastal exposure was modeled for this location under the selected scenario and horizon." | "This location is safe." |
| "Based on the active scenario and time horizon, the model indicates coastal exposure." | "Sea levels will reach this location by 2050." |

### 2.2 Always attribute results to the active scenario and time horizon

A result without its scenario and horizon context is meaningless. Every result summary must include both.

| Correct | Incorrect |
|---|---|
| "Modeled coastal exposure detected for [Location] under [Scenario] by [Year]." | "Exposure detected." |
| "No modeled exposure for [Location] in [Scenario] by [Year]." | "No flood risk found." |

### 2.3 Never imply parcel-level accuracy

The product works at a dataset resolution that cannot support property-level or address-precise claims.

| Correct | Incorrect |
|---|---|
| "This location falls within a modeled exposure zone at the resolution of the active dataset." | "This property is in a flood zone." |
| "Results reflect dataset resolution and are not suitable for site-specific engineering decisions." | "Your home is at risk." |

### 2.4 Use "exposure" not "flooding"

"Flooding" implies a specific hydrological event. "Exposure" reflects the product's actual claim: that a location intersects a modeled zone derived from sea-level projections and elevation data.

| Correct | Incorrect |
|---|---|
| "Modeled coastal exposure detected." | "Modeled flooding detected." |
| "Coastal sea-level exposure zone." | "Flood zone." |

### 2.5 Never describe a "No Exposure" result as safe

"No modeled exposure" is a specific technical statement about what the model shows. It is not a safety assurance.

| Correct | Incorrect |
|---|---|
| "No modeled coastal exposure detected under the selected scenario and horizon." | "This location is not at risk." |
| "The selected location does not intersect the active exposure layer for this scenario and time horizon." | "You're safe here." |

### 2.6 Distinguish "Data Unavailable" from "No Exposure"

These are different states. "Data Unavailable" means the model could not be evaluated — not that the result is zero.

| Correct | Incorrect |
|---|---|
| "Data is not available for this location under the selected scenario and horizon. This does not mean the location is unexposed." | "No data, so no risk." |

---

## 3. Result State Copy

### 3.1 Modeled Coastal Exposure Detected

**Headline:** `Modeled Coastal Exposure Detected`

**Summary template:**
> Based on the **[Scenario]** scenario and the **[Year]** time horizon, the selected location falls within a modeled coastal exposure zone. This result is based on **[Dataset Name]** sea-level projections and **[Elevation Dataset]** elevation data.
>
> This result is a model estimate, not a site-specific engineering assessment. See the methodology for assumptions, resolution, and limitations.

**Dos:**
- State the scenario and horizon explicitly.
- Name the data source.
- Link to methodology.

**Don'ts:**
- Do not use "will," "certain," or "definite."
- Do not describe the outcome as "flooding."
- Do not imply the result is suitable for legal, insurance, or property decisions.

---

### 3.2 No Modeled Coastal Exposure Detected

**Headline:** `No Modeled Coastal Exposure Detected`

**Summary template:**
> Based on the **[Scenario]** scenario and the **[Year]** time horizon, the selected location does not fall within the active modeled exposure zone. This result reflects the resolution and assumptions of the current methodology and does not constitute a safety determination.

**Dos:**
- State the scenario and horizon explicitly.
- Acknowledge what the result does not mean (not a safety guarantee).

**Don'ts:**
- Do not say "safe," "protected," "no risk," or "nothing to worry about."
- Do not imply the location is guaranteed to be unaffected by sea-level rise.

---

### 3.3 Data Unavailable

**Headline:** `Data Unavailable`

**Summary template:**
> Data is not available for this location under the **[Scenario]** scenario and **[Year]** time horizon. The system has not substituted another scenario, horizon, or dataset. Try a different scenario or time horizon, or check the methodology for coverage notes.

**Dos:**
- Confirm that no substitution has occurred.
- Offer a clear next action.

**Don'ts:**
- Do not imply the location is unexposed because data is missing.
- Do not leave the user with no path forward.

---

### 3.4 Out of Scope

**Headline:** `Outside MVP Coverage Area`

**Summary template:**
> The selected location is within Europe but outside the coastal analysis area covered by this tool. SeaRise Europe currently covers coastal sea-level exposure only. Inland locations are not in scope for MVP. Try a location closer to the coast.

**Dos:**
- Be specific about what scope means: coastal only.
- Offer a clear next action (search a different location).

**Don'ts:**
- Do not say "no risk" or "not affected."
- Do not leave the user with no way to recover.

---

### 3.5 Unsupported Geography

**Headline:** `Location Outside Supported Area`

**Summary template:**
> The selected location is outside the area supported by SeaRise Europe. This tool covers European coastal locations only. Please search a European address or location.

**Dos:**
- Be direct about the geographic scope constraint.
- Offer a clear next action.

**Don'ts:**
- Do not apologize for the limitation.
- Do not say "we can't help you here" — say what the tool *does* support.

---

## 4. Disclaimer Copy

The following disclaimer must appear on every result view. It must not be minimized into a single footer line with no explanation.

**Required disclaimer:**
> This result is a scenario-based model estimate for informational purposes only. It is not an engineering assessment, structural survey, legal determination, insurance evaluation, mortgage guidance, or financial advice. Do not rely on this result for decisions requiring professional expertise.

This exact text — or a minor editorial revision that preserves all enumerated exclusions — must pass copy review before implementation.

**Mandatory inclusions:**
- Engineering assessment
- Legal determination
- Insurance evaluation
- Mortgage guidance
- Financial advice

None of these may be removed or combined into a vague phrase like "professional purposes."

---

## 5. Methodology Panel Copy

The methodology panel must include the following elements. Each has specific content requirements.

| Element | Content Requirement |
|---|---|
| **Methodology version** | The version identifier used in the assessment response. E.g., "Methodology v1.0" |
| **Sea-level projection source** | Full name of the dataset, version, and licensing entity. E.g., "IPCC AR6 sea-level projections (NASA Sea Level Change Team)" |
| **Elevation data source** | Full name of the dataset. E.g., "Copernicus DEM (Digital Surface Model, GLO-30)" |
| **What this methodology does** | 2–4 sentence plain-language explanation of how projection data and elevation data are combined to produce a result |
| **What this methodology does not account for** | Explicit list: flood defenses, hydrodynamic connectivity, storm surge, land subsidence, local drainage infrastructure |
| **Dataset resolution note** | The approximate spatial resolution of the active dataset, and what this means for result accuracy at a street or property level |
| **Interpretation guidance** | "Modeled exposure means…" and "No modeled exposure means…" — each in 1–2 sentences |

---

## 6. Empty State Copy

### Landing / Initial State

**Heading:** `Explore coastal sea-level exposure in Europe`

**Body:**
> Enter a European address, city, or location to see how it appears in scenario-based sea-level projections. Choose a scenario and time horizon to compare different outlooks.

**Subtext:**
> Results are model-based estimates, not engineering assessments. See methodology for details.

---

### No Geocoding Results

**Heading:** `No locations found`

**Body:**
> We could not find a match for "[query]". Try a more specific address, a city name, or a well-known landmark.

---

## 7. Loading State Copy

| Context | Copy |
|---|---|
| Geocoding in progress | `Searching for locations…` |
| Assessment in progress | `Calculating exposure for [Location]…` |

Loading states must not say "Almost there!" or make predictions about how long the request will take.

---

## 8. Error State Copy

| Error Type | Heading | Body |
|---|---|---|
| Recoverable geocoding failure | `Search temporarily unavailable` | `We could not complete your search right now. Please try again.` [Retry button] |
| Recoverable assessment failure | `Result temporarily unavailable` | `We could not calculate the exposure for this location right now. Please try again.` [Retry button] |
| Unrecoverable / unexpected | `Something went wrong` | `An unexpected error occurred. Reload the page and try again. If this continues, try a different browser.` |

**Rules for error copy:**
- Never expose raw error codes or stack traces to the user.
- Never say "contact support" unless a support channel actually exists.
- Always provide a next action (retry, reload, try another query).
- Never blame the user.

---

## 9. Prohibited Language

The following phrases are banned from all product copy. Any instance discovered in a QA review is an automatic finding.

| Prohibited | Reason |
|---|---|
| "will flood" / "will be underwater" | States future certainty the model cannot support |
| "is safe" / "not at risk" | States a safety guarantee the product cannot provide |
| "no risk" | Same as above |
| "100% accurate" | No geospatial model achieves this |
| "predicts" (in place of "models" or "projects") | Implies precision and specificity the data does not have |
| "shows" (without "model" or "scenario" qualifier) | Ambiguous — makes it sound like fact, not projection |
| "flood zone" | Implies regulatory or legal designation |
| "your home" / "your property" | The product assesses a point, not a legal property |
| "by [year], this area will..." | Implies certainty; use "under [scenario] by [year], the model shows..." |

---

## 10. Glossary of Terms in Product Copy

Use these definitions consistently. If a term appears in the UI, it should match these definitions.

| Term | Definition for UI Copy |
|---|---|
| **Scenario** | A pathway describing possible future greenhouse gas emissions and their associated sea-level projections. Different scenarios represent different possible futures, from lower to higher emissions. |
| **Time horizon** | A future year for which the projection is evaluated (e.g., 2050 means the model projection as of the year 2050). |
| **Modeled exposure** | The intersection of a location with a sea-level exposure zone derived from projection data and elevation data, under a specific scenario and time horizon. |
| **Coastal analysis zone** | The geographic area within which this tool evaluates coastal sea-level exposure. Locations outside this zone are shown as Out of Scope. |
| **Methodology version** | The labeled version of the technical approach used to produce results. Versioning ensures that result comparisons are meaningful and that changes to the methodology are tracked. |
| **Data Unavailable** | The system could not evaluate exposure for this location/scenario/horizon combination because required data is missing. This is distinct from a result of zero or no exposure. |
