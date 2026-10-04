# 05 — Data Architecture

> **Status:** Implemented data boundaries, reviewed 2026-10-04.
> TypeScript/Python contracts and versioned schemas are the source of truth.

## Separate data products

| Concern | Coastal atlas | AR6 projection reference |
|---|---|---|
| Browser entry contract | `coastal-atlas-browser-v1` | Browser release manifest `2.0.0` |
| Matrix | SSP585 × 3 years × 2 defense assumptions | 3 SSP scenarios × 3 horizons |
| Point values | Depth in metres: positive, valid zero, unknown | Exact AR6 q0.167/q0.5/q0.833 in integer millimetres and derived metres |
| Source resolution | 25 m CoCliCo cells in real-local; fixture only illustrates the contract | Native 1° AR6 source grid |
| Point access | Fixture grid or local Python raster read | Browser COG lookup |
| Visual layer | Provider-rendered PNG tiles | Visual-only projection PMTiles |
| Persistence | No atlas durable data store | Verified complete resources and authorized COG chunks |

Neither atlas catalog IDs nor depth values may be used as AR6 release identities
or outcomes. The retained terrain-comparison no-go is not atlas source evidence.

## Atlas browser and disk contracts

[`browser-data-contract.ts`](../../src/web/src/atlas/browser-data-contract.ts)
uses exact-field validators and immutable values for catalog, place, search,
inspection and tile counts. The catalog includes edition, bounds, source
attribution and exactly six layer identities. It contains no disk path, byte
size, checksum, or private provenance receipt.

The provisioned disk tree is read by
[`real-local-atlas.mjs`](../../src/web/scripts/real-local-atlas.mjs) and
[`real-local-context.mjs`](../../src/web/scripts/real-local-context.mjs):

```text
local-data/atlas/europe/       # ignored; can be explicitly overridden
  manifest.json              # disk v2: SSP585 / high-tide / six layers
  <manifest raster paths>    # confined source TIFFs
  context/manifest.json      # place count and exact index byte identity
  context/<index>.json.br    # prepared place records and aliases
  basemap/                   # prepared PMTiles, glyphs, sprites and metadata
```

This is a provisioned workspace, not an output automatically built by
`npm run local:start`. The adapter converts disk `high-tide` to browser
`spring-high-tide`, strips private fields, validates raster metadata/path/size,
and starts Python for full raster digest validation. The context loader verifies
the exact Brotli bytes, record count and unique place IDs before serving search.
Basemap delivery confines paths and media types; it does not use the AR6
manifest's per-artifact digest authority.

## Atlas fixture and validity

[`synthetic-fixture.ts`](../../src/web/src/atlas/synthetic-fixture.ts) contains
four example places and six 4 × 4 grids over a small Venice extent. The
[`fixture provider`](../../src/web/src/atlas/fixture-data-source.ts) samples that
same grid for point inspection and requested 256 × 256 Web Mercator PNGs.
Other searchable fixture places have unknown inspection values outside the
bounded grid; the fixture is not Europe-wide scientific coverage.

Positive cells count as flooded and valid. Zero cells count as valid but are
transparent; unknown cells are also transparent and do not count as valid.
Consequently transparency is not an availability signal. Tile response counts
must satisfy `0 <= floodPixels <= validPixels <= 65536`. Transport/read failures
are errors, not unknown cells.

## Retained AR6 release architecture

The public offline builder retains [v1 schemas](../../contracts/release/v1/).
The browser consumes the
[v2 manifest](../../contracts/release/v2/manifest.schema.json), with base-release
and browser-derivation identities, source-grid identity and COG range-integrity
metadata. [Generated contracts](../../src/web/src/contracts/generated/release-contract.ts)
and [ManifestRepository](../../src/web/src/data/manifest-repository.ts) determine
the supported browser shape. Private-engineering binding is separately validated.

The standard Vite build copies the committed v1 release fixture, then overlays
its committed v2 browser derivation at the same pinned release prefix. It
remains synthetic and pending owner disposition; a version-looking directory
name or signature-shaped fixture is not proof of a public release.

The manifest, not a hard-coded directory layout, resolves artifact paths:

| Artifact role | Implemented use |
|---|---|
| Analysis COG | Lossless three-band integer quantiles; source nodata retained |
| Projection PMTiles | Visual overlay only; no scientific lookup authority |
| GeoParquet | Exact analytical data and support/coastal geometry |
| Core/coastal search shards | Serialized codepoint-trie indexes, decoded and queried in a Worker |
| Source-grid identity and range integrity | Release-bound grid selection and authorization of exact COG chunks |
| Methodology/config/attribution | Release-scoped interpretation and source credits |
| STAC, receipts, provenance and evidence | Discovery, reproducibility and review; not a STAC server |

The settlement pipeline maintains separately versioned normalization, spatial,
reconciliation and browser-search contracts under
[`contracts/settlements`](../../contracts/settlements/). Atlas's prepared local
place index is a different shape; it is not the projection worker shard format.

## Private demo candidate identity

[`candidate.mjs`](../../scripts/demo/candidate.mjs) defines
`local-demo-candidate-v1`: exact source revision, recorded toolchain, app
inventory and six external metadata/receipt identities. Those six files are the
atlas manifest, context manifest/source receipts and three basemap receipts.
The app inventory includes sizes and SHA-256 for every regular file; symlinked
paths are rejected. Candidate bytes are made read-only after verification.

The candidate is explicitly `private-local-demo`, with
`publicPromotionAuthorized=false` and `mvpRelease=false`. It binds metadata but
does not copy private source rasters. Startup additionally verifies the actual
raster/index inputs through the adapter. This is a local handoff contract,
separate from an AR6 immutable data release or public atlas distribution.

## Retention and delivery

| Data | Storage policy |
|---|---|
| Raw sources / local atlas inputs | Ignored local or controlled build workspace; excluded from app output |
| Atlas JSON and derived tiles | `no-store` HTTP responses; Python has a bounded in-process tile cache |
| Local atlas basemap responses | `no-store`; separate from AR6 PMTiles authority |
| AR6 complete resources | Byte-verified Cache Storage admission |
| AR6 COG chunks | Bounded integrity-authorized range storage; private sessions use their separate policy |
| AR6 visual PMTiles | Network-only `no-store`, excluded from persistent and session range stores |

The [HTTP delivery policy](../../contracts/http-delivery/v1/policy.json) overrides
the generic immutable cache default for AR6 visual PMTiles. Published release
corrections require a new immutable identity; no live publication is inferred
from a local candidate. Atlas URLs contain current view/point state, while
real-local requests also carry query/point values to loopback. There is no
implemented user-account or application analytics store.

See [16](16-geospatial-data-pipeline.md) for processing and
[07](07-security-architecture.md) for trust boundaries.
