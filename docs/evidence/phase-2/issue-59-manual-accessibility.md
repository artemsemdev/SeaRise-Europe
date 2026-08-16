# Issue #59 manual accessibility evidence

> **Date:** 2026-08-16
>
> **Reviewed commit:** `2f835e195e706467991fab50f22c13ca08c050f5`
>
> **Application:** production static build served from `http://127.0.0.1:4173/`
>
> **Release:** committed synthetic fixture
> `searise-europe-v1.0.0-20260810-c096aeab4e09` served read-only from
> `http://127.0.0.1:8091/`
>
> **Environment:** macOS 26.5.2 (25F84), Google Chrome 151.0.7922.138

## Result

The browser-assisted keyboard and semantic-tree review passed on the exact
issue #59 coordination commit. The separate human VoiceOver narration review
did **not** run because macOS Computer Use denied access to both Google Chrome
and VoiceOver. This record therefore does not claim that the screen-reader
narration Definition of Done item is complete.

Automated Playwright keyboard, focus, reduced-motion, and axe evidence remains
in `src/web/tests/projection-ux.spec.ts` and `src/web/tests/static-shell.spec.ts`.
The current suite runs those checks across desktop, Pixel 7 mobile, and
reduced-motion Chromium, but it is not used as a substitute for the unavailable
human VoiceOver check. The exact pass count belongs in the validation log for
the commit under test rather than in this manual-review record.

The observations below are historical evidence for the reviewed commit named
above. They must not be read as a manual review of later focus or live-region
changes.

## Browser-assisted keyboard review

| Journey | Observation | Result |
|---|---|---|
| Initial semantics | Chrome exposed one H1, landmark regions, labelled search, status regions, release disposition, projection actions, and a textual non-map journey. | Pass |
| Skip link | The first Tab focused `Skip to content`; Enter set `#main`; the next Tab reached the settlement combobox rather than header navigation. | Pass |
| Combobox | Typing `Málaga` expanded the combobox, announced `1 settlement found`, exposed one selected listbox option, and retained focus in the combobox. | Pass |
| Keyboard selection | Enter selected Málaga and produced `ProjectionAvailable` through the production geography/COG chain. | Pass |
| Outcome announcement | The accepted article exposed `Scientific outcome updated: ProjectionAvailable.` as a status message. | Pass |
| Complete scientific text | Chrome exposed SSP2-4.5, 2050, median 0.194 m, q0.167–q0.833 range 0.055–0.343 m, 1995–2014 baseline, source 37/-4, 48.641 km, native 1°, method and release IDs, attribution, limitations, map meaning, and disclaimer. | Pass |
| Radio keyboard control | ArrowRight on the checked scenario selected SSP5-8.5 while retaining 2050 and updated the accepted result to 0.230 m with range 0.142–0.334 m. | Pass |
| Methodology dialog | Enter on `Methodology and sources` opened the labelled dialog and focused `Close methodology`. | Pass |
| Dialog content | The semantic tree exposed the three quantile bands, nearest native 1° lookup, inclusive 100 km limit, exactly four scientific outcomes, PMTiles-as-visual-only statement, provenance links, product exclusions, and release disposition. | Pass |
| Focus restoration | Escape closed the dialog and restored focus to `Methodology and sources`. | Pass |

No Candidate-v7, TAR, ignored local-data path, external service, application
API, or public storage was used.

## Follow-up automated accessibility coverage

The focused follow-up commit that contains this section adds production-build
browser assertions for behaviors that could not be rechecked manually in the
blocked macOS session:

- the complete initial tab sequence is skip link, home link, methodology
  button, then settlement search;
- idle map legend, attribution, visual-band controls, and MapLibre controls are
  absent from the tab order and accessibility tree;
- selecting a search result moves focus to the lookup transition, then to the
  accepted outcome heading; reset returns focus to settlement search;
- one authoritative polite assessment live region reports evaluation, accepted
  outcome, share, and technical-operation state, while a distinct search live
  region announces only the current local result status without duplicating the
  assessment announcement;
- after the first selected-place transition, technical, integrity, offline, and
  connection-required failures move focus to the visible failure alert instead
  of dropping focus to the document body;
- scenario or horizon changes at the same location retain the accepted result
  atomically without camera flight or "Flying" copy;
- delayed superseded Worker search responses cannot replace the newest query;
- every completed outcome visibly includes the full product-boundary caveat.
- desktop and 390 px mobile controls retain a single segmented row, while the
  mobile hero/header geometry and idle map chrome remain aligned with Flight;
  the 320 px layout has no horizontal overflow.

These are automated assertions, not a human VoiceOver pass. The pending
human-only gate below remains open and unchanged.

On 2026-08-16, the production static build passed the complete Playwright
suite with the permanent single-worker timing isolation: `57 passed` across
desktop Chromium, Pixel 7 mobile Chromium, and reduced-motion Chromium. The
same follow-up also passed lint, type-check, 303 unit/integration tests, the
production build, target-content checks, and fixture/contract checks through
`npm run web:check`.

## Pending human-only gate

Before a public launch, a person with macOS VoiceOver access must repeat the
core journey and record the observed narration for:

1. initial page landmarks and skip link;
2. combobox query, result count, active option, and selection;
3. each of the four ADR-024 outcome announcements;
4. scenario/horizon changes while a previous accepted result is visible;
5. integrity, offline, connection-required, and general technical failures;
6. methodology dialog entry, reading order, focus trap, Escape, and focus
   restoration;
7. map opening and the equivalent textual meaning without relying on colour.

The reviewer must record their name or role, date, macOS, VoiceOver, and Chrome
versions plus any defects. Do not convert the current blocked result into a
pass without that observation.

## Reproduction

From a clean checkout of the reviewed commit:

```bash
npm ci
npm run web:build
npm run serve:committed-release --workspace @searise/web
npm run web:serve
```

Open `http://127.0.0.1:4173/` in Chrome. The two servers are static/read-only
test infrastructure; no Node application server is part of the product.
