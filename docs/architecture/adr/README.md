# Architecture Decision Records

This directory contains the authoritative Architecture Decision Records for
SeaRise Europe. The parent
[decision register](../11-architecture-decisions.md) summarizes which decisions
are active, amended, or superseded.

## Active ADRs

| ADR | Status | Decision |
|---|---|---|
| [ADR-021](ADR-021-static-first-offline-geospatial-architecture.md) | Accepted | Adopt the static-first offline geospatial architecture |
| [ADR-023](ADR-023-vertical-reference-methodology.md) | Accepted for validation; publication blocked | Build an EGM2008 baseline water surface and classify only outside the complete uncertainty interval |

## Proposed ADRs

| ADR | Status | Decision |
|---|---|---|
| [ADR-022](ADR-022-phase-0-source-and-geography-gate.md) | Proposed; safety gate enforced | Terrain/geography/connectivity candidates are selected; stop publication until uncertainty and named external approvals pass |

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
