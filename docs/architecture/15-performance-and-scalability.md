# 15 — Performance and Scalability

> **Status:** Implemented controls and measurement limits, reviewed 2026-10-04.
> A limit in code is not evidence that a particular real-data deployment met it.

## Separate runtime cost models

| Mode | Critical work | Scaling limit |
|---|---|---|
| Atlas fixture | Browser UI, bounded grid sampling, PNG generation, MapLibre | Browser CPU/GPU and bundled assets; fixture does not model Europe-wide load |
| Real-local atlas | Node search and file delivery; Python point/tile reads | Local index scan, disk/raster I/O, process memory and render concurrency |
| AR6 reference | Worker search, geometry decode, COG ranges and PMTiles visuals | Artifact transfer, browser stores/memory, Worker and exact lookup |
| Offline pipeline | Verified source processing and artifact construction | Build toolchain, disk, CPU, stage receipts and controlled input volume |

Static-host scalability applies to the fixture and retained projection delivery.
It does not describe the local raster service's capacity.

## Enforced build and quality controls

[`inspect-build.mjs`](../../src/web/scripts/inspect-build.mjs) computes each
entry's initial JavaScript import graph and enforces a separate **250 KiB
Brotli** ceiling for atlas and projection. Map/Worker chunks stay outside those
initial graphs. Build finalization embeds initial CSS and deterministic
Brotli/gzip sidecars. Atlas uses system fonts; projection documents preload
their two initial Flight fonts.

The [Lighthouse runner](../../tools/static-quality/run-lighthouse-gate.mjs)
checks map health, then performs three isolated cold simulated-mobile audits of
`/`. Its target is at least 90 in performance, accessibility, best practices
and SEO for each run and their medians. It audits the atlas, not only the old
projection landing experience.

[`evaluateLighthouseBudget`](../../src/web/scripts/lighthouse-budget.mjs)
accepts raw passes before consulting any waiver. The current runner selects
[the private-local-demo policy](../../tools/static-quality/atlas-local-demo-performance-waiver.json),
which records fixture performance **54/56/54**, a floor of **50** each run,
90+ in other categories and no render errors. It applies only to labeled
synthetic-fixture evidence for the local demo, with explicit non-public/non-MVP
flags and recorded owner approval. It expires **2026-10-16 00:00 Europe/Berlin**.
The old September adoption policy is historical. Expired/invalid policies cannot
excuse lower scores, while raw all-category passes need no exception.

The [cold startup evidence](../evidence/release-candidate/cold-atlas-startup.md)
records its exact source and Linux browser profile. It is prior evidence,
not a fresh measurement from this documentation update or real-data/public
qualification. The public 90-point target is unchanged.

## Atlas implementation controls

- `AtlasApp` waits two animation frames before mounting the lazy map so controls
  can paint first; MapLibre uses a bundled same-origin worker and caps canvas
  pixel ratio at 1.5.
- `CitySearch` debounces and cancels obsolete provider requests; search returns
  at most 12 places. Real-local search scans normalized aliases in Node memory
  and sorts exact/prefix/substring matches, then population/name/ID.
- Inspection returns all three years for one coordinate/defense request.
- Map layer generations ignore stale tile status. Only the selected year and
  defenses are drawn; comparison switches years at the same view.
- Map zoom reaches 16, while flood tile zoom is capped at 13. Zoom cannot create
  sub-cell scientific detail.
- The raster HTTP listener queues up to **64** connections; this is distinct
  from actual render concurrency.
- Python bounds concurrent raster work with a semaphore of **4**, uses
  single-threaded GDAL with a **64 MiB** cache setting, and retains at most
  **256** tile results in its process-local LRU cache.
- Display tiles are 256 × 256; overview selection and nearest-neighbor warping
  reduce display work. Point inspection samples the original 25 m cell.
- Atlas JSON/tiles are `no-store`; their reuse must not be modeled as a
  persistent CDN/browser-cache optimization.

Full source digests are computed during Python startup. Those checks can be
expensive and must not be bypassed to make startup appear fast. The adapter's
startup and raster-proxy timeouts are 30 seconds; this is a local behavior,
not a latency SLA.

Source anchors: [search](../../src/web/src/atlas/CitySearch.tsx),
[local ranking](../../src/web/scripts/real-local-context.mjs),
[map style limits](../../src/web/src/atlas/basemap-style.ts),
[raster implementation](../../scripts/atlas/europe_raster_service.py).

## Projection performance scope

Projection Worker initialization, query performance and cached scientific lookup
have retained targets of <1,000 ms, p95 <50 ms and p95 <100 ms respectively.
Their evidence must identify the exact shard/release and execution profile;
Node worker measurements are not reference-mobile results. See
[worker evidence](../operations/settlement-browser-worker-performance.md) and
[lookup validation](../operations/static-scientific-lookup.md).

The exact lookup selects the nearest native AR6 location by Haversine distance
and reads three integer quantiles. It does not map binary raster classes 0/1
to exposure. The range store authorizes complete digest-bound COG chunks, then
serves eligible slices; network volume is not necessarily one tiny pixel read.

Core/coastal shard loading, lazy Brotli decoding and bounded range storage limit
work. Visual PMTiles uses network-only `no-store`; its immutable URL does not
permit assuming a persistent tile cache. Offline claims apply only to admitted
resources and warmed chunks.

## Measurements still needed

Public atlas qualification needs cold startup, local/source preparation time,
search latency on the full index, raster inspection/tile throughput, memory,
transfer and public-host measurements. Record edition, revision, data identity,
cache state, browser/hardware and failures. Do not extrapolate a fixture or
loopback result into public mobile capacity.

No installed cloud cost model or provider allowance is established by source.
Future hosting estimates must use measured bytes/operations and dated provider
inputs. Reproducible AR6 stages and source-cache reuse reduce build work; they
are separate from the provisioned atlas and its request-time raster processing.
