# Settlement browser-worker performance evidence

> **Retirement notice:** The production static target now owns the accepted
> local browser path in `src/web/scripts/measure-local-candidate-search.mjs`
> and `src/web/scripts/search-performance-evidence.mjs`; use the
> [static settlement-search runbook](static-settlement-search.md) for new
> measurements. The legacy runners documented below remain only until issue
> #70 removes `src/frontend`, so their tests can be retired with explicit
> replacement evidence rather than silently deleted.

## Accepted Chromium reference path

`src/frontend/scripts/measure-production-browser-worker.mjs` builds the real
browser worker with pinned esbuild, serves the exact receipt-bound Brotli
shards from a cross-origin-isolated loopback origin, and runs the production
query set in Playwright Chromium. The worker checks the decompressed release
bytes against their SHA-256 authority before parsing and hydrates the already
validated serialized trie without rebuilding it from every alternate name.

The harness retains initialization and query distributions, main-thread timer
gaps, the exact query-set and shard identities, all intercepted request paths,
and worker-isolate heap plus backing-storage telemetry from Chrome DevTools
Protocol `Runtime.getHeapUsage`. Query text remains inside the worker and is
never included in a request or report. The report is canonical JSON with a
validated content identity and fails if initialization p95 is not below 1,000
ms, query p95 is not below 50 ms, memory is unmeasured, or any unexpected
network request occurs.

```bash
cd src/frontend
npm run measure:settlement-browser -- \
  --shard-directory ../../local-data/phase-1/browser-shards \
  --shard-receipt ../../local-data/phase-1/browser-shards/settlement-browser-search-shards.receipt.json \
  --query-set ../../local-data/phase-1/performance-queries.json \
  --data-release-id searise-europe-v1.0.0-20260812-939053bab621 \
  --output ../../local-data/phase-1/browser-worker-performance/browser-worker-performance.chromium.json \
  --initialization-samples 5 \
  --query-samples 10
```

The historic Node harness below remains useful for deterministic producer
diagnostics. Its measurements do not replace the accepted Chromium evidence.

`src/frontend/scripts/measure-settlement-browser-worker.ts` measures the exact
receipt-gated settlement search shards produced from a pinned search projection.
It accepts the same small synthetic fixture used by contract tests and the same
production-sized projection and shard directory used by a controlled build.
It does not publish artifacts or choose a search engine.

The harness first rebuilds the projection and requires the existing receipt,
both compressed shard byte streams, and every recorded SHA-256 to match. Each
timed build is also compared byte-for-byte with that set. Fresh isolated Node
workers then receive those exact compressed bytes by structured clone, validate
and initialize both shards, and execute a hash-bound query set after one warm-up
per query. The report records:

- receipt and compressed-shard byte sizes and SHA-256 values;
- raw Brotli-decoded sizes, per-shard record counts, and the deduplicated count;
- build, end-to-end worker initialization, and warmed query observations with
  minimum, p50, p95, maximum, mean, and sample count;
- the highest observed V8 worker isolate used-heap, external-byte, and combined
  snapshot after initialization or a measured query;
- explicit `pass`, `fail`, or `not-measured` outcomes for each optional
  operator-supplied diagnostic threshold.

Percentiles use the nearest-rank definition over the retained raw observations.

The report is canonical JSON with a deterministic content identity. The validator
rebinds it to the exact projection, receipt, shard bytes, and canonical query
set, recomputes the deterministic result-count identity from those exact inputs,
and recomputes every distribution and budget outcome. Raw query text is not
copied into the report; only the query-set byte identity and result-count
identity are retained. Validation does not authenticate the recorded timing or
memory observations: they remain diagnostic until an external controlled
evidence workflow retains or signs the exact report identity.

## Reference profile and limitations

`settlement-node-worker-reference-v1` is a repeatable production-input-format harness
profile, not the accepted browser mobile profile. It uses the exact Node
20.20.1 shard runtime, `worker_threads`, a `tsx` source loader, structured-clone
transfer, a warm local filesystem after receipt validation, and no network.
End-to-end initialization includes worker startup, source loading, byte
transfer, Brotli validation, JSON decoding, and index restoration.

