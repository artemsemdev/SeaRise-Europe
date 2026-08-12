# Phase 1 settlement production evidence

> **Issue:** [#298](https://github.com/artemsemdev/SeaRise-Europe/issues/298)
>
> **Disposition:** exact local production bytes, Node-worker diagnostics, and
> accepted Chromium reference evidence are retained; application integration
> and candidate publication gates remain blocked.

The machine-readable
[`phase-1-settlement-production-inventory.json`](phase-1-settlement-production-inventory.json)
records the exact local artifact sizes and SHA-256 identities for data release
`searise-europe-v1.0.0-20260812-939053bab621`. The corresponding large bytes
are retained outside Git under `local-data/phase-1/` as documented in the
[offline builder evidence](phase-1-offline-release-builder.md#local-production-data-handoff-2026-08-12).

## Verified production chain

- Both full GeoNames scans completed with zero parser failures: 13,455,006
  place-source rows, 3,865 admin1 rows, 19,037,112 alternate-name rows, and
  7,929 language rows.
- The normalized catalogue contains 4,988,582 places. The spatial stage
  classifies 701,881 places, including 91,190 core and 137,944 coastal
  memberships.
- The 701,881-record search projection reproduced byte-for-byte from the exact
  spatial database and receipt.
- GeoParquet contains 701,881 rows and its receipt records a byte-for-byte
  rebuild.
- Both Brotli browser shards match their v4 receipt.
- The post-traversal-fix Node-worker diagnostic completed and independently
  validated with identity
  `36d21fd8dc303f523e5a19cb00c789804dd2a42ed9c15ba3c3d1cddff56083e9`.
  Its 600 warmed query observations have p95 7.426417 ms.
- The release-bound Web Worker ran in headless Chromium 151 on the documented
  Apple M1 Max reference host. Five fresh core initializations produced p95
  618.91 ms against the 1,000 ms target; 200 warmed production-query
  observations produced p95 5.33 ms against the 50 ms target. Dedicated
  worker-isolate CDP telemetry recorded 753,232,781 peak observed bytes. The
  intercepted network inventory contains only the page, worker module, and two
  static shards, with no query transmission. The canonical local report is
  `browser-worker-performance/browser-worker-performance.chromium.json`,
  SHA-256 `8491c032d1ebc7a904416aa1036cf0c4df52ef2b424fcacc7eb5a431543cfa0c`.

## Rights disposition

The project owner recorded a
[conditional publication approval](https://github.com/artemsemdev/SeaRise-Europe/issues/298#issuecomment-5267891419)
for the GeoNames and Natural Earth derived settlement artifacts. The approval
applies only when the final candidate binds these exact reviewed identities and
passes the remaining candidate, browser-runtime, integrity, signing, readback,
and retention gates. This evidence therefore keeps all publication and
production claims false.

## Remaining stop conditions

The Chromium reference profile now satisfies the Phase 1 initialization,
query-p95, worker-memory reporting, responsiveness, and zero-query-leakage
requirements. The full application still has to replace its retiring runtime
geocoder with this worker protocol before [#56](https://github.com/artemsemdev/SeaRise-Europe/issues/56)
can close. Candidate-wide QA, protected signing/readback, and external immutable
co-retention also remain separate required gates.

This record is durable repository evidence for exact identities; it does not
promote the local handoff directory into immutable storage and does not close
Phase 1.
