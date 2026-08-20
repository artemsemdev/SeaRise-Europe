# Issue #60 offline lifecycle evidence

The production-like Playwright gate uses only the committed synthetic release.
It builds and byte-seals three static application generations, switches the
loopback host atomically, and exercises one uninterrupted A→B→C browser
lifecycle in Chromium, the required Phase 2 browser baseline.

## Assertions

- A and B remain active while the next worker is waiting; no `skipWaiting`,
  `clients.claim`, or reload is used to force activation. Activation occurs
  only after every controlled tab closes.
- Preparing an update writes an armed close-and-reopen intent. Closing every
  controlled tab permits natural activation, and the next distinct launch
  consumes the exact intent.
- A consumed or tombstoned intent can roll forward only to a distinct valid
  candidate. Pending, armed, same-candidate, and malformed evidence fails
  closed.
- After C becomes active, B is the sole previous generation. A lifecycle,
  receipt, range, lease, release cache, and precache-addressed shell cache
  authority is absent except for its durable cleanup fence.
- A warmed 2050 assessment reloads as `ProjectionAvailable` offline. An
  unwarmed 2100 selection reports connection-required while preserving the
  previous scientific outcome; technical delivery state is not a fifth
  ADR-024 outcome.
- The application sends no `/assess`, `/geocode`, `/config`, Candidate-v7,
  TAR, or lifecycle-control request.

## Reproduction

From `src/web` after `npm ci`:

```bash
npx playwright install chromium
npm run e2e:offline-lifecycle
```

CI runs the same command with Playwright 1.62.1 and uploads only ordinary test
diagnostics. Candidate-v7 and its TAR are never read, copied, or uploaded.

The final local validation on 2026-08-17 used Node 20.20.1 and produced:

- Chromium lifecycle: 1 passed;
- web unit and integration tests: 57 files and 761 tests passed;
- lint, type-check, production build, test inventory, dependency inventory,
  build-plane SBOM validation, and its 13 contract tests: passed.

## Cross-engine status

WebKit 26.5 passed the same local A→B→C journey on 2026-08-17 when offline
delivery was exercised through the reversible lifecycle-host network outage.
This is optional evidence, not a required CI or support claim.

Firefox 153 verified the sealed waiting B worker but did not naturally activate
it after all controlled pages closed, after all SeaRise pages left worker
scope, or after bounded client-free waits. Reopening the same persistent
profile retained active A but discarded waiting B. The owner therefore scoped
Issue #60 acceptance to Chromium and explicitly deferred Firefox update
compatibility. No `skipWaiting` or `clients.claim` workaround was added.
