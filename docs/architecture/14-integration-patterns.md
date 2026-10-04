# 14 — Integration Patterns

> **Status:** Implemented interfaces, reviewed 2026-10-04.
> The atlas provider and AR6 release are different integration units.

## Integration matrix

| Boundary | Contract | Failure behavior |
|---|---|---|
| Atlas UI → provider | Typed `AtlasDataSource`, optional AbortSignal | Explicit error/cancellation; no edition fallback |
| Fixture provider → authored grid | In-memory deterministic source | Out-of-extent values unknown; no network discovery |
| Real-local provider → adapter | Same-origin `/atlas-data` GET, strict JSON/PNG validation | Transport failure or invalid response, never invented scientific values |
| Node adapter → Python | Fixed loopback raster proxy, owned child process | Startup/timeout/disconnect error; child cleanup |
| Node/Python → local files | Confined manifests/index/rasters and prepared basemap | Fail startup/read on invalid identity or unsupported input |
| Projection UI → Worker | Versioned structured-clone protocol and correlation tokens | Stale results ignored; technical Worker errors remain separate |
| Projection browser → release | Manifest v2/private binding, whole files and exact ranges | Fail on identity, schema, role, media-type or integrity mismatch |
| Retained pipeline → sources | Pinned source registry and acquisition receipts | Verify before parsing/reuse; controlled retries |
| Controlled candidate → signing/readback | Versioned supply-chain and release evidence | Candidate construction does not activate a public app |

## Real-local HTTP surface

The default [HTTP provider](../../src/web/src/atlas/http-data-source.ts) uses:

| GET route | Result |
|---|---|
| `/atlas-data/manifest.json` | Sanitized `AtlasCatalogV1` |
| `/atlas-data/europe/search?q=…` | Up to 12 places and total corpus count |
| `/atlas-data/europe/place?id=…` | One place; 404 becomes `null` |
| `/atlas-data/inspect?lon=…&lat=…&defenses=…` | All three years at the exact requested point/defenses |
| `/atlas-data/tiles/{year}/{protection}/{z}/{x}/{y}.png` | PNG plus `X-Valid-Pixels` and `X-Flood-Pixels` |
| `/atlas-data/basemap/*` | Confined prepared basemap files; full or single-range GET |

The adapter is GET-only. Browser data methods use `cache: "no-store"`; private
atlas and basemap responses are `no-store`. JSON validators reject extra fields,
and inspection responses must echo exact requested coordinates and defenses.
Tile counts and PNG signature are checked before handing bytes to MapLibre.
`getPlace`'s 404 is absence; malformed successful data is a technical failure.

`createRealLocalAtlas` validates catalog/context, launches one Python process,
waits for its readiness message, then installs middleware. Proxy requests have
a 30-second timeout. Incomplete response disconnects cancel the upstream request;
completed responses do not tear down valid tile connections prematurely.
Python queues up to 64 pending connections and bounds raster work separately.

The local basemap is a visual dependency, not depth authority. Its PMTiles uses
the atlas's standard protocol and local file-delivery boundary; it is not the
manifest-authorized projection PMTiles adapter.

## Demo candidate handoff

[`scripts/demo/demo.mjs`](../../scripts/demo/demo.mjs) adds preflight, prepare and
serve boundaries around that adapter. Candidate preparation requires clean exact
source and the pinned byte-affecting runtime. It builds real-local output and
seals an app inventory plus six external metadata/receipt identities. The
candidate contains no private raster package.

Serve verifies the exact checkout, app bytes and data identities, then uses
[`sealedPreviewConfig`](../../scripts/demo/sealed-preview.mjs), with project
config and dotenv loading disabled. It attaches the atlas middleware and the
same retained release delivery middleware used by ordinary preview. Explicit
CLI paths replace `SEARISE_*`/`VITE_*` environment overrides in this workflow.
See the [candidate runbook](../operations/local-demo-candidate.md).

## Projection artifacts and Worker integration

[ManifestRepository](../../src/web/src/data/manifest-repository.ts) admits an
explicit supported browser manifest, pins `dataReleaseId` and resolves every
referenced artifact. Current schemas close objects; unknown optional fields are
not silently tolerated. A compatible source-code/contract change is required
when supported schema shape changes.

COG is scientific lookup authority; GeoParquet supplies analytical/geometry
content; PMTiles supplies visual context. Search uses verified bytes before
JSON/Brotli decoding and its own codepoint-trie Worker. The exact protocol is in
[`worker-protocol.ts`](../../src/web/src/search/worker-protocol.ts); direct
structured-clone messages, not HTTP endpoints, carry raw projection queries.

[`release-delivery-middleware.mjs`](../../src/web/scripts/release-delivery-middleware.mjs)
serves only the pinned manifest and its declared artifacts. It confines file
paths and preserves `Content-Encoding: identity` for canonical compressed
artifact bytes. GET/HEAD, 206/416 totals, type, ETag and CORS follow the
[role-specific delivery policy](../../contracts/http-delivery/v1/policy.json).
Projection visual PMTiles uses `no-store`; other eligible versioned artifacts
retain immutable delivery. Unknown release files do not become public merely
because they exist on disk.

## Ingestion and publication boundary

[`Acquirer`](../../src/pipeline/searise_pipeline/sources/acquire.py) uses
reviewed registry identities, verifies downloads/cache reuse and records receipts.
Its bounded retry loop uses exponential backoff; it does not implement the
previously documented jitter. AR6 scientific processing and settlement stages
run before candidate assembly; atlas startup consumes already provisioned data.

The offline builder can atomically assemble a local immutable candidate.
Protected workflows handle separate signing/verification evidence. No
implemented OpenTofu-managed upload-and-activate service or public atlas release
pipeline follows automatically from those tools. Future publication must bind
rights, identity, delivery and approval to the exact artifacts; see
[08](08-deployment-topology.md) and [16](16-geospatial-data-pipeline.md).
