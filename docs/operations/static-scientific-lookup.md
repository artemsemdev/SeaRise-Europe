# Static scientific lookup runbook

This runbook validates the Phase 2 browser-side AR6 regional projection lookup.
The normal workflow is deterministic, network-free, and uses only the committed
synthetic release fixture. It does not discover or read private candidate data.

## Runtime contract

One immutable `ReleaseContext` supplies all runtime identities. The browser:

1. resolves exactly one support geometry and one coastal-analysis geometry;
2. verifies each small geometry artifact by byte size and SHA-256 before
   decoding its CRS84 `MultiPolygon` rows;
3. classifies support first and coastal scope second with boundary-inclusive
   point coverage;
4. verifies and decodes the release's `source-grid-identity` artifact instead
   of deriving source IDs in browser code;
5. verifies the small `cog-range-integrity` artifact and binds every COG to its
   manifest path, byte size, whole-object SHA-256, and canonical 64 KiB chunk
   SHA-256 identities;
6. requires an exact `HEAD` identity followed only by `206` byte ranges,
   expands each requested slice to complete verified chunks, and never accepts
   an unverified range or a full-file `200` substitution;
7. validates the COG's embedded scenario, horizon, source archive/member,
   source release, method, baseline, units, scale, native resolution, and exact
   q0.167/q0.5/q0.833 band descriptions before reading one nearest source pixel;
8. applies the Haversine distance using the 6,371.0088 km mean Earth radius,
   lowest-location-ID tie break, and inclusive unrounded 100 km limit; and
9. returns exactly `ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, or
   `UnsupportedGeography`.

Manifest, integrity, transport, decode, range-support, coordinate-validation,
release-identity, and cancellation failures remain technical failures. They are
never converted into a scientific outcome. PMTiles supplies only the matching
visual identity and never supplies analysis values.

## Browser-overlay evidence boundary

The committed browser fixture is an overlay on the byte-sealed release v1
fixture. Its v2 manifest separates two identities:

- `baseReleaseIdentity` records the inherited v1 manifest digest, timestamp,
  and code revision with the explicit `sealed-release-v1` scope;
- `browserDerivationIdentity` points to a versioned deterministic derivation
  receipt and in-toto statement and explicitly says that execution identity was
  not recorded.

The v1 build receipt and provenance statement remain byte-identical and are
labelled as base-release evidence. The browser derivation receipt is not a build
receipt and does not claim a CI run, workflow, platform, time, or code revision.
Its materials distinguish the prebuilt scientific support inputs from the
attribution and SBOM outputs that the JavaScript overlay generator actually
derives. Every identity is an exact SHA-256; the companion statement uses a
project-specific predicate rather than an unearned SLSA predicate.

The overlay-derived digest graph is acyclic: derived data depends on the
browser derivation receipt, and the derivation statement depends on that
receipt and its outputs. This claim is intentionally limited to the overlay
graph. Inherited sealed v1 evidence is retained unchanged, including its
historical lineage structure; v2 does not rewrite that evidence to manufacture
a whole-release acyclicity claim.

## Clean-clone verification

From the repository root with the pinned Node and npm versions:

```bash
npm ci
npm run web:check
npm run web:e2e
PYTHONPATH=src/pipeline .venv/bin/python -m pytest \
  src/pipeline/tests/science/test_ar6_lookup.py \
  src/pipeline/tests/science/test_ar6_lookup_goldens.py \
  src/pipeline/tests/science/test_ar6_regional_release_contract.py \
  src/pipeline/tests/science/test_projection_contract.py \
  src/pipeline/tests/offline_release/test_cog_range.py \
  src/pipeline/tests/release/test_range_integrity.py \
  src/pipeline/tests/release/test_boundary_geoparquet.py -q
```

`npm run web:check` runs lint, generated-contract drift checks, TypeScript,
Vitest, and the production static build. The focused scientific lookup tests
are:

- `src/web/src/domain/scientific-lookup.test.ts` for exhaustive outcome
  mapping, cancellation, exact scaling, distance limits, tie breaks, and 500
  generated candidate sets;
- `src/web/src/data/geography-classifier.test.ts` for real GeoParquet decoding,
  support/coastal precedence, caching, corruption, and twelve shared Shapely
  parity cases at exterior boundaries, hole boundaries, and epsilon seams;
- `src/web/src/data/cog-analysis-reader.golden.test.ts` for all nine
  scenario/horizon combinations, 63 Python/TypeScript golden comparisons,
  native-grid edges, the inclusive 100 km reader policy, nodata, strict ranges,
  post-open last-caller cancellation, shared-reader safety, and malformed
  responses;
- `src/web/tests/static-shell.spec.ts` for a production-built, page-context
  exact lookup against the committed 139,264-byte COG. The gate observes
  same-origin `HEAD` and `206` requests under the shipped CSP, verifies the
  transferred chunk hashes, rejects multi-ranges, and proves lookup transfer
  remains smaller than the artifact;
- `src/web/src/data/browser-overlay-evidence.test.ts` for the first-class v2
  derivation schemas, byte-identical v1 evidence, scoped identities, absence of
  fabricated execution claims, and overlay-only digest-DAG acyclicity.

The 2026-08-16 local run on macOS arm64 with Node 20.20.1 completed 33 focused
lookup tests, 121 static-target unit/integration tests, and 24 desktop/mobile
Playwright tests. Its warm in-memory
100-lookup sample had p95 below the required
100 ms gate. This is a synthetic-fixture engineering measurement, not a claim
about public hosting latency or private production-sized bytes.

## Private candidate check

Private Phase 1 candidate bytes remain only at the ignored local path documented
in [Phase 2 private release binding](phase-2-private-release-binding.md). Use
that explicit loopback, read-only workflow only when the owner selects the exact
directory. Do not copy candidate bytes into `src/web`, a build directory, a CI
workspace, an action artifact, or external storage.

Before and after a private check:

```bash
git status --short
git check-ignore -v local-data/phase-1/local-production-run/candidate-v7/manifest.json
```

The static production build must continue to contain only the committed
synthetic fixture until a separately authorized public release is promoted.

## Fail-closed triage

- `RangeUnsupported`: `HEAD` or a range response omitted or contradicted the
  exact size/range delivery contract, including a full response instead of
  `206`.
- `FetchFailed`: a required immutable artifact or byte range was unavailable.
- `IntegrityFailed`: a complete artifact, range chunk, COG embedded identity,
  boundary identity, or source-grid mapping did not match the pinned release.
- `DecodeFailed`: otherwise verified artifact bytes could not be decoded.
- `ReleaseIdentityMismatch`: selection, analysis, visual, and manifest
  identities did not describe one immutable release selection.
- `Aborted`: the evaluation was cancelled or superseded; its result must be
  discarded.

Do not retry with another release, scenario, horizon, grid cell, quantile, or
artifact. Correct the delivery or release defect and rerun the same selection.
