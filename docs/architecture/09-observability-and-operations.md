# 09 — Observability and Operations

> **Status:** Repository tooling and local operations, reviewed 2026-10-04.
> Production monitoring and hosting intentions are not installed services.

## Available evidence

| Area | Implemented evidence | Scope |
|---|---|---|
| Frontend build | Exact output, precache, CSP and separate initial JS size checks in `inspect-build.mjs` | Current build; no public hosting claim |
| Browser behavior | Vitest and Playwright assertions, screenshots and traces | Fixture journeys; separately provisioned real-local journeys |
| Static delivery | Generic-host validation and Lighthouse runner | Local production-build harness |
| Atlas raster service | Startup digest checks, readiness message, HTTP errors and tile validity counts | Local source/transport health |
| Private demo candidate | Exact source, toolchain, app inventory and external metadata identities | Local reproducible handoff; does not package or publish rasters |
| AR6 pipeline | Stage receipts, source/artifact hashes, parity and candidate validators | Exact inputs/profile/revision of the run |
| Supply chain | SBOM, signing, verification and readback receipts | Controlled evidence flow; not ordinary fixture output |
| Architecture route | Build ID, release ID, disposition and manifest path | Retained projection reference only |

The implementation has no application analytics collector, telemetry backend,
production metrics dashboard, scheduled multi-region availability probes or
configured cloud cost alerts. Consequently no measured uptime/SLA or zero-cost
production result is asserted here.

Source anchors: [CI](../../.github/workflows/ci.yml),
[static quality](../../.github/workflows/static-quality.yml),
[build inspection](../../src/web/scripts/inspect-build.mjs),
[raster service](../../scripts/atlas/europe_raster_service.py),
[architecture page](../../src/web/src/routes/ArchitecturePage.tsx).

## Local atlas diagnosis

1. Confirm the intended edition and use matching build/serve commands.
   A preview marker mismatch is a startup error; rebuild the selected edition.
2. For real-local, check the explicit data root, interpreter and confined
   manifest/index/raster files. Startup verifies these before serving the app.
3. Treat HTTP, JSON, PNG or source-read failure as a technical failure. Do not
   repair it by selecting fixture data or replacing unknown with zero.
4. Distinguish map geography failure from flood-tile failure and point
   inspection. Their UI errors/retries are separate.
5. Stop the Vite server to terminate its owned Python process. The raster proxy
   has a 30-second timeout and disconnect cancellation; it is not a background
   production daemon.

Python suppresses default request access logs. Search/inspection still cross
loopback in GET URLs, and the UI writes current view state to the document URL.
No repository evidence proves that arbitrary future hosting/proxy logs are
scrubbed. See [07](07-security-architecture.md).

## Projection diagnosis and recovery

A manifest identity/schema failure stops release bootstrap. Retry only the
pinned release. A missing range, integrity failure or unavailable store is a
technical state, never `DataUnavailable`. For offline diagnosis, inspect the
exact admitted app/release pair and authorized COG chunks; an unwarmed location
or layer need not work offline. PMTiles remains network-only.

Update/retention failures retain their own retryable technical state. Do not
force activation or delete stores used by live/unknown clients. Application
rollback requires a verified deployment; source recovery uses Git history.

Runbooks retain the detailed protocols:

- [Atlas development](../operations/coastal-atlas-development.md) and
  [local adapter](../operations/coastal-atlas-real-local-adapter.md)
- [Static scientific lookup](../operations/static-scientific-lookup.md)
- [Offline client lifecycle](../operations/static-offline-client-lifecycle.md)
- [Production browser retention](../operations/production-browser-retention.md)
- [Offline release builder](../operations/offline-release-builder.md)
- [Public readback](../operations/phase-1-public-readback.md)

## Reading performance evidence

A report must identify edition, build/release, browser/tool profile and cold/warm
conditions. Fixture success does not validate local CoCliCo sources; source
hashes do not validate scientific meaning or public delivery.

The Lighthouse evaluator accepts raw 90+ results without any waiver. The current
runner selects the separate private-local-demo exception, valid until
2026-10-16 00:00 Europe/Berlin, only if accepting lower performance needs it.
It records 54/56/54 fixture performance and retains a 50 floor, 90 in the other
categories and zero render errors. That exception is not public/MVP or
scientific qualification. The expired September adoption policy is historical;
see [15](15-performance-and-scalability.md).

## Future public operations

Before a public data deployment, define operator ownership, exact release
qualification, delivery probes, response headers, cost assumptions and recovery
procedures against the chosen host. These remain delivery work. Existing local
and controlled-build tools provide evidence inputs, not an already operating
monitoring platform.
