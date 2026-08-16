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
in `src/web/tests/projection-ux.spec.ts`. That automation passed 45/45 tests
across desktop, Pixel 7 mobile, and reduced-motion Chromium, but it is not used
as a substitute for the unavailable human VoiceOver check.

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
