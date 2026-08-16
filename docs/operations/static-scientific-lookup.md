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
4. resolves the selected scenario/horizon analysis COG from that same release;
5. requires byte-range responses, validates the 76 by 46 EPSG:4326 native grid,
   and reads q0.167, q0.5, and q0.833 from one nearest native source pixel;
6. applies the Haversine distance using the 6,371.0088 km mean Earth radius,
   lowest-location-ID tie break, and inclusive unrounded 100 km limit; and
7. returns exactly `ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, or
   `UnsupportedGeography`.

Manifest, integrity, transport, decode, range-support, coordinate-validation,
release-identity, and cancellation failures remain technical failures. They are
never converted into a scientific outcome. PMTiles supplies only the matching
visual identity and never supplies analysis values.

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
  src/pipeline/tests/release/test_boundary_geoparquet.py -q
```

`npm run web:check` runs lint, generated-contract drift checks, TypeScript,
Vitest, and the production static build. The focused scientific lookup tests
are:

- `src/web/src/domain/scientific-lookup.test.ts` for exhaustive outcome
  mapping, cancellation, exact scaling, distance limits, tie breaks, and 500
  generated candidate sets;
- `src/web/src/data/geography-classifier.test.ts` for real GeoParquet decoding,
  support/coastal precedence, geometry boundaries, caching, and corruption;
- `src/web/src/data/cog-analysis-reader.golden.test.ts` for all nine
  scenario/horizon combinations, 63 Python/TypeScript golden comparisons,
  native-grid edges, nodata, strict ranges, aborts, and malformed responses.

The 2026-08-16 local run on macOS arm64 with Node 20.20.1 completed 24 focused
lookup tests. Its warm in-memory 100-lookup sample had p95 below the required
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

- `RangeUnsupported`: the host returned a full response instead of `206`.
- `FetchFailed`: a required immutable artifact or byte range was unavailable.
- `IntegrityFailed`: a complete boundary artifact did not match manifest bytes.
- `DecodeFailed`: artifact structure, grid metadata, bands, nodata, or geometry
  semantics violated the release contract.
- `ReleaseIdentityMismatch`: selection, analysis, visual, and manifest
  identities did not describe one immutable release selection.
- `Aborted`: the evaluation was cancelled or superseded; its result must be
  discarded.

Do not retry with another release, scenario, horizon, grid cell, quantile, or
artifact. Correct the delivery or release defect and rerun the same selection.
