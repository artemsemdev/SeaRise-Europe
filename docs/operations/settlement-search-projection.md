# Settlement search projection

`searise_pipeline.settlements.search_projection` converts one verified spatial-stage DuckDB database and its canonical receipt into a bounded-memory NDJSON artifact for a static browser search worker. It is a serializer and validator only: it does not publish an artifact, select a browser search engine, benchmark browser behavior, or make production, scientific, owner, hazard, canonical-geometry, or publication claims.

The artifact has one canonical JSON value per line, in this exact order:

1. A `settlement-search-projection-header` binds the SHA-256 of the exact spatial database and receipt, the spatial candidate identity, schema version, provenance, geometry status, and explicit false approval, production, signing, and publication claims.
2. Zero or more strictly ascending `settlement-search-projection-document` records. Each preserves the normalized source spelling, canonical and alternate spelling metadata, country and administrative context, location, population, feature code, source update date, lineage, and spatial membership/distance context.
3. A `settlement-search-projection-footer` binds the count, canonical document-stream SHA-256, and deterministic artifact identity.

The serializer opens only descriptor-bound regular files, snapshots inputs into a private work directory, checks source receipt/database reconciliation, and streams rows in numeric GeoNames order. DuckDB external spilling is disabled because its macOS runtime cannot traverse a held directory descriptor; memory pressure therefore fails closed instead of resolving an attacker-replaceable temporary path. The serializer refuses output overwrite and does not promote its staged output until all source and database authorities close successfully. The validator repeats the source checks and streams artifact records in lockstep with the exact spatial source, rejecting symlinks, path replacement, truncation, duplicate or unstable ordering, noncanonical JSON, source binding drift, and footer tampering.

The output is deliberately an internal pre-publication contract. A reviewed browser-index stage may map these records to a versioned shard format, but must retain this source binding and must not infer approval or publication eligibility from it.

## Browser shard candidates

`src/frontend/scripts/build-settlement-search-shards.ts` converts an exact
projection into `europe-core.minisearch.json.br` and
`europe-coastal.minisearch.json.br`. Both artifacts use the lock-pinned
MiniSearch 7.2.0 `minisearch-json-v1` serialization and fixed Brotli text mode
at quality 11; validation recompresses the raw bytes with those exact parameters
and requires byte identity. Their envelopes bind the exact projection byte hash, projection
footer identity, spatial database, spatial receipt, and spatial candidate.
They retain false production, signing, publication, owner, scientific, hazard,
and canonical-geometry claims.

Records remain in ascending numeric GeoNames ID order. The core shard loads
first; a consumer appends only previously unseen coastal results, preserving
each shard's deterministic rank and deduplicating solely by `placeId`. A
package, serialization, format, source, ordering, membership, record hash, or
compressed-byte mismatch fails closed.

```bash
cd src/frontend
node --import tsx scripts/build-settlement-search-shards.ts build \
  --projection /absolute/search-projection.ndjson --output-dir /private/output
node --import tsx scripts/build-settlement-search-shards.ts validate \
  --projection /absolute/search-projection.ndjson --output-dir /private/output
```

The builder performs stable descriptor-bound reads, bounded Brotli decompression,
exclusive inode-checked staging, and no-overwrite promotion through a held output
directory identity. It links both shards first, links
`settlement-browser-search-shards.receipt.json` last as the canonical completion
marker, syncs the directory, and rechecks every final inode and byte. Consumers
must treat the set as absent until that exact receipt exists; the validator refuses
missing, incomplete, or projection-mismatched receipts and shard pairs. The
buffer-level decoder assumes this set-level receipt gate has already passed.
These candidate
shards do not provide the Web Worker, browser loading, production-scale
benchmarks, or publication approval required by the consumer frontend issue.
