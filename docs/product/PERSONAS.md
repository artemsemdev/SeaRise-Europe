# SeaRise Europe — User Personas

> **Owner:** Artem Sem
>
> **Status:** Active hypotheses; primary research pending
>
> **Version:** 1.0
>
> **Last updated:** 2026-08-04

These personas guide product decisions but are not research findings. Validate
them with representative users before making material audience-specific
investments.

## Persona map

| ID | Persona | Role in product decisions | Primary need |
|---|---|---|---|
| P-01 | Marina, climate-aware place researcher | Primary | Understand a European place without mistaking a model for a property forecast |
| P-02 | Tobias, educator and science communicator | Secondary | Explain scenarios, sources, and uncertainty in a reliable live demonstration |
| P-03 | Yuki, portfolio and technical reviewer | Secondary | Assess product judgement, data integrity, and architecture quickly |

## P-01 — Marina, climate-aware place researcher

### Context

Marina is comparing coastal cities and neighbourhoods for personal research.
She follows climate reporting but does not use GIS tools. She begins with a
city or village name, not a scientific dataset, and may later refine the point
on the map. She understands that SeaRise Europe is an exploratory first pass,
not professional advice.

### Goals

- Find the intended settlement despite diacritics, aliases, or duplicate names.
- Compare lower-, intermediate-, and higher-emissions scenarios at 2030, 2050,
  and 2100.
- Distinguish modeled exposure, no modeled exposure, missing data, inland
  scope, and unsupported geography.
- See what data and assumptions produced the result.
- Know what additional professional or local evidence would still be needed.

### Frustrations and risks

- A precise marker can look more accurate than the underlying raster.
- “No exposure” can be misread as a safety guarantee.
- Provider names used as scenario labels can obscure the actual SSP pathway.
- A slow or fragile backend undermines confidence even when the data is valid.
- Exact address language creates expectations the settlement catalog cannot
  meet.

### Product implications

- Search copy says city, town, village, or place—not guaranteed street address.
- Country and first-level administration disambiguate results.
- Results always show scenario, horizon, methodology, and release.
- Conservative language and resolution notes stay visible.
- Local search and assessment should feel immediate after required data loads.

## P-02 — Tobias, educator and science communicator

### Context

Tobias uses a laptop and projector in classrooms or presentations. He needs a
stable route to familiar coastal and inland examples, clear scenario
comparisons, and enough methodology detail to answer “how do we know?” He may
need the experience to continue after an intermittent network connection.

### Goals

- Prepare and repeat a demonstration against a pinned data release.
- Explain why the three scenarios are possible pathways, not forecasts.
- Show why `DataUnavailable` differs from
  `NoModeledExposureDetected`.
- Cite source snapshots, licences, and methodology.
- Use a cached demo without depending on backend warm-up.

### Frustrations and risks

- A product that changes data silently between sessions.
- Hidden methodology or vague source labels.
- Dramatic visuals with no textual interpretation.
- An “offline” claim that fails because the selected layer was never cached.

### Product implications

- Shareable URLs pin location, scenario, horizon, and release.
- Methodology and attribution are presentation-readable and printable.
- Offline indicators describe actual cached availability.
- Basemap degradation does not remove the textual assessment.
- Every visual state has a text equivalent and works from the keyboard.

## P-03 — Yuki, portfolio and technical reviewer

### Context

Yuki has a few minutes for a live demo and repository review. She is testing
whether the creator can match architecture to product needs, make scientific
limits explicit, and support claims with evidence. She is likely to inspect an
edge case, network behaviour, release metadata, and the difference between
planned and implemented work.

### Goals

- Understand the product value and limits in the first two minutes.
- See real, attributed data rather than an unlabeled synthetic demo.
- Understand why the production path needs no backend, database, or tile
  server.
- Inspect measurable performance, quality gates, artifact contracts, and
  provenance.
- Confirm that cost and portability claims are honest.

### Frustrations and risks

- Infrastructure that exists mainly to appear sophisticated.
- Architecture diagrams that do not match runtime network traffic.
- A polished UI that hides synthetic data or unpassed scientific gates.
- Unsupported claims such as “all villages,” “offline,” or “free forever.”
- Stale documentation that describes services no longer in the target design.

### Product implications

- `/about/architecture` leads with user and operational outcomes, then shows
  the technology and trade-offs.
- The page exposes the data release, code revision, artifact sizes, checks,
  STAC catalog, and signed provenance.
- Browser tests prove there are no `/assess`, `/geocode`, or `/config` calls.
- Demo fixtures include all five domain states and basemap/network degradation.
- Migration status is explicit until real data and parity gates pass.

## Comparison

| Dimension | Marina | Tobias | Yuki |
|---|---|---|---|
| Main question | “What does the model show for this place?” | “Can I explain and repeat this honestly?” | “Is this product and architecture credible?” |
| Methodology depth | On demand | High | High, including implementation evidence |
| Primary device | Mobile or desktop | Laptop/projector | Desktop plus repository |
| Critical failure | Misleading certainty | Unstable or uncitable result | Unverified claims or needless complexity |
| Offline value | Useful on return visits | Important for live demos | Evidence of resilient design |

## Validation plan

| Hypothesis | Method | Minimum evidence |
|---|---|---|
| Non-specialists can find a settlement and interpret a result | Five moderated task sessions across coastal and inland examples | At least 90% task completion; observed language problems recorded |
| Users distinguish all five states | Screenshot/card comprehension test | At least 80% correctly explain each state and its limits |
| Three scenarios and three years are understandable | Think-aloud comparison task | Users identify scenario and horizon without provider-name shortcuts |
| Offline wording is honest | Network-toggle usability test | Users can tell cached availability from unavailable content |
| Portfolio story is legible | Three technical-review walkthroughs | Reviewer identifies value, static-first trade-off, limits, and evidence within three minutes |

Research notes should update the hypotheses in this file; they must not contain
raw addresses, exact coordinates, or unnecessary personal data.
