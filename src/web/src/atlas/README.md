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
