# Phase 2 static-only repository audit

## Result

The Phase 2 integration branch contains one delivered runtime: the React/Vite
static browser application in `src/web`. A clean clone builds and serves the
committed synthetic release without Docker, .NET, PostgreSQL, TiTiler,
Azurite, a runtime geocoder, cloud credentials, or a Node application server.

Repository-removal v2 receipts preserve the exact owner-approved #72, #70, and
#71 transitions. Git history is the rollback mechanism for removed source.

## Removed repository runtime

- Next.js application and its separate dependency graph;
- ASP.NET solution, projects, packages, tests, and runtime entrypoint;
- request-time PostGIS schemas, database integration, and mutable activation;
- TiTiler, runtime geocoder, Azurite/blob-seed, and aggregate Compose paths;
- obsolete container build jobs, C# CodeQL routing, environment templates, and
  transition-only CI selectors;
- legacy upload, registration, and database activation pipeline modules.

## Retained authority

- Phase 1 release contracts, STAC, manifests, provenance, SBOMs, source locks,
  scientific goldens, ADR-024 evidence, and deterministic build-plane code;
- the canonical Flight mock, its design contract, and implementation map;
- ignored-path documentation for the local-only Phase 1 candidate;
- offline-release and pinned native-tool container recipes used only to build
  reproducible artifacts.

Candidate-v7 and TAR bytes are not read by CI, copied into the build, committed,
or uploaded. The clean-clone path uses only the committed synthetic fixture.

## Executable evidence

The integration gates cover:

- active static supply-chain profile: 13 components and 57 exact inputs;
- test inventory: 79 suites;
- static-target classification with zero pending-removal references;
- repository-readiness and final content scans with exact historical evidence;
- all four ADR-024 outcomes and all nine scenario/horizon combinations;
- GeoNames Web Worker search, exact AR6 COG lookup, and MapLibre/PMTiles visual
  rendering without treating PMTiles as scientific authority;
- generic static serving, static 404s for retired endpoints, share/reload and
  atomic state, keyboard/accessibility, offline/update, bundle, Lighthouse,
  and cross-runtime golden gates;
- exact PMTiles MIME, SHA-bound strong ETag, byte ranges, CORS, and `no-store`
  behavior for `200`, `206`, and `416`, while other approved release objects
  remain immutable.

The required browser gate is Chromium only. Firefox and WebKit are not claimed
as Phase 2 support baselines.

## Reproduce

```sh
npm ci
npm run web:check
npm run web:e2e

PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  static-profile \
  --document contracts/supply-chain/v2/static-target-profile.json \
  --repository-root .
python scripts/tests/validate_test_inventory.py
node src/web/scripts/check-target-content.mjs --static-target
node src/web/scripts/check-target-content.mjs --repository-final
```

Generic/reference-host and Lighthouse reproduction is documented in
[`docs/operations/generic-static-host-validation.md`](../../operations/generic-static-host-validation.md).

## Known limitations and external boundary

The committed fixture demonstrates product and release-contract behavior; it
is not a public scientific release. Candidate-v7 stays local-only. Live cloud
publication, DNS, credentials, secrets, GitHub environments, and external
resource cleanup were not performed and require separate authorization.
