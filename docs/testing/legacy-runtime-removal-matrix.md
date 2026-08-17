# Phase 2 legacy-runtime replacement and retirement matrix

> **Scope:** Issues #70, #71, and #72
>
> **Authority:** This matrix is hash-bound by the repository-removal evidence
> receipt. It describes replacement evidence; it does not authorize deletion
> without the canonical census, evidence receipt, and live owner decision.

The canonical machine census is
`contracts/repository-removal/v1/census.json`. Every tracked blob beneath its
roots, every exact path, and every semantic selector must occur exactly once in
the deletion inventory with the census-assigned issue owner. Directory globs,
unverified exclusions, and substring-only workflow checks are not accepted.
The census also requires `static-target-content` and `static-web-shell` as
replacement suites. Their repository and built-output scanners make absence of
legacy endpoint routes and runtime environment/configuration dependencies an
approval prerequisite.

## Issue #70 — Next.js frontend

| Retiring behavior | Permanent target evidence |
|---|---|
| API-shaped assessment, configuration, methodology, and geocoding clients | `static-release-domain`, `static-projection-panel`, `static-projection-browser-ux`, and immutable manifest/methodology repository suites |
| Five-state/binary result presentation | Four ADR-024 outcomes in `static-release-domain` and `static-projection-browser-ux`; technical errors remain outside the scientific outcome domain |
| Zustand store, URL, map, legend, dialog, focus, and retry behavior | Static application/controller/component tests plus the production Chromium journey |
| Frontend AR6 and regional fixture copies | `static-release-domain`, `pipeline-regional-fixture`, `pipeline-reviewed-cog-range-access`, and retained scientific goldens |
| Next.js search shards and Worker evidence | `static-settlement-search`, production static-shell Worker tests, and deterministic search evidence tests |
| Next.js lint, type, contract, and content commands | `static-target-content` and the `src/web` lint, type-check, test, and production-build gates |

The detailed test-by-test mapping remains in
`docs/testing/legacy-frontend-removal-inventory.md`. It is supporting evidence,
not the hash-bound cross-issue authorization matrix.

## Issue #71 — API, database, adapters, and executable legacy science

| Retiring behavior | Permanent target evidence |
|---|---|
| ASP.NET request validation and endpoint orchestration | Static schema validation, local assessment controller tests, technical-failure tests, and zero `/assess`, `/geocode`, `/config` browser requests |
| C# five-state determiner | ADR-024 four-outcome browser and Python science suites; the labelled five-state fixture remains historical-only |
| Runtime Nominatim/Azure Maps geocoder | Integrity-checked GeoNames Worker search and local privacy/failure tests |
| PostGIS repositories and mutable scenario/layer activation | Immutable release manifest, scenario/horizon contract, boundary artifacts, atomic release identity, and share/reload isolation tests |
| TiTiler exposure evaluator | Exact COG analysis reads plus identity-bound PMTiles visual rendering and byte-range delivery tests |
| Blob upload, database registration, and binary exposure pipeline | Audited acquisition, exact AR6 source-grid lookup, deterministic release builder, reproducibility, provenance, STAC, SBOM, and range-integrity gates |
| API/legacy Python dependencies and CodeQL C# | Static contributor dependency authority, supply-chain profile, JavaScript CodeQL, Python tests, and repository absence scans |
| Legacy top-level `pipeline` import/package mapping | Exact deletion of `src/pipeline/__init__.py` plus independently resolved `tool.setuptools.packages` and `tool.setuptools.package-dir` selectors; the retained `searise_pipeline` build-plane package remains |

Before deleting the executable five-state domain, the retained scope-review
builder must use ADR-024 support/coastal semantics directly and must not import
the superseded five-state model. Immutable historical evidence may name old
paths but cannot execute inside the active target package.

Issue #71 must be updated before owner approval to state the narrow exception
explicitly: `src/pipeline/searise_pipeline/domain/**` is deleted because it is
the superseded executable five-state model, while historical five-state
evidence remains retained only in its allowlisted evidence locations. The
scope-review decoupling change that removes active imports of that model must
merge first. Until both the issue text and dependency order reflect those
facts, the #71 census entry is inventory scope, not deletion authorization.

## Issue #72 — Compose and runtime containers

| Retiring behavior | Permanent target evidence |
|---|---|
| Next.js and API images | Production Vite build served by the pinned generic static host |
| TiTiler container | Direct COG/PMTiles range delivery and generic-host route/header tests |
| PostGIS and Azurite services, volumes, seed container | Clean-clone static build/E2E with committed synthetic fixtures and zero Docker, database, or storage-emulator dependency |
| Compose health and smoke orchestration | Static host validation, Chromium E2E, offline/update lifecycle, accessibility, and keyboard gates |

Issue #72 removes the API/frontend Dockerfiles before #70/#71 remove their
containing trees. This preserves single issue ownership for every canonical
locator.

## Semantic test retirement

Every active suite whose `replacementGate.issue` is 70, 71, or 72 must occur
exactly once in an inventory item's `retirementSuiteIds`. Every deleted
baseline path must be owned by that mapped suite. Each deletion item also names
active `replacementSuiteIds` and evidence-receipt `replacementCheckIds`; the
validator rejects missing, retired, duplicated, or unlinked identities.
The canonical census defines allowed and mandatory replacement suites
separately for #70, #71, and #72. Issue #71 specifically requires
`pipeline-science-contracts`, whose receipt check must name a real retained
science-test path matching that suite's `sourcePaths`; an unrelated workflow
path cannot substitute. Recorded commands must exactly equal each covered
suite's inventoried focused or full command.

Runtime endpoints and environment variables inside fully deleted files are
owned byte-for-byte by the census root or exact-path locator. Shared retained
files use semantic selectors (workflow jobs, Python assignments, structurally
parsed PEP 621/PEP 508 dependencies, and setuptools mappings). Pyproject and
requirements selectors have distinct identities so metadata, comments, pip
options, index URLs, and hashes cannot satisfy a dependency locator. The
mandatory target/repository and built-output scanner suites close the remaining
boundary by rejecting any legacy route,
server, database, container, or mutable runtime configuration that leaks into
the static target.

## Retained evidence and non-authorizations

Retain audited sources and locks, release contracts and fixtures, STAC,
manifests, provenance, SBOMs, ADR-024 evidence, scientific goldens,
deterministic build-plane code, the immutable Phase 1 supply-chain subtree,
historical ADRs, and the exact Flight mock. Historical five-state evidence is
exact-path allowlisted and cannot enter `src/web` or active pipeline runtime.

Candidate-v7 and TAR bytes remain local-only and uninspected by this approval
chain. Repository deletion never authorizes publishing those bytes or mutating
cloud resources, credentials, GitHub environments, secrets, or external data.

## Evidence execution

Each receipt check records an exact safe command, a retained output file, and
the SHA-256 of that file at the audited commit. An approved chain additionally
requires live verification of the exact Issue #68 comment ID, URL, body,
`artemsemdev` login, and `OWNER` association.
