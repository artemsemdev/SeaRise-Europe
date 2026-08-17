# Generic static-host validation

Phase 2 is deployable as files. Its production build is therefore validated
with pinned `sirv-cli`, a generic static-file server, instead of Vite preview
or an application server. The validation never reads private Candidate-v7 or
TAR bytes and uses only the committed synthetic fixture copied by the build.

## Reproduce the gates

Use the repository-pinned Node 20.20.1 and npm 11.12.1 versions:

```sh
npm ci
npx playwright install chromium
npm run web:build
npm run web:validate:static-host
npm run web:validate:lighthouse
```

The build emits deterministic Brotli and gzip sidecars for text assets. The
static-host smoke verifies `/`, `/about/architecture/`, the build identity,
release manifest, and every reported asset. Unknown paths and the legacy
`/assess`, `/geocode`, `/config`, `/v1/assess`, `/v1/geocode`, and `/v1/config`
application endpoints must return static 404 responses; neither unversioned nor
versioned assessment POST acquires dynamic handling. Every manifest-authorized
`config/*.json` asset is fetched from its release-scoped path and checked
against its byte size, SHA-256, release identity, and provenance.

`sirv-cli` is a validation-only generic static-file server. It is a pinned
development dependency for CI portability evidence, never a production Node
application-server or deployment runtime dependency.

The Lighthouse gate uses Lighthouse 12.8.2 and Playwright 1.62.1 Chromium on
the Lighthouse mobile profile with simulated throttling. Performance,
accessibility, best practices, and SEO must each score at least 90. Its JSON
report and summary are written beneath the ignored
`src/web/test-results/lighthouse/` directory and retained by a dedicated CI
artifact before Playwright owns its output directory. This is a Chromium-only
Phase 2 gate and makes no Firefox or WebKit support claim.

The initial stylesheet is embedded into both static documents to remove a
render-blocking request. Scientific COG/runtime code is loaded after the first
application render rather than entering the initial dependency graph. The
existing build inspector independently retains the 250 KiB Brotli budget and
lazy map/search checks.

## Expected result

The static smoke prints `generic static-host validation passed`. Lighthouse
prints all four integer category scores and exits non-zero if any score is
below 90. A missing Chromium installation, missing build output, unexpected
dynamic route, or failed audit is a blocking failure rather than a deferral.
