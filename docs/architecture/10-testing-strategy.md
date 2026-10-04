# 10 — Testing Strategy

> **Status:** Executable verification scopes, reviewed 2026-10-04.
> The source of truth for suite ownership is
> [tests/test-inventory.json](../../tests/test-inventory.json).

## Verification boundaries

The atlas, projection reference, demo launcher and scientific build have
separate evidence scopes. A green authored fixture does not verify provisioned
CoCliCo files; a source hash or candidate seal does not approve scientific
publication. Historical tests/receipts retain their original scope.

| Layer | Source suites | What they establish |
|---|---|---|
| Atlas browser contracts/providers | `src/web/src/atlas/*.test.ts` | Closed shapes, edition isolation, deterministic fixture, HTTP failure/abort behavior |
| Atlas components | `src/web/src/atlas/*.test.tsx` | Search, inspection, URL state, controls, retry, sharing and disclosure with injected providers |
| Atlas local adapter | `src/web/scripts/real-local-atlas.test.mjs`, `atlas-edition.test.mjs` | Activation, path/integrity checks, explicit mode and lifecycle |
| Raster service | `src/pipeline/tests/atlas/` | Native-cell sampling, validity, tiles, HTTP behavior and bounded connection handling using synthetic inputs |
| Demo tooling | `scripts/demo/*.test.mjs` | Candidate byte/source identity, sealed preview, child shutdown and startup interruption |
| Atlas fixture browser | `src/web/tests/atlas-fixture.spec.ts` | Built fixture UI, map pixels, controls and network boundaries |
| Real-local browser | `src/web/tests/real-local/` | Provisioned local source journeys; manual, separately launched service |
| Projection domain/data/search | `src/web/src/{domain,data,search,application}/` | Four outcomes, exact lookup, manifest v2, correlation, Worker and technical failures |
| Projection storage/browser | `src/web/src/offline/`, remaining `src/web/tests/` | Integrity admission, range policies, lifecycle, map, URL and reference UX |
| Scientific/release pipeline | `src/pipeline/tests/` | Source acquisition, AR6 parity, artifacts, settlements, candidate and supply-chain contracts |
| Repository contracts | `tests/harness/`, `tests/repository-removal/` | Suite ownership, changed-path routing and completed removal authority |

Paths above are relative to the repository root. The
[testing guide](../testing/README.md) and inventory contain exact focused commands.

## Normal clean-clone frontend loop

From the repository root with the pinned Node/npm runtime:

```bash
npm ci
npm run web:check
npm exec --workspace @searise/web -- playwright install chromium
npm run web:e2e
npm run web:e2e:offline-lifecycle
```

`web:check` now includes demo lint and Node tests, followed by web lint, type
checking, Vitest and build checks. Web lint also checks source boundaries,
target content and generated contracts/fixtures. Playwright is a separate gate.

The [standard Playwright config](../../src/web/playwright.config.ts) runs desktop
and mobile Chromium, plus a reduced-motion project scoped to projection UX.
It excludes private, real-local and dedicated offline-lifecycle tests. AR6
journeys explicitly use `/projections/`; `/` is atlas. Firefox/WebKit evidence
from optional profiles must not be described as a required ordinary CI gate.

For a provisioned local atlas, start `npm run local:start` or the matching
built preview separately, then run `npm run local:e2e`. Its config disables
service workers and uses desktop/mobile/boundary Chromium projects. It does
not start or download the private data itself. See the
[atlas workflow](../operations/coastal-atlas-development.md).

## Contract and scientific checks

Atlas checks preserve positive depth, valid zero and unknown as distinct
values; inspect and display tile values come from the same provider's data.
HTTP failure, invalid bytes or cancellation cannot become a fabricated depth.
Tests exercise layer changes and stale completion, not just successful reads.

Projection checks preserve the exact 3 × 3 matrix, support-before-coastal
precedence, nearest native location with lowest-ID ties, inclusive 100 km
limit, exact integer quantiles and nodata. The shared independent AR6 goldens
and artifact tests bind source IDs and values across Python, TypeScript, COG,
GeoParquet and PMTiles. Synthetic browser-only controls remain explicitly
separate from real-source scientific evidence.

Projection offline tests reject partial responses in complete-resource Cache
Storage, reject PMTiles admission to all authoritative stores, and exercise
warm-cache success plus honest uncached failure. The dedicated lifecycle suite
covers natural update activation and retaining the active/previous pair.
Neither suite promises offline atlas data.

## Build, delivery and performance

The build inspects all three static routes, exact output inventory, generated
precache, CSP, lazy Worker/decoder boundaries and separate initial JS budgets.
The generic static-host harness checks paths, 404s, identity, media types and
release delivery independently of Vite preview. Sealed demo preview additionally
uses the manifest-allowlisted release middleware while atlas responses stay
`no-store`.

The [static-quality workflow](../../.github/workflows/static-quality.yml) uses
isolated tools under `tools/static-quality`, builds with the pinned app runtime,
then runs the quality tools with their own Node version. It audits three cold
atlas visits. Raw all-category 90+ results pass without a waiver. Lower
performance can use only the exact time-bounded private-local-demo policy;
other category failures or rendering errors are not waived. See
[15](15-performance-and-scalability.md) for the current exception and limits.

Automated axe, keyboard, focus and browser tests do not substitute for a manual
screen-reader, usability or scientific interpretation review before public
qualification. Test reports/screenshots are evidence of their exact profile,
not public release artifacts.

## CI and historical authority

[changed_components.py](../../scripts/ci/changed_components.py) selects CI jobs
from paths. Atlas Python changes route to web and pipeline checks; demo tooling
routes to web checks. The normal web job runs `web:check`, PMTiles render evidence,
browser journeys and offline lifecycle. Pipeline and controlled artifact jobs
have their own toolchains and input requirements.

Use `scripts/tests/validate_test_inventory.py` and
`scripts/tests/changed_suites.py` to validate ownership and select relevant
local checks. A documentation-only change need not rerun provisioned-source
journeys, and passing local checks is not a claim that remote CI ran.

The old service runtime has already been removed. Current development uses
[post-cutover validation](../../scripts/repository/validate_post_cutover.py):
local `--evidence-only` verifies pinned historical authority and removed-path
absence; CI `--verify-owner-comment` also checks live owner evidence. Do not
revive legacy-vs-target migration as an unfinished test phase.

AR6 Phase 0R approval and later controlled signing/readback evidence remain
separate from the coastal atlas. Public atlas source distribution and scientific
qualification require additional evidence under ADR-028; the
[demo prerelease record](../releases/v0.1.0-rc.1.md) makes that limitation explicit.
