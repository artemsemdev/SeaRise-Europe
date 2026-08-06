# SeaRise Flight Mock — Scope Reconciliation Map

> **Status:** Active implementation guide
>
> **Canonical mock:** [SeaRise-Flight.html](SeaRise-Flight.html)
>
> **Replaces:** the deleted `pages/` mock set and legacy preview images
>
> **Behaviour authority:** [PRD](../PRD.md)
>
> **Architecture authority:** [ADR-021](../../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)
>
> **Copy authority:** [Content guidelines](../CONTENT_GUIDELINES.md)

## Authority and intended use

`SeaRise-Flight.html` is the canonical visual and interaction reference for the
new static browser experience. It demonstrates the landing composition, local
settlement search, flight transition, scenario/horizon controls, release-scoped
result, methodology disclosure, attribution, and technical/offline edge cases in
one self-contained artifact.

It remains a design mock. When its fixture values, timing, copy, state coverage,
or implementation detail conflicts with the PRD, content guidelines, methodology,
release contracts, accessibility requirements, or ADR-021, those authoritative
documents win.

## Mock inventory

| Mock surface | Preserve | Implementation correction or constraint |
|---|---|---|
| Editorial landing | Destination-led hierarchy, restrained terrain scene, immediate search | Render useful semantic HTML before map/search modules; do not require animation to understand the product |
| Settlement combobox | Local-search framing, duplicate-name context, keyboard-active candidate, privacy note | Search all supported European settlements needed by the PRD; fixture count comes from the release, not source code |
| `Fly there` journey | Memorable transition from selection to result | Respect reduced motion, support skip/direct completion, and never delay a ready result to finish animation |
| Result panel | Strong textual hierarchy, synchronized marker/legend/controls, visible caveat | Result is produced by exact COG lookup; map animation and colour remain visual context only |
| Scenario controls | Three SSP pathways with one selected value | IDs/defaults come from validated release contracts and use semantic radio-group behaviour |
| Horizon controls | `2030`, `2050`, `2100` absolute years | No relative-year alternatives or fallback to another horizon |
| Limitations disclosure | Progressive detail, release and artifact identity, clear limitations | Add exact source/licence/STAC/checksum/provenance links from the pinned release |
| Methodology dialog | Four-stage processing narrative and evidence summary | Focus trap/return focus, link integrity, content authority, and responsive layout require implementation tests |
| Incomplete artifact demo | Correctly separates a range/checksum failure from `DataUnavailable` | Error details shown to users must be safe, actionable, and produced from typed technical failures |
| Partly cached offline demo | Capability-specific offline messaging and cached attribution | Never claim broad offline availability; determine capability from actual cached resources |
| Synthetic status | Prominent illustrative-release notice | Remains mandatory until scientific and rights gates approve a real release |

## GitHub scope mapping

