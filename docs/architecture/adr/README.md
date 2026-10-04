# Architecture Decision Records

This directory contains Architecture Decision Records for SeaRise Europe.
They preserve decision history; the source-backed parent views describe what is
implemented now. ADR-028 governs the main atlas; the earlier static/projection
decisions retain their explicitly scoped authority. The parent
[decision register](../11-architecture-decisions.md) summarizes which decisions
are active, amended, or superseded.

## Active ADRs

| ADR | Status | Decision |
|---|---|---|
| [ADR-028](ADR-028-coastal-atlas-adoption.md) | Accepted engineering direction | Main coastal atlas, explicit fixture/real-local editions and read-only loopback adapter; no public/scientific approval |
| [ADR-027](ADR-027-post-cutover-application-evolution.md) | Accepted | Evolve current source while preserving completed removal authority |
| [ADR-021](ADR-021-static-first-offline-geospatial-architecture.md) | Accepted | Static-first retained projection/build architecture; atlas runtime amended by ADR-028 |
| [ADR-024](ADR-024-ar6-regional-projection-contract.md) | Accepted; Phase 1 evidence complete | Report source-native AR6 regional projection values without terrain exposure classification |
| [ADR-025](ADR-025-accelerated-static-runtime-cutover.md) | Accepted | Completed legacy-runtime repository cutover; recover removed source through Git history, with later evolution under ADR-027/028 |
| [ADR-026](ADR-026-authoritative-browser-range-persistence.md) | Accepted | Persist complete resources in Cache Storage and only integrity-authorized COG chunks in bounded IndexedDB; keep PMTiles network-only and `no-store` |

## Superseded publication decisions

| ADR | Status | Historical decision |
|---|---|---|
| [ADR-023](ADR-023-vertical-reference-methodology.md) | Superseded for publication by ADR-024 | Build an EGM2008 baseline water surface and classify only outside the complete uncertainty interval |

## Proposed ADRs

| ADR | Status | Decision |
|---|---|---|
| [ADR-022](ADR-022-phase-0-source-and-geography-gate.md) | Proposed; historical safety gate retained | Terrain/geography/connectivity controls apply to the superseded binary path; its evidence remains immutable |

## Conventions

- One material architecture decision per file.
- File names use `ADR-NNN-short-title.md`.
- ADRs are append-only after acceptance except for corrections that do not
  change the decision.
- A changed decision receives a new ADR and links to the record it supersedes.
- The decision register and architecture index are updated in the same pull
  request.
- Superseded ADRs remain in this directory for history; they are never presented
  as active guidance.

ADR-001 through ADR-020 originated in a former combined decision document.
Their current dispositions are preserved in the
[decision register](../11-architecture-decisions.md) and Git history. New ADRs
must use standalone files in this directory.
