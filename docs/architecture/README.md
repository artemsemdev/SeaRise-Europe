# Architecture Documentation

These documents describe the source code in this repository. When prose and
implementation differ, inspect the executable source, schemas and tests first
and update the prose. ADRs explain decisions and historical constraints; they
are not evidence that every planned component is deployed.

Reviewed on **2026-10-04** against `origin/master` at
`fa6c3c2a` (the base of this documentation update). No application behavior or
scientific evidence is changed by this review.

## What runs today

| Surface | Implementation and data |
|---|---|
| `/`, normal build | Coastal atlas using an explicitly illustrative browser fixture |
| `/`, real-local mode | Same UI, read-only loopback Node adapter and Python raster service over separately provisioned CoCliCo inputs |
| Sealed private demo | Source/app/data-bound candidate of the real-local edition, launched on loopback |
| `/projections/` | Retained AR6 reference: local Worker search and exact lookup over a pinned browser v2 release |
| `/about/architecture/` | Projection reference build/status page |

Atlas uses SSP585, 2030/2050/2100 and two defense assumptions; its point states
are positive depth, valid zero and unknown. AR6 uses three scenarios × three
years and four projection outcomes. Their scientific meanings, IDs, search
implementations and persistence policies are separate.

Atlas has no service-worker registration or offline-data promise. The retained
projection worker is root-scoped but precaches only its own allowed resources;
private atlas responses are `no-store`. The local adapter is not public hosting.
Cloudflare/R2 remain a reference delivery direction; no OpenTofu deployment or
public atlas distribution is implemented here.

## Read and navigate

Start with [01 — System Context](01-system-context.md),
[02 — Container View](02-container-view.md), then
[03a — Frontend](03a-frontend-architecture.md). For operation, use the
[atlas development guide](../operations/coastal-atlas-development.md) and
[private demo candidate runbook](../operations/local-demo-candidate.md).

There are **16 numbered topic documents plus this README: 17 Markdown files at
this directory's top level**. The numbering is historical: `03a` is the retained
frontend view and there is no active `06`. ADRs and diagrams are additional
subdirectories, not missing numbered views.

| Document | Current scope | Main implementation anchor |
|---|---|---|
| [01 — System Context](01-system-context.md) | Products, actors, local/static boundaries | [Entries](../../src/web/vite.config.ts) |
| [02 — Container View](02-container-view.md) | Browser, Node/Python and offline execution units | [Adapter](../../src/web/scripts/real-local-atlas.mjs) |
| [03a — Frontend](03a-frontend-architecture.md) | Actual components, providers, routes and state | [AtlasApp](../../src/web/src/atlas/AtlasApp.tsx), [App](../../src/web/src/App.tsx) |
| [04 — Runtime Sequences](04-runtime-sequences.md) | Atlas/demo flows and retained projection lifecycle | [Demo launcher](../../scripts/demo/demo.mjs), [controller](../../src/web/src/application/assessment-controller.ts) |
| [05 — Data Architecture](05-data-architecture.md) | Browser/disk contracts, AR6 v1/v2 and storage | [Atlas contract](../../src/web/src/atlas/browser-data-contract.ts), [v2 schema](../../contracts/release/v2/manifest.schema.json) |
| [07 — Security](07-security-architecture.md) | Local trust, privacy, CSP and supply chain | [Edition boundary](../../src/web/scripts/atlas-edition.mjs), [build checks](../../src/web/scripts/inspect-build.mjs) |
| [08 — Deployment](08-deployment-topology.md) | Fixture, real-local and sealed-demo builds; hosting limits | [Commands](../../package.json), [sealed preview](../../scripts/demo/sealed-preview.mjs) |
| [09 — Operations](09-observability-and-operations.md) | Available evidence and diagnosis, monitoring gaps | [CI](../../.github/workflows/ci.yml) |
| [10 — Testing](10-testing-strategy.md) | Suite scopes, commands and release limits | [Inventory](../../tests/test-inventory.json) |
| [11 — Decisions](11-architecture-decisions.md) | ADR-028 atlas adoption and retained decisions | [ADR index](adr/README.md) |
| [12 — Risks](12-risks-assumptions-and-open-questions.md) | Open delivery/evidence gaps and resolved implementation choices | [Demo identity](../../scripts/demo/candidate.mjs) |
| [13 — Domain Model](13-domain-model.md) | Actual atlas and projection types and outcomes | [Projection domain](../../src/web/src/domain/release.ts) |
| [14 — Integrations](14-integration-patterns.md) | Provider HTTP, Worker messages, candidate and artifact handoffs | [HTTP provider](../../src/web/src/atlas/http-data-source.ts) |
| [15 — Performance](15-performance-and-scalability.md) | Enforced budgets, local limits and qualified measurements | [Budget evaluator](../../src/web/scripts/lighthouse-budget.mjs) |
| [16 — Geospatial Processing](16-geospatial-data-pipeline.md) | Local raster sampling and retained offline AR6 build | [Raster service](../../scripts/atlas/europe_raster_service.py), [builder](../../src/pipeline/searise_pipeline/offline_release/) |
| [17 — Atomic Projection State](17-atomic-projection-state.md) | Projection-only accepted tuple and stale-work guards | [Reducer](../../src/web/src/domain/projection-state.ts) |

## Diagram and supporting material

The [coastal atlas diagram](diagrams/coastal-atlas/README.md) includes an
interactive viewer, SVG/PNG exports and a source-linked editable specification.
It is pinned to its reviewed demo source commit; preserve its recorded
provenance rather than treating it as a live generated code view.

Supporting authorities:

- [ADR-028](adr/ADR-028-coastal-atlas-adoption.md): atlas adoption and local adapter.
- [ADR-027](adr/ADR-027-post-cutover-application-evolution.md): evolution after
  completed legacy removal without rewriting historical authority.
- [ADR-024](adr/ADR-024-ar6-regional-projection-contract.md) and
  [ADR-026](adr/ADR-026-authoritative-browser-range-persistence.md): retained
  projection science and browser persistence.
- [Atlas requirements](../product/COASTAL_ATLAS_PRD.md),
  [design](../product/COASTAL_ATLAS_DESIGN.md),
  [content](../product/COASTAL_ATLAS_CONTENT.md): atlas product interpretation.
- [AR6 methodology](../methodology.md) and
  [Flight design](../product/Mock/DESIGN.md): projection reference only.
- [Demo prerelease record](../releases/v0.1.0-rc.1.md): source deliverable and
  limitations; it does not distribute private CoCliCo data or qualify the MVP.

## Evidence and maintenance rules

**Implemented** means backed by checked-in executable behavior. **Target** means
a decision or requirement still awaiting implementation/evidence. **Fixture**
proves software behavior only. **Private local demo** is a sealed local artifact,
not public/scientific approval. Historical scientific dispositions and published
records retain their original scope and identity.

Keep these views aligned with source in the same PR as a behavior change:

1. Update the owning view and its implementation links; do not duplicate full
   TypeScript/JSON schemas into prose.
2. Distinguish atlas editions, projection releases, local candidates and public
   release authority.
3. Describe actual paths/commands. Label future hosting, telemetry and source
   preparation explicitly as gaps, not installed infrastructure.
4. Update the decision register and ADR index when a decision changes; retain
   accepted ADR history and immutable receipts.
5. Check relative links, `git diff --check`, suite routing and any affected
   contract/content checks before review.

Removed API, REST, relational and legacy server views remain in Git history.
Do not recreate them to fill numbering gaps. [docs/README.md](../README.md)
indexes the wider documentation collection; this README indexes architecture.
