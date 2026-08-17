# Generic static-host validation

Phase 2 is deployable as files. Its production build is therefore validated
with pinned `sirv-cli`, a generic static-file server, instead of Vite preview
or an application server. The validation never reads private Candidate-v7 or
TAR bytes and uses only the committed synthetic fixture copied by the build.

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
host smoke verifies `/`, `/about/architecture/`, the build identity,
release manifest, and every reported asset. Unknown paths and the legacy
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
Chromium audits and preserves every raw report. Performance, accessibility,
best practices, and SEO must each have a median raw score of at least 0.90;
the stricter guard also rejects any individual raw score below 0.90. Reports
and the machine-readable run/median summary are written beneath the ignored
`src/web/test-results/lighthouse/` directory. The Phase 2 v2 supply-chain
profile must own this isolated toolchain before the gate is wired into CI; the
immutable Phase 1 v1 dependency authority is not rewritten. This is a
Chromium-only Phase 2 gate and makes no Firefox or WebKit support claim.

The initial stylesheet is embedded into both static documents to remove a
render-blocking request. The two Latin fonts used by the initial Flight command
are preloaded from the same immutable hashed assets; this changes delivery
timing, not font selection or rendered styling. Scientific COG/runtime code is
loaded after the first application render rather than entering the initial
dependency graph. The tiny build-identity authority is deferred while retaining
document order ahead of the application module, and manifest validation starts
at browser idle so the complete Flight command can paint before verified release
startup begins. The
existing build inspector independently retains the 250 KiB Brotli budget and
lazy map/search checks.

## Expected result

The static smoke prints `generic static-host validation passed`. Lighthouse
prints all four category scores for each run and their median, then exits
non-zero if any raw run or median is below 0.90. A missing Chromium
installation, missing build output, unexpected
dynamic route, or failed audit is a blocking failure rather than a deferral.
