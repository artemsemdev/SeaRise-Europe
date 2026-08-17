# Static settlement search operations

This runbook covers the release-scoped GeoNames settlement search used by the
static browser application. Search is a navigation aid, not a scientific
outcome. Selecting a result supplies its exact source coordinates to the
assessment flow; it does not classify exposure or make a flooding, inundation,
probability, property-risk, or terrain claim.

## Release contract

The pinned manifest must contain two immutable artifacts with role
`settlement-search-index`:

| Artifact ID | Shard | Load order |
|---|---|---|
| `settlements-europe-core` | `europe-core` | First; enables partial-ready search |
| `settlements-europe-coastal` | `europe-coastal` | Second; expands the same result set |

Each artifact authority carries its release ID, provenance class, exact byte
size, SHA-256 digest, and release-scoped URL into the Worker. The client never
constructs a storage-provider path. It rejects an absent role, cross-release
identity, unsafe origin, wrong size, or digest mismatch as a technical error.
After decompression, the Worker validates the authoritative
`contracts/settlements/v4/search-artifact.schema.json` contract and its exact
release/provenance, source, spatial, geometry, records SHA-256, index binding,
compression, runtime, ranking, and merge identities. Core and coastal must
share one common identity; overlapping GeoNames IDs must have byte-equivalent
canonical records.

The committed release is deliberately synthetic and reproducible. Regenerate
or verify its two fixtures from the repository root:

```bash
npm run generate:search-fixture --workspace @searise/web
npm run check:search-fixture --workspace @searise/web
```

### Production shard build

The static target owns the production builder in
`src/web/scripts/search-shard-builder.mjs`; it does not call or import the
legacy Next.js runtime. First produce the projection-authority JSON with
`scripts/release/validate_settlement_search_projection.py`. That Python
authority is the replay proof for the exact spatial database, spatial receipt,
projection bytes, record count, source identities, release ID, and three
geometry identities. Then build into a new, owner-controlled directory:

```bash
mkdir -m 700 /absolute/output/search
npm run build:search-shards --workspace @searise/web -- \
  --projection /absolute/input/settlement-search-projection.ndjson \
  --projection-authority /absolute/input/settlement-search-projection-authority.json \
  --spatial-database /absolute/input/spatial.duckdb \
  --spatial-receipt /absolute/input/spatial-receipt.json \
  --validation-work-dir /absolute/private/replay-work \
  --data-release-id searise-europe-v1.2.3-YYYYMMDD-0123456789ab \
  --output-dir /absolute/output/search
```

The production CLI reruns the Python validator and requires its stdout to equal
the supplied authority byte-for-byte; a self-consistent but unvalidated
authority is insufficient. The builder also rechecks the canonical bounded
projection and the authority's self-hash before producing either shard. It
emits the exact v4 code-point trie format accepted by the production Worker
decoder, with canonical numeric GeoNames order and the pinned runtime/ranking
identity. Quality-11 Brotli bytes are deterministic only under the pinned Node
runtime recorded in the artifact.

Publication refuses existing names, symlink directories, path escape, and
non-owner-controlled output. Each file is staged and synced, then promoted by
an exclusive hard link; the receipt is the final completeness marker. A failed
promotion removes only inodes owned by that invocation, so a retry starts from
an empty public set. Validate the exact set without overwriting it:

```bash
npm run validate:search-shards --workspace @searise/web -- \
  --projection /absolute/input/settlement-search-projection.ndjson \
  --projection-authority /absolute/input/settlement-search-projection-authority.json \
  --spatial-database /absolute/input/spatial.duckdb \
  --spatial-receipt /absolute/input/spatial-receipt.json \
  --validation-work-dir /absolute/private/replay-work \
  --data-release-id searise-europe-v1.2.3-YYYYMMDD-0123456789ab \
  --output-dir /absolute/output/search
```

Candidate-v7 may be supplied only through the documented ignored, read-only
local path. Neither this command nor CI discovers, copies, uploads, or publishes
Candidate-v7 or its TAR.

