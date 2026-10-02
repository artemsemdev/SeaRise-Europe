# Cold Atlas startup investigation

Date: 2026-10-02. Scope: release-candidate issue
[#519](https://github.com/artemsemdev/SeaRise-Europe/issues/519), under
[#518](https://github.com/artemsemdev/SeaRise-Europe/issues/518).

## Reproduction

Build the committed illustrative edition with Node 20.20.1 and npm 11.12.1.
Run `node tools/static-quality/run-lighthouse-gate.mjs` with Node 22.23.2 and
its separately locked dependencies. The tool launches three fresh Playwright
1.62.1 Chromium 151 browsers, mobile 412 × 823 at device density 2.625,
simulated throttling, and explicit SwiftShader software WebGL. Its separate
preflight requires a rendered map, settled tile counts, and no technical error.
Neither shaders nor application pages are warmed in the three audit browsers.

These measurements are from a local Apple Silicon computer. Linux CI is the
independent acceptance authority; local raw scores are not substituted for it.
The edition is visibly synthetic and these audits make no CoCliCo data or
scientific qualification claim. Raw reports were preserved in the ignored
`src/web/test-results/lighthouse/` output before each subsequent measurement.

## Measured bottleneck

An exploratory Chrome 154 trace, before installing the pinned browser, showed
synchronous GPU work rather than JavaScript parsing dominating startup. The
mount effect blocked for 1,513 ms, a rendering frame for 526 ms, and subsequent
frames for 213 and 203 ms. GPU tasks totaled 3.10 seconds; JavaScript module
parsing and compilation took roughly 9 ms. This exploratory trace informed the
optimization and is not acceptance evidence.

The change gives the controls a paint opportunity before loading the map and
bounds the map canvas density at 1.5 on high-density displays. The map starts
on the immediately following frame. CSS layout and DOM text retain the screen's
normal density; raster request coordinates, native scientific cell sampling,
pixel counts, and nearest-neighbor flood rendering remain unchanged. The lower
canvas density trades some map edge sharpness for less allocation and rendering
work, while low-density screens retain their existing density.

## Exact pinned local comparison

| Three cold audits | Before | Canvas cap only | Combined change |
| --- | --- | --- | --- |
| Raw performance | 43 / 44 / 44 | 53 / 45 / 46 | 51 / 53 / 52 |
| Accessibility, best practices, SEO | 100 each run | 100 each run | 100 each run |
| Median simulated first contentful paint | 2,649 ms | 2,650 ms | 2,638 ms |
| Median simulated largest contentful paint | 5,133 ms | 5,082 ms | 4,117 ms |
| Median simulated speed index | 5,011 ms | 4,051 ms | 3,848 ms |
| Median simulated total blocking time | 3,478 ms | 2,775 ms | 2,920 ms |
| Median observed first contentful paint | 1,437 ms | 669 ms | 625 ms |

Observed paint times are from the browser trace before Lighthouse simulates
mobile throttling. The canvas-only experiment isolates one part of the change;
the combined change improves largest paint and narrows the raw score range in
this three-run sample. These small samples do not establish a variance bound.

The rendered-map preflight passed for the baseline and optimized fixture builds.
Raw performance still misses the unchanged 90-point target in every run.
The expired historical waiver rejects these audits. This improvement does not
close the public performance gate or qualify a public MVP release.

## Fresh Linux CI

[Static-quality run 36998471253](https://github.com/artemsemdev/SeaRise-Europe/actions/runs/36998471253)
audited source revision `771baac16d87b5cb27adf1b66e9d841ba10574d1` with the same
locked Chromium 151 mobile software-render profile on Linux x86-64. Raw
performance was **54 / 56 / 54**; accessibility, best practices, and SEO were
**100 in every run**. Production build, generic static-host validation, and the
rendered-map preflight passed. The job rejected the expired historical waiver.
The independent raw 90-point target remains unmet.

[Raw three-run artifact](https://github.com/artemsemdev/SeaRise-Europe/actions/runs/36998471253/artifacts/11222787404)
contains the complete reports and has the workflow's 14-day retention. This
failed audit is evidence of remaining debt, not a passed public release gate.

## Owner-approved local demo exception

On 2026-10-02 the owner explicitly approved keeping the current performance for
the private local demonstration. This approval is recorded from the owner
conversation, with no external or scientific signoff claimed. A separate
[local-demo policy](../../../tools/static-quality/atlas-local-demo-performance-waiver.json)
uses the Linux evidence above and issues #518/#519. It permits only labeled
synthetic fixture software evidence, requires 50 in every cold performance run
and 90 in every other category, and expires at the start of 16 October in Berlin,
`2026-10-16T00:00:00+02:00`. Render health and raw errors remain blocking.
The historical September policy is preserved unchanged. CI acceptance under
the new exception still reports `performance90Passed: false`, retains the raw
90-point failures, and does not qualify private data, a scientific release,
public promotion or an MVP release. Fresh CI remains required for the new head.

## Verification

The independent Lighthouse evaluator regression failed three tests before its
fix and passes all 16 historical/raw policy cases afterward. Six additional
local-demo cases enforce the owner scope, raw floors, other categories, exact
Berlin expiry boundary, renderer errors and release identities. It accepts raw 90-point passes
without consuming a waiver, and still rejects expired exceptions, render
errors, incomplete audits, and any attempt to broaden the historical policy.

The Atlas unit suite awaits both the catalogue and map mount, exercising city
selection, selected-point inspection, defense/year changes, shared views,
comparison, and errors with the existing injected data-source contract. The
fixture browser journeys retain their real rendered-map checks, representative
year/defense transitions, and selected-view screenshots. The existing fixture
unit suite checks all six configured year/defense combinations. No timing-only assertion is
used as a replacement for render health.
