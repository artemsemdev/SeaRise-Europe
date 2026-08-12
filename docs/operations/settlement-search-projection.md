# Settlement search projection

`searise_pipeline.settlements.search_projection` converts one verified spatial-stage DuckDB database and its canonical receipt into a bounded-memory NDJSON artifact for a static browser search worker. It is a serializer and validator only: it does not publish an artifact, select a browser search engine, benchmark browser behavior, or make production, scientific, owner, hazard, canonical-geometry, or publication claims.

The artifact has one canonical JSON value per line, in this exact order:

1. A `settlement-search-projection-header` binds the SHA-256 of the exact spatial database and receipt, the spatial candidate identity, schema version, provenance, geometry status, and explicit false approval, production, signing, and publication claims.
2. Zero or more strictly ascending `settlement-search-projection-document` records. Each preserves the normalized source spelling, canonical and alternate spelling metadata, country and administrative context, location, population, feature code, source update date, lineage, and spatial membership/distance context.
3. A `settlement-search-projection-footer` binds the count, canonical document-stream SHA-256, and deterministic artifact identity.

The serializer opens only descriptor-bound regular files, snapshots inputs into a private work directory, checks source receipt/database reconciliation, and makes single-pass scans of each spatial stage table in its materialized numeric GeoNames order. It fails closed if physical storage order drifts, avoiding full-corpus global sort state while preserving exact receipt counts, hashes, and row semantics. DuckDB external spilling is disabled because its macOS runtime cannot traverse a held directory descriptor; memory pressure therefore fails closed instead of resolving an attacker-replaceable temporary path. The serializer refuses output overwrite and does not promote its staged output until all source and database authorities close successfully. The validator repeats the source checks and streams artifact records in lockstep with the exact spatial source, rejecting symlinks, path replacement, truncation, duplicate or unstable ordering, noncanonical JSON, source binding drift, and footer tampering.

The output is deliberately an internal pre-publication contract. A reviewed browser-index stage may map these records to a versioned shard format, but must retain this source binding and must not infer approval or publication eligibility from it.

## Browser shard candidates

`src/frontend/scripts/build-settlement-search-shards.ts` converts an exact
projection into `europe-core.codepoint-trie.json.br` and
`europe-coastal.codepoint-trie.json.br`. The build is bound to the official
Node 20.20.1 binary profile: Brotli 1.1.0, zlib 1.3.1-e00f703, ICU 78.2, and
Unicode 17.0. This exact profile is shared by the official Linux and macOS x64
and arm64 distributions; repackaged Node builds with different embedded
libraries are rejected. Validation rebuilds both the exact trie payload and
byte-identical quality-11 Brotli text compression. The envelopes bind
the exact projection byte hash, projection footer identity, spatial database,
spatial receipt, and spatial candidate. They retain false production, signing,
publication, owner, scientific, hazard, and canonical-geometry claims.
Each compressed payload implements the public settlement v4 search contract,
without altering the fixture-only v3 envelope. The caller must provide the
exact spatial DuckDB database, canonical receipt, private validation work
directory, and an explicit `dataReleaseId`. Before building any shard, the
builder invokes the pinned Python projection validator. That validator opens
descriptor-safe snapshots, reconciles the database with the receipt, and
replays every projection document in lockstep. Its canonical authority commits
the projection bytes, document identity, counts, release, source, and geometry;
same-count substitutions therefore fail closed. The builder also verifies the
receipt byte hash and candidate identity already bound by the projection,
derives the three geometry identities from that authority, and
places the same release, provenance, spatial, source, engine, runtime, ranking,
merge, and compression identities in both shards and the receipt-last set.

Projection input must be canonical, duplicate-free NDJSON with the exact nested
name, location, lineage, and spatial-classification shapes. Records remain in
ascending numeric GeoNames ID order. The core shard loads first; a consumer
appends only previously unseen coastal results, preserving each shard's
deterministic rank and deduplicating solely by `placeId`. Package,
serialization, runtime, format, source, ordering, membership, record, index, or
compressed-byte drift fails closed. Projection, line, record, raw shard,
compressed shard, query, and search-candidate limits are hard upper bounds.
The parser also retains the producer's exact source identities, lineage order,
calendar dates, feature-code set, source/canonical-name relationship,
language/script metadata, geometry status, and spatial-stage version. Empty
membership remains valid for an internal audit record, but such a record is not
written to either browser shard.

