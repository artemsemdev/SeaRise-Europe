# Phase 0.3 regional methodology gate

> **Decision:** `blocked`
> **Measured:** 2026-08-05 (Europe/Berlin)
> **Fixture:** `north-sea-n52-e004-real-source-v1`
> **Issue:** [#47](https://github.com/artemsemdev/SeaRise-Europe/issues/47)

## Decision

Stop. Do not generate exposure classes, PMTiles, Europe-scale jobs, or public
methodology `v1.0` claims.

The pinned IPCC AR6 value is relative sea-level change from the 1995–2014
baseline. The pinned Copernicus DEM value is an absolute EGM2008 orthometric
DSM height. No reviewed local baseline sea-surface/tidal datum, transformation
to EGM2008, or uncertainty budget currently makes a direct comparison valid.
The binding source contract therefore prohibits publishing
`sea_level_change >= DEM elevation`.

This is a completed stop/go spike with a blocked result, not an implicitly
approved methodology or a failed software delivery.

## Evidence inventory

| Evidence | Location | Result |
|---|---|---|
| Scientific source decisions | [`source-semantics.json`](../../src/pipeline/science/source-semantics.json) | Datum compatibility blocked |
| Geography and connectivity decisions | [`geography-rules.json`](../../src/pipeline/science/geography-rules.json) | Approximation/reviews pending |
| Reproducible recipe | [`recipe.json`](../../src/pipeline/fixtures/regional/recipe.json) and `searise_pipeline.regional_fixture.build` | Rebuilds/validates real-source mechanics fixture |
| Build receipt and nine-layer disposition | [`build-receipt.json`](../../src/pipeline/fixtures/regional/build-receipt.json) | All nine combinations recorded as blocked |
| Shared lookup fixture | [`lookup-fixture.json`](../../src/pipeline/fixtures/regional/lookup-fixture.json) | Nine blocked layers; no class arrays |
| Shared vectors | [`golden-vectors.json`](../../src/pipeline/fixtures/regional/golden-vectors.json) | 11 mechanics-only vectors; review pending |
| Delivery measurement | [`delivery-measurements.json`](../../src/pipeline/fixtures/regional/delivery-measurements.json) | Exact COG ranges on local reference profile |
| Redistributed DEM derivative notice | [`NOTICE.md`](../../src/pipeline/fixtures/regional/NOTICE.md) | Attribution, liability, purpose, and lineage recorded |

## Real-source regional build

No synthetic scientific input is used. The build verifies and reads the exact
Copernicus DEM GLO-30 `2021_1` tile locked by #45/#46:

| Field | Value |
|---|---|
| Source asset | `Copernicus_DSM_COG_10_N52_00_E004_00_DEM.tif` |
| Source SHA-256 | `edb307664fd717ca1805e77e8e16ad3267f1992f2614b2d0127193dfdf6851f1` |
| Source bytes | 17,037,271 |
| Window | columns 544–799, rows 3112–3367; 256 × 256 native samples |
| Bounds | 4.2264583333–4.333125° E, 52.0645833333–52.1356944444° N |
| Horizontal/vertical reference | EPSG:4326 / EGM2008 (EPSG:3855) |
| Derived COG | 143,754 bytes; SHA-256 `d200cd6448fa673467068e312e1b41771c9b0e5ace5db9818f3431491d5b736a` |
| COG structure | Valid; 128 × 128 blocks; PixelIsPoint retained |
| Measured elevation range | -8.137821–32.125767 m; median 4.470796 m |
| Working arrays | 393,216 bytes |
| Build peak resident memory | 96,747,520 bytes on the recorded build profile |

The small COG is a cropped/compressed modified product, not an exposure layer.
Its required Copernicus attribution is embedded in TIFF tags and repeated in
the adjacent notice. Raw source bytes remain ignored.

## Nine-combination disposition

| Scenario | 2030 | 2050 | 2100 |
|---|---|---|---|
| `ssp1-26` | blocked | blocked | blocked |
| `ssp2-45` | blocked | blocked | blocked |
| `ssp5-85` | blocked | blocked | blocked |

Each entry carries the same exact lineage: IPCC AR6 `20210809`,
`sea_level_change`, medium confidence, quantile `0.5`, millimetres converted
with factor `0.001`, and Copernicus DEM `2021_1` metres. They are dispositions,
not completed scientific arrays. Consequently there are no nine-layer class
statistics, analysis COGs, visual PMTiles, or release manifest.

## Lookup and parity result

Python and the independent TypeScript reference reader implement:

- `[-180, 180]` longitude input with no implicit wrapping;
- north-up, row-major nearest-cell lookup;
- west/north-inclusive and east/south-exclusive grid edges;
- checksum-verified `uint8` arrays;
- explicit `255` nodata and fail-closed blocked/missing layers;
- all five domain states in contract characterization tests.

Both readers match all 11 shared real-fixture vectors exactly. Nine vectors
prove that every blocked scenario/horizon returns `DataUnavailable`; two prove
regional edge behavior. These vectors do not contain independently reviewed
`ModeledExposureDetected` or `NoModeledExposureDetected` expectations. Their
review status remains `pending`, so this evidence proves lookup mechanics, not
scientific validity.

## Delivery measurements

Reference profile: Node `v20.20.1`, Apple M1 Max, 64 GiB RAM, macOS/Darwin
25.5.0, Node fetch against a loopback HTTP/1.1 immutable static server. The
measurement runner serves the real committed COG and compares response bytes
with exact source slices.

| Request | Status | Bytes | Content-Range | Time |
|---|---:|---:|---|---:|
| Cold header `0-16383` | 206 | 16,384 | `bytes 0-16383/143754` | 39.001 ms |
| Cold tail `127370-143753` | 206 | 16,384 | `bytes 127370-143753/143754` | 4.852 ms |
| Warm header `0-16383` | 206 | 16,384 | `bytes 0-16383/143754` | 4.360 ms |

All three responses were byte-exact. Fixture parsing took 18.419 ms; 10,000
warm lookups measured median 0.000209 ms and p95 0.000500 ms.

This supports only the local reference profile's COG range mechanics. It does
not establish public-CDN latency, CORS/cache behavior, representative mobile
performance, Europe-scale request locality, or PMTiles feasibility. PMTiles
was deliberately not generated because it would require prohibited classes.

## Connectivity and controls

The candidate eight-neighbour rule is specified in #46, but no naive exposure
mask exists against which to calculate false positives. Running connectivity
on a scientifically invalid comparison would create misleading numbers.
Connectivity comparison is therefore `not run`, and its scientific review is
pending.

The selected DEM window exercises a straightforward North Sea coast. The
planned estuary/port, disconnected inland low terrain, nodata/void, steep
coast, and island control windows were not classified. No human scientific
review record exists. These are named blockers, not silently omitted controls.

## Acceptance and Definition of Done disposition

| Requirement | Disposition |
|---|---|
| No synthetic scientific input in regional build | Pass |
| All nine classifications complete | Blocked; no valid datum reconciliation |
| Python/TypeScript bit-exact scientific goldens | Blocked; mechanics-only parity passes |
| Nearest neighbour, nodata, edges, transforms, longitude | Pass for lookup contract |
| Connectivity false positives quantified | Blocked; no valid naive mask |
| COG/PMTiles size, requests, latency, memory | Partial COG reference evidence; PMTiles blocked |
| Every control reviewed | Blocked; reviewer status pending |
| Explicit methodology state | Pass: `blocked` |
| Failed gate prevents Europe-scale work | Pass: release guard raises and `unlocksPhase1=false` |
| Reproducible recipe and receipt | Pass |
| Small redistributable fixture; raw ignored | Pass |
| CI validates fixture/shared vectors | Pass in Python and frontend test suites; PR CI still required |
| Scientific review recorded | Blocked; no review event exists |

## Reproduce and validate

With the checksum-locked source present in the ignored acquisition cache:

```bash
PYTHONPATH=src/pipeline .venv/bin/python -m searise_pipeline.regional_fixture.build \
  --repo-root . \
  --fixture-dir src/pipeline/fixtures/regional \
  --dem data/raw/sources/copernicus-dem-glo30/2021_1/samples/Copernicus_DSM_COG_10_N52_00_E004_00_DEM.tif

PYTHONPATH=src/pipeline .venv/bin/python -m searise_pipeline.regional_fixture.build \
  --fixture-dir src/pipeline/fixtures/regional --validate

cd src/frontend
npx tsx scripts/measure-regional-fixture.ts ../..
```

An approved result requires new pinned/reviewed evidence, a rebuilt regional
release, independent controls, connectivity comparison, PMTiles/COG delivery
measurements, and an explicit reviewer decision. Do not change this report to
`approved` merely by editing its status.