The generator covers canonical and alternate spellings, diacritics,
transliteration, duplicate names with country/admin context, inland and coastal
places, zero population, and a transcontinental boundary case. It writes four
core records (2,118 compressed bytes) and three coastal records (2,025
compressed bytes), including one deliberate cross-shard duplicate used to
prove stable-ID de-duplication. JSON keys, postings, checksum inputs, and
fixture path inventories use one explicit Unicode code-point comparator.

## Browser lifecycle and privacy

1. Focusing or typing in the combobox starts a lazy module Worker.
2. The Worker fetches the core artifact, verifies its exact transport bytes,
   decodes and validates the shard contract, and returns `core-ready`.
3. The client immediately starts the coastal load. Queries can run against the
   core shard while that load is pending.
4. Every request has a monotonically increasing token. Query results and query
   failures are accepted only for the current query token. Coastal-load
   failures are tracked independently, so an older load token cannot disappear
   behind a newer successful core query.
5. Results follow the v4 merge contract: ranked core results first, then unseen
   ranked coastal results, de-duplicated by stable GeoNames place ID. No global
   cross-shard reranking is permitted.
6. Unmount or release replacement sends `terminate`, terminates the Worker,
   clears listeners, and drops the in-memory query.

The raw query exists only in component/client/Worker memory. It is never added
to a URL, request path, request body, analytics event, log, local storage,
session storage, IndexedDB, or cache key. Network requests contain only the two
pinned artifact URLs. A no-match response is distinct from artifact, integrity,
decode, browser-support, or Worker failures.

The accessible UI follows the ARIA combobox/listbox pattern. Arrow keys,
Home/End, Enter, and Escape work without moving focus from the text field;
duplicate place names always expose country and first-level administration.
Changing the query clears and unbinds prior results synchronously. Enter,
Explore, and option clicks cannot select an old result while a new query is
pending or after it fails.

## Exact compressed transport

Search shards are stored as `.codepoint-trie.json.br`. The Worker verifies the exact
compressed byte size and SHA-256 before decoding them with pinned
`brotli-wasm@3.0.1`. Generic static hosting must therefore serve those object
bytes unchanged and must not apply `Content-Encoding: br` in a way that causes
the browser to return decompressed bytes to `fetch`. Such a transformation is
detected as `IntegrityFailed` before decode. The repository's static preview
sets `Content-Encoding: identity` so its generic-server validation preserves
the stored `.br` object bytes; production object metadata must provide the same
opaque-byte behavior.

The Brotli decoder is lazy with the search Worker. The current production build
contains a 1,056.86 KiB raw / 575.35 KiB gzip WASM asset and a 33.96 KiB raw
Worker chunk; neither appears in the initial HTML dependency graph. The build
inspector records both under `lazyWorkerAssets` in `dist/build-report.json`.