The pinned 2026-08-10 source scan observed maximum source/ASCII and alternate
name lengths of 180 and 200 Unicode code points, respectively, at most 835
alternate rows for one place, and at most 7,354 aggregate alternate-name code
points for one place. The browser boundary deliberately rounds these upward to
256 code points per name, 1,024 alternates, and 16,384 aggregate name code
points per record. A query is limited to 256 source and 1,024 normalized code
points. Full-name exact, qualified-context, prefix, and Unicode-code-point
Levenshtein-distance-two retrieval shares the ranker's normalization and hands
at most the globally best 128 candidates under that exact rank order to the
public helper. Trie cells, edges, and postings share a
250,000-unit traversal-work limit before any unbounded match map can form, and
the public search helper returns at most 100 results.

Because every accepted alternate name is indexed, one shard trie spans many
writing systems. The fuzzy walk therefore prunes each subtree before it opens
it, using two admissible lower bounds on the remaining edit distance: the
longest name under the node, and the union of the code points that appear in
those names, folded into a 64-bucket signature. A subtree is skipped when the
query is longer than its longest name plus the allowance, or when more query
positions than the allowance use a code point the subtree never contains. Both
bounds can only understate the true distance, so pruning never removes a match;
they cut the query-independent shallow traversal that would otherwise exhaust
the work limit on the production shards. The walk is also skipped outright once
the exact, qualified, and prefix passes have filled the candidate set, because
every fuzzy match ranks below all three. The traversal-work limit itself is
unchanged and remains part of the receipt-bound shard semantics. Source spelling is checked
against the producer-emitted NFC
canonical spelling; producer-emitted script metadata is consumed without a
second, runtime-divergent Unicode classifier. These are versioned safety bounds,
not claims about GeoNames completeness.

```bash
cd src/frontend
node --import tsx scripts/build-settlement-search-shards.ts build \
  --projection /absolute/search-projection.ndjson \
  --spatial-database /absolute/spatial.duckdb \
  --spatial-receipt /absolute/spatial-stage.receipt.json \
  --validation-work-dir /absolute/private-validation-work \
  --data-release-id searise-europe-v1.0.0-20260812-0123456789ab \
  --output-dir /private/output
node --import tsx scripts/build-settlement-search-shards.ts validate \
  --projection /absolute/search-projection.ndjson \
  --spatial-database /absolute/spatial.duckdb \
  --spatial-receipt /absolute/spatial-stage.receipt.json \
  --validation-work-dir /absolute/private-validation-work \
  --data-release-id searise-europe-v1.0.0-20260812-0123456789ab \
  --output-dir /private/output
```

On macOS or Linux with Python 3.9 or newer, the builder performs stable
descriptor-bound reads, bounded Brotli decompression, exclusive descriptor-
relative staging, and no-overwrite promotion through a held owner-controlled
output directory. Cooperating helper processes take a nonblocking directory
lock; the operational boundary is an isolated owner-controlled directory with
no uncooperative same-UID writer.
It preflights the complete three-name inventory before payload I/O, syncs both
final single-link shards, and validates those names together with the staged
receipt before atomically promoting and syncing
`settlement-browser-search-shards.receipt.json` as the canonical completion
marker. Cleanup never unlinks or restores a pathname: one atomic no-overwrite
rename quarantines whatever inode occupies an owned name under a high-entropy
diagnostic name. A foreign inode is preserved and no helper placeholder ever
occupies a public final name. Every created staging entry is registered before
payload I/O, so one invocation leaves at most one diagnostic entry per staged or
promoted artifact; retries against an unchanged existing final name stage
nothing. Rollback preserves the primary failure, retries transient quarantine
errors, and attempts every remaining cleanup. Once the receipt rename and root
sync complete, descriptor-close errors are cleanup-only and cannot reverse the
reported commit outcome.

Consumers must treat the set as absent until that exact receipt exists. Use
`loadBrowserSearchShards` for the receipt-gated handoff: it opens the output root
component by component without following symlinks, reads the receipt first,
reads both exact single-link shards through that descriptor, rereads the receipt
last, then performs a final all-descriptor, all-path, and output-root identity
pass. Successful publication and loading are point-in-time linearized at that
final pass; they are not a lease on paths after the function returns.
Downstream code must use those returned objects rather than reopen artifact
paths. Supplying a different release ID or receipt produces a different exact
set and cannot validate an existing set. The standalone decoder also requires
the caller's complete expected release, provenance, source, and spatial
authority; self-asserted hashes inside a recompressed shard are insufficient.
These artifacts do not provide the Web Worker, production-scale
benchmarks, or publication approval required by the consumer frontend issue.

The [settlement browser-worker performance harness](settlement-browser-worker-performance.md)
can bind these exact receipt-gated bytes and measure production-sized inputs on
its documented Node worker reference profile. It deliberately remains separate
from real browser/mobile promotion evidence.

The receipt is a first-class candidate artifact at
`search/settlement-browser-search-shards.receipt.json`. It follows the two shard
entries in write order and is included in the exact artifact and checksum
inventories; omitting it or treating it as an unlisted extra fails the candidate
byte gate.
