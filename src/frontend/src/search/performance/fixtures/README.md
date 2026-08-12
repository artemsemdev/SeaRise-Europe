# Synthetic browser-worker performance fixture

This directory publishes a representative, receipt-bound **synthetic** run of
the `settlement-node-worker-reference-v1` harness. It is a fixture for the
public settlement browser-shard input format; it is not production-scale
performance evidence and does not make an accepted browser/mobile budget
claim.

The report binds the checked-in canonical query set and the exact compressed
shard bytes in `browser-shards/`. The immutable predecessor projection is kept
beside the report as `projection.v3.synthetic.ndjson`, so the v3 shard source
binding remains independently verifiable after the current contract advances.
Its shard receipt and both Brotli streams are validated byte-for-byte by the
focused frontend test before the report is accepted.

All thresholds in the report are deliberately `not-measured`. Its Node worker
timings and sampled V8 memory are diagnostic observations only. The report's
false browser, production, engine-selection, owner-approval, publication, and
scientific-approval claims are part of the validated envelope.

## Revalidation

Use the official pinned Node `20.20.1` binary profile declared in
`src/frontend/package.json`: Brotli `1.1.0`, zlib `1.3.1-e00f703`, ICU `78.2`,
and Unicode `17.0`. A repackaged Node build that reports different embedded
libraries is intentionally rejected. All paths below are absolute.

```bash
cd src/frontend
node --import tsx scripts/measure-settlement-browser-worker.ts validate \
  --projection /absolute/path/to/src/frontend/src/search/performance/fixtures/projection.v3.synthetic.ndjson \
  --shard-dir /absolute/path/to/src/frontend/src/search/performance/fixtures/browser-shards \
  --queries /absolute/path/to/src/frontend/src/search/performance/fixtures/performance-queries.synthetic.json \
  --report /absolute/path/to/src/frontend/src/search/performance/fixtures/browser-worker-performance.synthetic.json
```

The validation confirms the canonical report schema, deterministic identity,
query result-count identity, and exact receipt/shard input identities. It does
not rerun or authenticate timing observations.

The successor v4 shard contract keeps this checked-in v3 fixture byte-exact for
historical validation. New v4 measurements additionally require absolute
`--spatial-database`, `--spatial-receipt`, and `--validation-work-dir` paths plus
the exact `--data-release-id`. Those inputs are replayed before shards are
loaded, rebuilt, or transferred to the worker.

```bash
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
