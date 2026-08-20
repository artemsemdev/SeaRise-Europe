# ADR-025 — Accelerate repository cutover to the static runtime

> **Status:** Accepted
>
> **Decision date:** 2026-08-16
>
> **Decision owner:** Project owner
>
> **Scope:** Repository runtime and development baseline; external production
> resources are explicitly excluded

## Context

ADR-021 defined a staged migration in which the Next.js, ASP.NET Core,
PostGIS, TiTiler, runtime geocoder, Azurite, and legacy deployment code remained
in the repository until production cutover. Phase 0R and Phase 1 have since
established the scientific and immutable-artifact contracts needed by a static
browser consumer. Keeping two application architectures now increases review,
CI, dependency, security, and contributor cost without providing a required
product capability.

The project owner has decided that the legacy runtime is not a baseline or a
rollback target. Repository history is sufficient for source recovery. The
static application must therefore become the only checked-in runtime during
Phase 2, after equivalent-or-stronger behavior coverage exists in the target.

This decision does not claim that a private Phase 1 candidate is publishable.
Candidate-v7 and its TAR remain ignored, local-only evidence and must never be
copied into a static build, CI artifact, GitHub, R2, or another external store.
Clean clones and CI use the committed synthetic release fixture.

## Decision

Phase 2 delivers one static-first repository baseline:

- React 19, TypeScript, and Vite 8 produce static files that work on a generic
  static server;
- the browser consumes immutable release manifests, GeoNames search shards,
  PMTiles visual layers, and exact AR6 analysis COGs;
- normal operation makes no `/assess`, `/geocode`, or `/config` request and has
  no dependency on a Node server, .NET, PostgreSQL/PostGIS, TiTiler, Azurite,
  Docker, or a runtime geocoder;
- ADR-024 remains the complete scientific domain contract, including its four
  outcomes and prohibited interpretations;
- after target coverage is merged, focused Phase 2 pull requests remove the
  superseded repository runtime, tests, dependencies, scripts, CI jobs, and
  deployment scaffolding.

Every removed legacy test must be mapped to equivalent-or-stronger static
target evidence before deletion. Historical five-state exposure fixtures may
remain only in clearly labelled historical evidence locations; they are not
part of the target domain or runtime bundle.

The following remain permanent repository assets:

- audited sources and source locks;
- release schemas, manifests, STAC, provenance, integrity, licence, and SBOM
  contracts;
- ADR-024 evidence and scientific goldens;
- deterministic pipeline code that builds or validates static releases;
- historical ADRs and Git history;
- ignored local Phase 1 candidate evidence.

## Repository deletion boundary

Repository removal is authorized only after the corresponding static behavior
and migration evidence pass. It includes:

- `src/frontend` and the Next.js runtime;
- `src/api`, the .NET solution, and the C# request-time runtime;
- runtime PostGIS schemas, seeds, and database integration;
- TiTiler, runtime geocoder, Azurite, and blob-seed paths;
- mutable upload/database activation paths;
- obsolete Dockerfiles, Compose services, environment variables,
  dependencies, scripts, CI jobs, and runtime documentation.

Reusable build-plane code is evaluated by purpose, not language or directory.
Code remains when the static release pipeline still needs it and deterministic
tests cover it.

## External-resource boundary

Deleting repository code does not authorize deletion or mutation of cloud
resources, credentials, GitHub environments, secrets, storage objects,
databases, or deployment accounts. Any destructive external cleanup requires a
separate inventory, exact target resolution, explicit owner approval, and
recorded recovery consequences.

Phase 3 may still provision and verify static delivery. Production cutover and
external-resource retirement remain later operational decisions. They do not
block removal of unused source code from the Phase 2 repository baseline.

## Validation gate

The accelerated removal is complete only when a clean clone proves:

- install, lint, type-check, unit, integration, production build, static serve,
  Playwright, accessibility, and keyboard checks;
- all four ADR-024 outcomes, technical failure handling, and all nine
  scenario/horizon combinations;
- GeoNames Web Worker search, exact nearest-grid AR6 COG lookup with the
  inclusive 100 km limit, and MapLibre/PMTiles rendering;
- release isolation, atomic share/reload state, offline behavior, and safe
  updates;
- zero `/assess`, `/geocode`, and `/config` requests;
- no runtime dependency on the deleted stack;
- bundle, performance, cross-runtime golden, and repository policy gates;
- no prohibited product claims outside an explicit historical allowlist.

Candidate-v7 may be used only by an explicit read-only local command that
points at its ignored path. It is not a clean-clone or CI prerequisite.

## Consequences

Positive consequences:

- contributors and CI have one application architecture to understand;
- obsolete server dependencies stop consuming maintenance and security work;
- static-only assumptions are enforced early instead of deferred to cutover;
- all recovery of removed source is explicit and auditable through Git.

Trade-offs:

- there is no checked-in runnable legacy comparison environment after Phase 2;
- historical behavior investigations require checking out an earlier commit or
  worktree;
- production rollback must use a previously verified static application and
  immutable release pair, not the retired distributed runtime.

## Alternatives considered

### Keep the legacy stack until production stabilization

Rejected by the project owner. It preserves two baselines and delays proof that
the repository is genuinely static-only.

### Move legacy code to an archive directory or branch

Rejected. It retains dependency and maintenance ambiguity. Normal Git history
already provides immutable source recovery.

### Delete the legacy stack before target coverage exists

Rejected. Accelerated removal changes the schedule, not the evidence standard.
Equivalent-or-stronger static coverage remains mandatory before each deletion.

## Relationship to earlier decisions

ADR-025 amends the migration and decommission sequence in ADR-021. It does not
change ADR-021's target architecture or ADR-024's scientific contract. Where
older delivery text requires retaining the legacy runtime through Phase 3 or a
production stabilization window, this ADR takes precedence.