The memory value is the maximum snapshot observed by the harness, defined as
V8 isolate used heap plus V8 external bytes. It is not an operating-system RSS
high-water mark. Synchronous transient allocation between snapshots may be
higher. A real browser/mobile run is therefore still required before applying
the `< 1,000 ms` initialization and `< 50 ms` query targets as release claims.
Supplying those numbers to this harness cannot satisfy those targets: every
operator threshold is labelled diagnostic and
`acceptedBrowserBudgetOutcome` remains `not-measured`.
Every report keeps `browserReferenceClaim`, `productionClaim`,
`engineSelectionClaim`, `ownerApprovalClaim`, `publicationClaim`, and
`scientificApprovalClaim` false.

## Published synthetic fixture

The repository includes one representative synthetic worker run in
`src/frontend/src/search/performance/fixtures/`. It binds the existing
synthetic settlement projection to checked-in receipt-gated shard bytes and a
canonical query set. It is schema- and identity-validated by the focused
frontend test, but is not a production-scale measurement and makes no accepted
browser/mobile budget claim. See that directory's `README.md` for its exact
inputs, limitations, and revalidation command.

## Canonical query set

The query set contains one to 100 unique, nonempty queries. Its provenance must
match both exact shards. `synthetic-fixture` is valid only with synthetic data;
real-source inputs must declare either `real-source-sample` or
`production-candidate`. `production-candidate` describes input scale and never
asserts production approval.

```json
{"corpusScale":"synthetic-fixture","dataProvenanceClass":"synthetic-fixture","queries":[{"id":"exact-name","query":"Alpha"}],"schemaVersion":1}
```

## Measure and validate

All paths must be absolute. The defaults are one build, five fresh worker
initializations, and 30 measured samples per query after one warm-up. Omitted
thresholds are written as `not-measured`; a controlled operator may supply
positive thresholds after the applicable profile and budgets are approved.
The historical v3 API uses only the projection and shard-directory inputs shown
below. The v4 API additionally requires the exact spatial database and receipt,
an isolated validation work directory, and the data release ID; the harness
forwards all four authorities through every load, timed rebuild, and worker
decode instead of coercing them into the older API.

```bash
cd src/frontend
node --import tsx scripts/measure-settlement-browser-worker.ts measure \
  --projection /absolute/search-projection.ndjson \
  --spatial-database /absolute/spatial.duckdb \
  --spatial-receipt /absolute/spatial-receipt.json \
  --validation-work-dir /absolute/private-validation-work \
  --data-release-id searise-europe-v1.0.0-YYYYMMDD-0123456789ab \
  --shard-dir /absolute/browser-shards \
  --queries /absolute/performance-queries.json \
  --report /absolute/browser-worker-performance.json \
  --build-samples 1 \
  --init-samples 5 \
  --query-samples 30 \
  --max-build-p95-ms not-measured \
  --max-init-p95-ms not-measured \
  --max-query-p95-ms not-measured \
  --max-worker-memory-bytes not-measured

node --import tsx scripts/measure-settlement-browser-worker.ts validate \
  --projection /absolute/search-projection.ndjson \
  --spatial-database /absolute/spatial.duckdb \
  --spatial-receipt /absolute/spatial-receipt.json \
  --validation-work-dir /absolute/private-validation-work \
  --data-release-id searise-europe-v1.0.0-YYYYMMDD-0123456789ab \
  --shard-dir /absolute/browser-shards \
  --queries /absolute/performance-queries.json \
  --report /absolute/browser-worker-performance.json
```

The writer requires an existing owner-controlled output directory. It writes a
private partial, verifies and syncs the exact canonical bytes, makes the report
read-only, promotes it through an atomic no-overwrite link, removes the partial,
and syncs the directory before returning success. It never replaces an existing
report. Production inputs remain read-only; timed rebuilds use private temporary
directories and are removed after exact byte comparison.