The checked static pages use `script-src 'self' 'wasm-unsafe-eval'`, never
`'unsafe-eval'`. The [CSP Level 3 WebAssembly integration
rule](https://www.w3.org/TR/CSP/#wasm-integration) defines this narrow source as
permission for WebAssembly compilation without permitting JavaScript `eval()`
or `Function()`. The exact meta policy is a build invariant, and Playwright
loads a real compressed shard through the real Worker/WASM decoder while a
self-hosted probe proves dynamic JavaScript remains blocked. If a target
browser cannot instantiate the pinned decoder under that policy, search fails
closed as `UnsupportedBrowser`; it does not switch to an unpinned decoder or a
server endpoint. Native `DecompressionStream('brotli')` is not used because it
is not yet an established cross-target baseline.

## Validation

Run the deterministic target gates from the repository root:

```bash
npm ci
npm run test:search-shard-builder --workspace @searise/web
npm run web:check
npm run web:e2e
npm audit --audit-level=high
python scripts/tests/validate_test_inventory.py
python -m unittest discover -s tests/harness -p 'test_*.py'
```

The unit and browser suites cover normalization and ranking, exact and alternate
names, bounded fuzzy matching, stable IDs and coordinates, core-first readiness,
cross-shard de-duplication, stale selection prevention, independent coastal
failure tokens, cancellation, Worker teardown, integrity-before-decode, full
v4 identity and Brotli payloads, malformed data,
unsupported decode runtime, no-match versus technical failure, query privacy,
keyboard interaction, the exact CSP, blocked JavaScript dynamic code, and
serious/critical accessibility findings.

On 2026-08-16, Chromium over the committed synthetic fixture observed:

| Profile | Core initialization | Query p50 | Query p95 |
|---|---:|---:|---:|
| Desktop Chromium | 26.8 ms | 0.1 ms | 0.2 ms |
| Mobile Chromium emulation | 23.6 ms | 0.1 ms | 0.3 ms |

Each browser test attaches a release-scoped JSON measurement. These figures are
fixture evidence only: they are not a production-corpus performance claim, and
Worker memory is explicitly `not-measured` in this target run. Production-scale
memory and latency require a separate, explicit, read-only local run against
the ignored Candidate-v7 path. Candidate-v7 and its TAR must not be copied into
the static build, committed, sent to CI, or uploaded anywhere.

### Read-only Candidate-v7 measurement

The static target includes a local-only measurement command. It reads an
explicit candidate root in place, verifies each compressed shard against the
candidate manifest, serves the production Worker bundle and those source files
from a cross-origin-isolated loopback origin, and writes its raw report with
exclusive creation. Keep that report under `/tmp` or another ignored private
directory outside every Git worktree, the Candidate tree, and the deployable
`dist` tree. The command resolves canonical paths and rejects those locations
before it reads or opens the report path:

```bash
cd src/web
npm run build
npm run measure:local-candidate-search -- \
  --candidate-root /absolute/ignored/candidate-v7 \
  --query-set /absolute/ignored/performance-queries.json \
  --output /tmp/static-search-candidate-v7-measurement.json \
  --samples 5
```

The command uses Pixel 7 emulation and a 512 MiB Worker V8 old-space limit. It
records Chromium version, initialization and query distributions,
`performance.measureUserAgentSpecificMemory()` when available, and dedicated
Worker `Runtime.getHeapUsage` telemetry. The conservative numeric observation
adds V8 used heap, embedder heap, and backing storage, then takes the maximum
with the user-agent-specific observations. This is not device RSS and Pixel
emulation is not physical mobile hardware.

The 2026-08-16 read-only run observed 38,512,542-byte and 46,221,779-byte
decoded shards. The 64 MiB decoded ceiling therefore leaves 20,887,085 bytes
(45.2%) above the larger representative shard, while the 16 MiB compressed
ceiling leaves more than 2.8 times the larger compressed shard. Streaming
checks cumulative output before requesting another decoder allocation.

Chromium 151 produced initialization p50 439.76 ms and p95 459.89 ms across
five cold core loads, query p50 3.61 ms and p95 9.09 ms across 100
measurements, and a conservative Worker observation of 251,963,600 bytes.
The tested runtime keeps the canonical sorted entries compact, performs direct
ordinal-array lookup, and applies admissible length and signature-count lower
bounds before banded fuzzy distance. The Worker omits duplicate publisher-side
equivalence reconstruction only after the compressed artifact passes its exact
manifest size and SHA-256 authority; standalone contract tests retain the full
reconstruction path. `measureUserAgentSpecificMemory()` was unavailable, so
the numeric bound is the CDP heap/embedder/backing-storage sum, not process RSS.
Initialization passes its 1,000 ms target and query performance passes its
50 ms target. These observations are local browser acceptance evidence, not a
physical-mobile, production, publication, or scientific approval.

## Failure interpretation

Search failures use the closed technical-error vocabulary from the release
domain. They never produce or alter a scientific outcome. The scientific domain
remains exactly `ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, and
`UnsupportedGeography`.
