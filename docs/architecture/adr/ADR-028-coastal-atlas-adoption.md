# ADR-028: Adopt the accepted coastal atlas

Status: accepted engineering direction from the owner's 2026-09-10 instruction;
implementation in [#490](https://github.com/artemsemdev/SeaRise-Europe/issues/490).
This decision is not a public deployment or scientific release approval.

## Context

The accepted local product depicts CoCliCo coastal inundation. The normal
repository build still serves the AR6 relative sea-level application. Treating
both as one scientific contract creates contradictory product requirements,
and keeping the accepted app outside normal build/CI prevents reproducible work.

## Decision

Adopt the light European coastal atlas as the main application, preserving its
accepted behavior and removing the experimental Lab entirely. Its source
contract is one SSP5-8.5 pathway, three years (2030/2050/2100), and two defense
assumptions. Use the [PRD](../../product/COASTAL_ATLAS_PRD.md) as the active product definition.

Retain ADR-024 and its projection contracts for the AR6 reference application.
Its outcomes, likely-range meaning, release receipts, and scientific no-go
history are unchanged. CoCliCo depth cells are not AR6 projection outcomes;
independent source identities and validation prevent interchange between them.

Use explicit real-local and synthetic-fixture data editions. Isolate browser
contracts from filesystem manifests. A read-only loopback raster adapter is
allowed for the local edition; compact authored fixtures support normal CI.
Neither edition may silently substitute for the other. No private candidate
archive or large source raster belongs in the application build or repository.

The local adapter is a development boundary, not a production hosting choice.
Do not add durable storage of private local-derived data or register an atlas
service worker. Resolve public data distribution, acquisition reproducibility,
rights, static delivery feasibility, and release qualification before publication.

## Consequences and verification

Replace obsolete active Flight requirements with the accepted atlas design.
Scope projection-only terminology checks to the AR6 reference, while continuing
to reject unsupported certainty, property assessments, fabricated probability,
and conflation of valid zero with unknown in every product edition.

Transfer in dependency order through focused issue PRs into
`integration/coastal-atlas`. Keep the reference app buildable until the atlas's
primary entry is ready. Normal build, fixture tests, real-local regressions,
source-boundary checks, and visual review must cover the actual application
before the final integration PR to master. The owner decides that final merge.
