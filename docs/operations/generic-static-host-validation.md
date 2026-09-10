# Generic static-host validation

The illustrative coastal atlas and retained projection reference are deployable
as files. Their fixture build is validated
with pinned `sirv-cli`, a generic static-file server, instead of Vite preview
or an application server. The validation never reads private Candidate-v7 or
TAR bytes and uses only the committed illustrative fixture and retained projection fixture copied by the
build. The real-local adapter is not part of this static-host gate.

## Reproduce the gates

Build the application with repository-pinned Node 20.20.1 and npm 11.12.1.
Run the isolated static-quality tools with Node 22.23.2 and npm 11.12.1:

```sh
npm ci
npm run web:build
npm ci --prefix tools/static-quality
npm run --prefix tools/static-quality install:chromium
node tools/static-quality/validate-generic-static-host.mjs
node tools/static-quality/run-lighthouse-gate.mjs
```

The build emits deterministic Brotli and gzip sidecars for application-shell
text assets. The release directory is excluded: release objects remain exactly
manifest-authorized, including canonical compressed artifacts declared by the
manifest, and no generated sidecar creates an extra release URL. The static-
host smoke verifies `/`, `/projections/`, `/about/architecture/`, the build identity,
release manifest, and every reported asset. Brotli delivery follows both named
initial entry graphs, with no sidecar required when compression would increase
a tiny asset. Private `/atlas-data` routes must return 404. Unknown paths and the legacy
`/assess`, `/geocode`, `/config`, `/v1/assess`, `/v1/geocode`, and `/v1/config`
application endpoints must return static 404 responses; neither unversioned nor
versioned assessment POST acquires dynamic handling. Every manifest-authorized
`config/*.json` asset is fetched from its release-scoped path and checked
against its byte size, SHA-256, release identity, and provenance.

`sirv-cli` is a validation-only generic static-file server. Lighthouse,
Chromium control, and `sirv-cli` are isolated beneath `tools/static-quality/`
with their own audited lock. They never enter the static application's root
lock or its production runtime, and are not a deployment dependency.

The Lighthouse gate uses Lighthouse 13.4.1 and Playwright 1.62.1 Chromium on
the Lighthouse mobile profile with simulated throttling. It runs three fresh
Chromium audits and preserves every raw report. Chromium uses explicit software
WebGL so the audit renders the actual map; a visible canvas with rendered geographic
features, settled tile counts, and no technical error is required in a separate
browser preflight. Each audit starts its own new browser without an application
preflight or shader-cache warming and rejects application errors in its console evidence. Performance, accessibility,
best practices, and SEO must each have a median raw score of at least 0.90;
the stricter guard also checks every individual raw score against 0.90. The
bounded local-adoption performance exception below retains these failed targets
in evidence instead of reporting them as passes. Reports
and the machine-readable run/median summary are written beneath the ignored
`src/web/test-results/lighthouse/` directory. The isolated
`.github/workflows/static-quality.yml` job runs the production build, generic
host validation, and Lighthouse gate from their exact v2 locks. The immutable
Phase 1 `ci.yml` and v1 dependency authority are not rewritten. This is a
Chromium-only Phase 2 gate and makes no Firefox or WebKit support claim.

The initial stylesheet is embedded into all three static documents to remove a
render-blocking request. The atlas uses system fonts. The two Latin fonts used by the retained Flight command
are preloaded from the same immutable hashed assets; this changes delivery
timing, not font selection or rendered styling. Scientific COG/runtime code is
loaded after the first application render rather than entering the initial
dependency graph. The tiny build-identity authority is deferred while retaining
document order ahead of the application module, and manifest validation starts
at browser idle so the retained Flight command can paint before verified release
startup begins. The
existing build inspector independently retains the 250 KiB Brotli budget and
lazy map/search checks.

The generic server chooses a free loopback port. Readiness uses the bound URL
announced by the owned `sirv-cli` process, so an existing preview on the requested
port cannot be mistaken for the build under test. No running preview is stopped.

## Expected result

The static smoke prints `generic static-host validation passed`. Lighthouse
prints all four category scores for each run and their median, then exits
non-zero if a raw run or median is below 0.90 without the exact temporary
performance exception below. A missing Chromium
installation, missing build output, unexpected
dynamic route, or failed audit is a blocking failure rather than a deferral.


## Temporary Atlas local-adoption performance exception

Owner: **artemsemdev**. Issues: [#490](https://github.com/artemsemdev/SeaRise-Europe/issues/490)
and [#65](https://github.com/artemsemdev/SeaRise-Europe/issues/65). Expires at
**2026-09-24 00:00 UTC**, with no automatic renewal.

[Linux run 34493541004](https://github.com/artemsemdev/SeaRise-Europe/actions/runs/34493541004)
measured raw performance **54 / 53 / 55**, median **54**, against target **90**;
accessibility was 96 and best practices/SEO 100 in every run. Cold MapLibre
startup dominates the new map-first route, replacing the earlier static landing
page. This measured engineering debt must not hold the accepted local product
outside reproducible development while performance work continues under #65.

The [checked policy](../../tools/static-quality/atlas-local-performance-waiver.json)
applies only to the visibly labeled Atlas `synthetic-fixture` edition with
synthetic release identity. Every cold run must score at least **50 performance**
and **90 in each other category**. Renderer errors remain fatal. The three raw
reports remain intact; the summary records `performance90Passed: false` and
`waiverApplied: true`, and CI emits the actual scores, owner, floor, and expiry.
Missing, malformed, extended, or expired policy fails closed. Fixing the debt
requires retiring this temporary policy through review; expiry is not a silent
return to unchecked operation.

This is local adoption only: it qualifies neither a public MVP nor a scientific
release and cannot apply to private-engineering or public-promoted identities.
[ADR-021](../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md#15-performance-budgets-and-architecture-fitness-functions)
and the [testing strategy](../architecture/10-testing-strategy.md#6-ci-stages)
require the measured regression, rationale, owner, and expiry in the PR. The
paragraphs above provide that disposition; no scientific authority is changed.
