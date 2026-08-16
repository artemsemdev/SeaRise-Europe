# Design Direction: The Flight Experience

> **Status:** Historical visual direction retained for audit
>
> **Historical interactive export:** [SeaRise Flight](SeaRise-Flight.html)
>
> **Behaviour authority:** [PRD](../PRD.md)
>
> **Copy authority:** [Content guidelines](../CONTENT_GUIDELINES.md)
>
> **Architecture authority:** [ADR-021](../../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)

The self-contained `SeaRise-Flight.html` export preserves the earlier visual
direction. It is historical evidence, not application code, product copy, a
scientific contract, a rollback baseline, or an implementation source. Its
binary exposure and terrain-comparison behavior is superseded by ADR-024. The
implemented static frontend and the authorities above define current behavior.

## 1. Creative north star

**The Flight Experience** turns an abstract geospatial lookup into a deliberate
journey from place selection to a transparent, release-scoped result. The user
starts with an editorial prompt, selects a European settlement from a local
catalogue, travels through a stylised cartographic scene, and lands on a precise
result panel that remains readable without the map.

The experience should feel:

- calm rather than alarming;
- editorial rather than dashboard-like;
- cinematic without hiding system state;
- scientifically cautious rather than predictive;
- technically sophisticated without exposing infrastructure jargon by default.

The flight animation is visual context only. Exact assessment continues to come
from the classified analysis artifact declared by the active immutable release.

## 2. Canonical composition

### Landing

- Atlantic-toned full-viewport scene with a restrained graticule.
- `SeaRise Europe` wordmark and an explicit synthetic/illustrative status.
- Large editorial `Take me there.` heading.
- One dominant settlement combobox and `Fly there` action.
- Immediate privacy and scope explanation: settlements only and local search.
- Methodology remains available without blocking the primary journey.

### Flight

- Camera movement preserves a sense of geographic transition.
- Location and model-stage announcements have accessible text equivalents.
- The animation must respect `prefers-reduced-motion` and offer a direct path to
  the completed result.
- Animation duration is not a performance contract. Production copy must use
  measured behaviour and must not promise a fixed wait time.

### Result

- A light, high-contrast result panel sits above the geographic scene.
- Result heading, settlement context, scenario, absolute horizon, limitations,
  methodology, release identity, and disclaimer form one coherent hierarchy.
- Scenario and horizon controls remain visible and update the result, overlay,
  legend, URL, and release-scoped selection atomically.
- The result remains understandable when the basemap is absent.
- Legend and attribution stay visible on wide layouts; narrow layouts must retain
  equivalent textual meaning.

## 3. Visual language

### Palette

- Deep Atlantic blue establishes the environmental context.
- Off-white terrain and panels create editorial contrast.
- Teal supports neutral interactive emphasis and selected locations.
- Teal and blue may encode the visual projection scale, but colour must not
  imply a flood threshold or replace the numeric median and likely range.
- Available projection styling must always be paired with language that rejects
  flooding, exposure, property-risk, and safety interpretations.
- Neutral grey communicates missing data and technical uncertainty.
- Violet may distinguish scope boundaries without implying hazard severity.

### Typography

- **Instrument Serif** provides editorial display moments and the destination-led
  identity.
- **Instrument Sans** carries navigation, explanations, controls, and results.
- **Geist Mono** carries release IDs, scenarios, years, artifact paths, checksums,
  and other technical evidence.

Typography must remain bundled or self-hosted in the implemented static app.

### Geometry and depth

- Layered terrain silhouettes replace a conventional dashboard grid.
- Rounded search and result surfaces should feel physical but restrained.
- Dense glassmorphism is not the base system; translucency is reserved for map
  context, compact metadata, and attribution.
- Shadows support hierarchy only and must not reduce text contrast.

## 4. Core interaction patterns

### Local settlement search

- Accessible combobox/listbox with country and first-level administration.
- Duplicate names remain distinguishable.
- Coastal and inland catalogue context may be shown without filtering away valid
  `OutOfScope` demonstrations.
- Search-index failure is not the same as no matches.
- Search text never leaves the browser in the target architecture.

### Scenario and horizon controls

- Exactly `SSP1-2.6`, `SSP2-4.5`, and `SSP5-8.5`.
- Exactly `2030`, `2050`, and `2100`.
- Default is `SSP2-4.5` / `2050`.
- Controls use semantic radio-group behaviour and visible keyboard focus.

### Result states

The production UI must cover all four domain outcomes:

1. `ProjectionAvailable`
2. `DataUnavailable`
3. `OutOfScope`
4. `UnsupportedGeography`

Technical artifact, range, integrity, manifest, browser, and offline failures are
separate presentations and must never be converted into a scientific result.

### Methodology and release evidence

- Progressive disclosure keeps the primary result concise.
- Expanded content identifies methodology version, `dataReleaseId`, AR6 median
  and likely range, selected source-grid identity and distance, lookup method,
  artifact, source status, limitations, and disclaimer.
- The dedicated methodology surface adds exact sources, licences, processing
  steps, STAC, checksums, and provenance.

## 5. Accessibility and motion

- WCAG 2.2 AA is the minimum target.
- Search, scenario, horizon, result, methodology, replay, reset, and edge-case
  controls must be keyboard operable.
- Flight and modeled-scene changes require live-region announcements that do not
  overwhelm assistive-technology users.
- Focus must enter and return from methodology dialogs predictably.
- Result meaning cannot depend on colour, animation, map visibility, or the
  position of a marker.
- Reduced-motion mode must collapse cinematic transitions without delaying the
  result.
- Narrow layouts prioritize search and textual results over the map canvas.

## 6. Implementation guardrails

- Do not copy mock fixture counts, release IDs, app commits, artifact paths, or
  timings as production constants; read them from validated release/evidence
  contracts.
- Replace `European coastal settlement` with the PRD-approved European settlement
  scope when inland catalogue entries are needed for `OutOfScope`.
- Do not implement a fixed fifteen-second wait. Cached exact assessment has a
  sub-100 ms p95 target after required resources are available.
- Preserve the explicit synthetic/illustrative label until the scientific release
  gate passes.
- Do not sample animation or PMTiles colour for scientific assessment.
- Do not introduce a runtime geocoder, assessment API, database, or tile server to
  reproduce the prototype.
- `/about/architecture` is a separate static route and remains required even
  though it is not included in this interactive export.

See [the mock-to-scope map](MOCK_REQUIREMENTS_MAP.md) for implementation issue
links, accepted concepts, corrections, and missing design states.
