# Coastal atlas browser data boundary

`browser-data-contract.ts` defines the JSON values the coastal atlas may trust
after an adapter has read them. It is separate from the real-local disk
manifest. Browser catalog responses contain no filesystem path, checksum,
object-store receipt, byte size, or other private provenance field.

The public success boundary is:

- catalog: one `coastal-atlas-browser-v1` catalog, an explicit `real-local` or
  `synthetic-fixture` edition, and exactly the six combinations of 2030, 2050,
  2100 with protected and unprotected conditions;
- place search: `{ "results": AtlasPlaceV1[], "totalPlaces": number }`, with
  at most 12 unique result IDs, and a single `AtlasPlaceV1` for lookup by ID;
- point inspection: the selected coordinates, defense setting, 25 m source
  cell size, and one result for each supported year;
- raster tile metadata: `validPixels` and `floodPixels`, where flooded pixels
  cannot exceed valid pixels.

A flooded point has a finite positive `depthMeters`. A valid zero point has
`status: "zero"` and `depthMeters: 0`. An unknown point has
`status: "unknown"` and `depthMeters: null`. Unknown must never be converted to
zero. Network, decoding, and source-read failures are transport errors outside
these three data statuses.

## Deterministic fixture

`synthetic-fixture.ts` is an authored software-test input. Its source label and
catalog edition distinguish it from CoCliCo data. Its values are illustrative
and carry no scientific, publication, flood-risk, safety, or real-world
accuracy claim.

The fixture includes four coastal place records, both defense settings, all
three years, and deterministic point inspections. Six 4 by 4 source grids use
explicit `null`, zero, and positive depth cells over a small Venice extent.
Their WGS84 bounds and north-to-south row order let a later fixture adapter
georeference and resample them for requested Web Mercator tiles. Requests
outside that extent are unknown. The grids do not represent a whole-world
zoom-zero tile.

Tile image transparency cannot distinguish unknown from valid zero. The source
grid therefore remains authoritative for validity: every non-null cell counts
as valid, only a positive cell counts as flooded, and only a positive cell gets
nonzero display alpha. The fixture's declared counts describe its 4 by 4 source
grid. Tests recompute them from those cells; a later adapter must recompute
counts after resampling each requested output tile.

Runtime adapters are responsible for translating either the fixture or a
verified real-local disk manifest into these contracts. Real-local adapters
must retain paths, hashes, and source receipts on the trusted server side.
Neither this module nor the fixture activates an endpoint, map, or application
entry.

## Data sources

`AtlasDataSource` is the UI and map injection boundary. Its catalog, search,
place, inspection, and tile methods accept cancellation signals. Tile results
carry PNG bytes plus counts calculated from measurements. `AtlasDataSourceError`
represents invalid requests, unavailable transport, and invalid responses;
native `AbortError` cancellation remains unchanged. Technical failures never
become flooded, zero, or unknown point values.

`createAtlasDataSource()` selects the synthetic fixture by its explicit
`DEFAULT_ATLAS_EDITION`. Selecting `{ edition: "real-local" }` creates only the
HTTP provider for the existing `/atlas-data` routes. A missing or invalid local
service rejects the request and never falls back to fixture values.

The fixture provider performs no network or Python work. It samples the same
bounded Venice grid for inspection and tile rendering. Places outside that
grid remain searchable examples but every inspected year is unknown and their
map cells stay transparent. A deterministic 256 by 256 PNG is rendered for the
requested Web Mercator tile with the pinned flood-depth palette. Valid zero
pixels contribute to `validPixels` even though they share transparent display
alpha with unknown pixels.

## Atlas experience

Issue #501 transfers the accepted coastal atlas interface from checkpoint
`a84279a9` without its retired calculation experiment. `AtlasApp` requires one
`AtlasDataSource` and passes it to the map, city search, and point inspector.
It does not choose a provider or make direct network requests. The application
entry is responsible for selecting the edition and providing its adapter.

The model uses the strict browser catalog, place, and point contracts above;
it does not import the local disk manifest or its provenance fields. Shared
links preserve the year, defenses, overlay, comparison, city, camera, and
selected point. Retired experiment parameters are ignored and removed when
writing the current view URL.

The accepted light layout, portal search menu, mobile detail panel, timeline,
and year comparison remain in `atlas.css`. Synthetic editions show an
**Illustrative fixture** label in the header and methods dialog, with fixture
credits. Real-local editions retain CoCliCo and local geographic data credits.

Component tests inject an in-memory provider and isolate the map renderer.
They cover canceled searches and point requests, unknown versus valid zero,
exact point matching and retry, catalog retry, shared links and browser
history, timeline and comparison controls, mobile detail expansion, clipboard
fallback, and edition disclosure. Map pixels and real-local transport are
verified by their separate provider and map suites.
