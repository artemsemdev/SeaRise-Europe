# 12 — Risks, Assumptions, and Open Questions

> **Status:** Current repository risks, reviewed 2026-10-04.
> Claims below distinguish implemented controls from evidence still needed.

## Current risks

| Risk | Existing control/evidence | Remaining limitation or required evidence |
|---|---|---|
| Fixture mistaken for real coastal modeling | Explicit provider edition and visible fixture disclosure; four places and bounded Venice grids | Fixture tests establish software behavior only |
| Atlas and AR6 scientific meanings conflated | Separate entries, contracts and ADR-028/024 | Keep depth, relative sea-level change, source identities and result vocabulary separate in every change |
| Unknown interpreted as valid zero | Strict point contracts, masked raster reads and tile validity counts | Transparent pixels alone cannot establish availability; never infer point values from color |
| Local service failure silently changes data | Explicit edition selection, no HTTP-to-fixture fallback, separate technical errors | Local data/service must be provisioned and healthy |
| Private local-derived data leaks or persists | Confined paths, sanitized catalog, no-store JSON/tiles, build isolation, no atlas precache | Basemap also uses no-store; public distribution and rights are not yet qualified |
| Prepared atlas cannot be reproduced from a clean checkout | Startup validates existing raster/index identities | A complete checked-in CoCliCo acquisition/preparation workflow is not implemented |
| Basemap is treated as scientific coverage | Independent geographic and depth layers, 25 m disclosure | Closer zoom and detailed buildings do not improve native depth resolution |
| Local search/rendering fails at scale | Result cap, debounce, cancellation, bounded raster concurrency and RAM tile cache | Node search scans the prepared index; startup hashes full rasters; no production capacity claim |
| Performance gate reported as green from old evidence | Separate build budgets and Lighthouse raw-score policy | Raw 90+ passes need no waiver; the separate private-demo exception expires 2026-10-16 and does not qualify the public/MVP target |
| Offline promises extend to atlas | Projection-only precache and explicit no-atlas-worker design | Atlas reload and real-data offline packs are not implemented |
| AR6 app/release state mixes during update | Atomic projection reducer, exact-pair admission, client leases and controlled cleanup | Preserve cancellation, identity and browser compatibility tests |
| Search/grid lookup regresses | Worker tests, native-grid goldens, COG/GeoParquet/PMTiles parity | Every new source/release still requires its own validation; synthetic coverage is not approval |
| Dependency or historical approval changes unnoticed | Supply-chain profiles, SBOM validators, post-cutover authority checks | Local evidence-only validation does not attest current GitHub owner comments |
| Public hosting/cost promises exceed repository state | Generic static-host checks and explicit delivery contracts | No installed Cloudflare/OpenTofu topology, continuous monitor or verified current cost model |
| Documentation becomes a parallel specification | Concrete source anchors and edition-scoped views | Update these views with code; do not change code merely to satisfy stale prose |

## Resolved implementation choices

These are no longer open questions or unfinished migration steps:

- `/` is the coastal atlas; `/projections/` retains the AR6 reference.
- Atlas has explicit fixture/real-local editions and a read-only loopback
  service allowed by ADR-028.
- Projection search uses the implemented codepoint trie and core/coastal shards,
  not a pending MiniSearch selection.
- The browser release manifest is v2; immutable v1 release evidence remains.
- The old Next.js, ASP.NET, database and tile-service repository paths have
  been removed. [ADR-027](adr/ADR-027-post-cutover-application-evolution.md)
  permits current source evolution while preserving that historical authority.
- Private demo preflight/preparation/serving seals exact source/app/data identities; it does not package rasters or authorize public promotion.
- The AR6 Phase 0R recovery and owner disposition are recorded as complete;
  the earlier binary terrain path remains a historical no-go. Neither fact
  qualifies the atlas for a public scientific release.

## Open delivery decisions

| Question | Evidence needed before declaring it resolved |
|---|---|
| How is real atlas data acquired/prepared reproducibly? | Reviewed source locks, rights, exact transformations, receipts and repeatable construction of rasters/context/basemap |
| What public atlas delivery architecture replaces loopback? | Measured static feasibility or an explicitly approved service design, security/headers, transfer/latency and cost evidence |
| Which source/derivative bytes may be redistributed? | Dataset-specific rights and attribution review bound to actual artifacts |
| How will an atlas release be identified and qualified? | Versioned public artifact identity and validation; current atlas view URLs contain no immutable data-release pin |
| What correction meets the unwaived public performance target? | Current cold-browser measurements; temporary demo acceptance is not public/MVP qualification |
| Is a regional offline atlas pack useful and feasible? | Explicit storage authority, quota/recovery tests and a product decision; no inference from AR6's caches |
| Which browsers and accessibility claims are supported? | Relevant automated and manual evidence for atlas, separately from projection lifecycle tests |
| Is telemetry needed? | A concrete purpose, minimized fields, URL handling, retention and user-facing policy before integration |

See the [scoped backlog](../delivery/coastal-atlas-backlog.md) for retained work.
This register does not assert live issue status from issue numbers or old plans.

## Historical scientific evidence

The former binary exposure model could not reconcile its scientific inputs.
Its [terminal no-go](../evidence/phase-0-14-final-no-go.md) and
[vertical methodology](adr/ADR-023-vertical-reference-methodology.md) remain
historical evidence. ADR-024 instead reports native AR6 relative change without
terrain comparison; the [Phase 0R evidence](../evidence/phase-0r-regional-release.md)
records that recovery. CoCliCo atlas depth is a separate adopted source contract,
not a reversal of the rejected AR6-versus-terrain operation.

Do not rewrite old receipts, owner decisions or no-go outcomes to describe the
current app. Current implementation belongs in these views; decisions retain
their historical context in [the ADR index](adr/README.md).