| Work item | Mock responsibility | Required implementation evidence |
|---|---|---|
| [#54](https://github.com/artemsemdev/SeaRise-Europe/issues/54) | Static shell, landing composition, responsive layout, bundled fonts, methodology route entry | Static build, direct navigation, no server runtime, initial bundle report, desktop/mobile screenshots |
| [#55](https://github.com/artemsemdev/SeaRise-Europe/issues/55) | Release badge, scenario/horizon/release metadata, startup and invalid-release presentation | Schema validation, release isolation, safe URL resolution, exhaustive bootstrap errors |
| [#56](https://github.com/artemsemdev/SeaRise-Europe/issues/56) | Settlement combobox, duplicate names, local/privacy note, candidate status | Worker protocol, accessible combobox, ranking fixtures, performance and zero-query-leak trace |
| [#57](https://github.com/artemsemdev/SeaRise-Europe/issues/57) | Terrain/map scene, marker, overlay, legend, attribution, graceful context degradation | PMTiles range trace, atomic overlay swap, basemap failure, reduced motion, non-map equivalent |
| [#58](https://github.com/artemsemdev/SeaRise-Europe/issues/58) | Exact result explanation, AR6 values, source-grid and artifact identity, incomplete-range failure | Shared Python/TypeScript goldens, exact nearest-grid COG lookup, abort/range/corruption tests |
| [#59](https://github.com/artemsemdev/SeaRise-Europe/issues/59) | Atomic result panel, four domain states, controls, transient/technical separation | State-machine tests, approved copy, all four outcomes, accessibility and stale-work tests |
| [#60](https://github.com/artemsemdev/SeaRise-Europe/issues/60) | Partly cached/offline presentation and safe update concepts | Release-scoped cache tests, actual capability inventory, mixed-release prevention, quota/eviction tests |
| [#63](https://github.com/artemsemdev/SeaRise-Europe/issues/63) | Privacy statement, inert release metadata, public attribution | CSP/CORS, XSS fixtures, no-secret build, no project-controlled query/coordinate transmission |
| [#65](https://github.com/artemsemdev/SeaRise-Europe/issues/65) | Browser journey and visual state reference | Cross-browser E2E, screenshot/a11y evidence, performance budgets, zero legacy API calls |
| [#66](https://github.com/artemsemdev/SeaRise-Europe/issues/66) | Visual language to extend into `/about/architecture` | Separate architecture evidence page; targets and measured outcomes must remain distinct |
| [#73](https://github.com/artemsemdev/SeaRise-Europe/issues/73) | Interaction/state coverage used to drive frontend TDD | Characterization matrix, red-green-refactor evidence, permanent scientific/contract tests |

## Domain-state coverage

| Domain outcome | Mock coverage | Production requirement |
|---|---|---|
| `ProjectionAvailable` | The mock's two binary cards are obsolete | Replace them with median + likely range, scenario/horizon/baseline, source distance/resolution, limitations, and a non-colour cue |
| `DataUnavailable` | Present in the interactive fixture data | Keep distinct from missing network/cache/range data; never substitute another combination |
| `OutOfScope` | Present in the interactive fixture data | Explain the release-scoped coastal boundary; do not imply absence of climate risk |
| `UnsupportedGeography` | **Not represented as a named state in the export** | Add before #59 can close and cover outside-versioned-Europe support semantics |

The mock also demonstrates an incomplete-artifact technical failure. This is not
a fifth scientific state and must not be stored as `DataUnavailable`.

## Known corrections before implementation

1. The landing phrase `European coastal settlement` is visually useful but too
   narrow for a catalogue that must also demonstrate inland `OutOfScope` entries.
   Use the PRD-approved European-settlement wording.
2. `84,912 settlements` is fixture evidence. Production displays a count only
   when it comes from the validated pinned release.
3. `about fifteen seconds` is prototype narrative, not a latency target. Do not
   add an artificial wait; use measured progress and the performance budgets in
   #65.
4. Fixture release `2026-07-24-r3`, app commit, artifact path, checksums, distance,
   population, and classifications are illustrative and must not become constants.
5. The cinematic scene is not a substitute for MapLibre/PMTiles rendering or
   exact COG assessment.
6. The export does not include the required `/about/architecture` evidence page.
   Its visual extension is owned by #66.
7. The export requires JavaScript. The implemented app still needs meaningful
   initial HTML, direct-route fallback, failure text, and a no-JavaScript message.

## Visual acceptance checklist

- [ ] The implementation is visibly derived from the Flight mock without copying
  fixture values as product facts.
- [ ] Exactly three scenarios and three absolute horizons are present.
- [ ] Search is local, settlement-only, duplicate-aware, and keyboard operable.
- [ ] All four domain states plus technical and offline failures are designed and
  tested.
- [ ] Scenario, horizon, methodology, release, limitations, and attribution remain
  synchronized with the accepted selection.
- [ ] Result meaning survives map, animation, basemap, colour, and motion loss.
- [ ] Reduced-motion users reach the result without the cinematic delay.
- [ ] Mobile prioritizes search and textual result over the map canvas.
- [ ] Synthetic/provisional status remains explicit until approved evidence exists.
- [ ] Final screenshots are captured from the implemented static frontend and link
  back to the relevant work items above.

## Artifact integrity

The imported mock is intentionally self-contained so reviewers can open it
without a build step. Its SHA-256 at import is:

```text
e9f72148a9c9661b86d483043a0d661f8f7c4bb4938600ac1a41394320698aa7
```

If the HTML export changes, update this digest and review the reconciliation map
in the same pull request.
