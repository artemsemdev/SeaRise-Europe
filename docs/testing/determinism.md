# Determinism, flakes, and performance evidence

Tests must make nondeterminism an explicit input. Re-running a failed test until
it passes is diagnostic evidence of a flake, not a green gate.

## Functional profile `deterministic-v1`

Unless a test is specifically exercising one of these inputs, use:

- clock: injected fixed UTC instant, serialized with `Z`;
- timezone: `UTC`;
- locale: `C.UTF-8` in process/CI, with expected text supplied explicitly;
- random seed: `20260805`, printed on failure; property tests must accept a
  replay seed and keep minimized regressions as tables;
- ordering: sort filesystem, feature, object-key, and equal-score inputs by the
  documented stable key before assertions;
- numeric evidence: compare source location IDs and integer-millimetre
  q0.167/q0.5/q0.833 values exactly; use the registered tolerance only for
  published metre conversions and reported distance;
- concurrency: await or control work explicitly; never use sleep as readiness;
- identifiers: fixed builders or injected factories, not ambient UUID/time.

A test of timezone, locale, order, or seed behavior declares its variations in
the test name/table and still emits a reproducible failing case.

## Filesystem and network

Write only under a per-test temporary directory. Do not depend on home
directories, developer caches, current directory outside the runner contract,
or files left by a previous test. Promote output atomically and sort directory
enumeration before comparing it.

Unit tests do not use public network services. Network behavior uses a bounded
loopback fixture with fixed bytes, status codes, redirects, headers, delays, and
attempt counts. Timeouts and retry schedules are injected or bounded. Adapter
suites must cover, as applicable:

- failure before and during transfer;
- caller abort and cancellation propagation;
- stale work losing to a newer request;
- truncation, checksum mismatch, invalid format, and corrupt cache;
- bounded retry, exhaustion, and no retry for permanent failures.

Representative regional, public-origin, and browser delivery tests are separate
tiers because their network and storage are part of the contract. Their report
records origin, release ID, artifact checksum, request/range count, and retry.

## Browser profile `browser-reference-v1`

Functional browser parity uses the lockfile-pinned Chromium, UTC,
`en-US`, reduced motion, color scheme light, device scale factor 1, and fixed
viewport. The production-static suite introduced by #70 must include:

- desktop: 1440 x 900 CSS pixels;
- mobile: 390 x 844 CSS pixels;
- cold shell and explicitly warmed supported-cache runs;
- an offline run only after the supported cache is warmed;
- request logging that fails on `/assess`, `/geocode`, or `/config`.

Screenshot tests mask only documented volatile external pixels; result text,
attribution, focus, state, and map alternatives remain asserted semantically.
Snapshots cannot be the sole evidence for the four domain states.

## Performance profiles

Performance reports identify a profile; an unlabeled timing is diagnostic only.

| Profile | Use | Required record |
|---|---|---|
| `local-fast-v1` | TDD feedback and mutation pilot | OS/architecture, runtime versions, warm/cold dependency state, wall time |
| `ci-regional-v1` | Representative transform and browser candidate | runner image, CPU/memory reported by runner, fixture/release SHA-256, cold/warm cache, per-step wall time |
| `browser-reference-v1` | Promotion budgets in architecture testing strategy | browser/version, viewport, throttle, cache state, artifact release, sample count, p50/p95/max |

Do not compare timings across profiles. Functional PR tests have no blanket
latency assertion. Regional and release suites apply the accepted budgets from
`docs/architecture/10-testing-strategy.md` only after a warm-up and at least 30
recorded samples; raw observations and aggregation stay with the candidate.

## Quarantine contract

There is no unowned or indefinite quarantine. A quarantined suite must declare
in `tests/test-inventory.json`:

- accountable owner;
- linked defect issue;
- expiry date;
- evidence explaining why the failure is nondeterministic rather than a product
  regression.

The expiry is at most 14 days unless a blocking-gate review approves a shorter
release-specific plan. On expiry the suite returns to blocking or the PR fails.
Retries preserve and report the first failure and cannot turn a blocking gate
green. Scientific, integrity, licence, provenance, public delivery, rollback,
and promotion tests cannot be quarantined or waived.

## Mock and coverage policy

Mock a boundary only to prove caller behavior. Use representative data for
scientific arrays, shared manifests, byte ranges, storage/public headers, and
browser delivery. A mock must not reproduce the implementation's algorithm as
its expected-value generator.

Coverage reports find unexercised branches and risky files. They are diagnostic
evidence, not a repository-wide percentage gate and never authorize test
retirement. Prefer table/property boundaries, an independent control, and the
bounded mutation pilot over assertions written only to raise a line count.
