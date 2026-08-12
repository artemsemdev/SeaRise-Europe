# Settlement artifact contracts

[`v2`](v2/) defines the first public record and artifact-envelope contracts for
the European settlement catalog. It is separate from `contracts/release/v1` so
the already published release-v1 validation meaning remains immutable.

[`v3`](v3/) is the compatible successor for spatially classified settlement
audit records, GeoParquet envelopes, search-shard envelopes, and settlement
reconciliation evidence. It preserves
the v2 meanings of stable GeoNames IDs, source spelling, canonical and
alternate names, country and admin context, WGS84 coordinates, population,
feature codes, source update dates, and per-record lineage. The checked-in v2
files remain byte-for-byte unchanged.

[`v4`](v4/) is the public browser-search successor. It does not change the v3
representative serializer. V4 instead identifies the exact
`searise-codepoint-trie` envelope and receipt-last two-shard set, including the
release ID, spatial/source provenance, geometry identities, runtime, ranking,
merge, and Brotli semantics consumed by the browser loader. Unknown versions,
engines, source receipts, release IDs, and set members fail closed. Its checked-
in examples and implementation retain false production, approval, signing, and
publication claims.
The v4 projection-authority receipt can be emitted only after the pinned Python
validator replays the canonical projection against its exact descriptor-safe
spatial database and receipt snapshots.

Compatibility is version-aware, not wire-level substitution. A v3 document
does not validate against a v2 schema, and a v2-only consumer must reject it
instead of dropping unknown fields. Consumers must dispatch on the exact
`$schema`, `schemaVersion`, artifact `formatVersion`, and search-engine
serialization identity. Consumers must apply both JSON Schema validation and
the matching shared semantic validator; schema validation alone cannot enforce
cross-field counts. Producers that move to v3 must emit a complete v3 record
or envelope; they must not mix v2 and v3 fields in one document.

V3 closes the public boundary that v2 intentionally left incomplete:

- `recordRole` distinguishes source-audit records from search-shard records;
  source-audit records may retain an empty `catalogMembership`, while shard
  records require at least one membership.
- Canonical and alternate names carry explicit, noninterchangeable roles.
- Support, coastal-zone, and shoreline identities bind artifact ID, version,
  and SHA-256 together with the `covers` predicate and the exact distance
  method.
- Coastal distance is a required nonnegative whole-meter integer, and
  `sourceUpdatedAt` is a required non-null source date.
- GeoParquet fields carry the same source and spatial identity, while search
  documents expose the required feature code and coastal distance.
- The representative search serializer advances to format `2.0.0` and
  serialization version `2`; it remains fixture-only and does not select the
  production browser engine.
- Approximate geometry cannot claim canonical geometry, hazard extent,
  scientific approval, owner approval, publication eligibility, or any other
  status that the reviewed source does not grant.

The v2 record adds exact source spelling, per-record lineage, and language and
script metadata. The committed envelopes are representative synthetic
goldens: they define deterministic GeoParquet and search-shard boundaries but
are not production-scale evidence and do not select the final browser search
engine.

The internal producer policy is versioned as
`src/pipeline/settlements/normalization-policy-v2.json`. The provider
`allCountries.name` remains canonical; current language names are NFC-preserved,
ISO-validated, script-tagged, and deduplicated by NFC casefold. Selected
alternate records retain their exact source line and `alternateNameId` so the
eventual `Place.lineage` can bind every contributing name. Non-language
namespaces, historic or inactive names, empty values, unparseable periods, and
unsafe provider controls are retained in raw scan counts but excluded from
normalized search names.

The exact 2026-08-10 offline scan covers 19,037,112 alternate-name and 7,929
ISO-language rows with zero unexplained parser or language-policy failures. It
is local engineering evidence, not a finished settlement catalog,
GeoParquet/search-shard build, performance result, or publication approval.

The internal shoreline producer policy is versioned separately as
`src/pipeline/settlements/shoreline-distance-policy-v1.json`. It selects whole
Natural Earth source `LineString` features intersecting the Europe build bounds
from the exact main and minor-island archives; it never clips lines or derives
shoreline from administrative, ocean-polygon, coastal-zone, or bounding-box
edges. Settlement distance uses longitude-latitude input transformed to
EPSG:3035 by pinned DuckDB Spatial before planar `ST_Distance` in meters. The
computed `DOUBLE` is persisted as whole-meter `BIGINT` with DuckDB's
nearest-half-to-even cast; generalized Natural Earth linework carries no false
sub-meter precision. `isCoastal` remains a separate `ST_Covers` classification
against the versioned 25 km zone and is not inferred from that distance. The
checked-in linework and QA evidence are product-eligibility engineering inputs
only: they carry no hazard-extent, canonical-coastline, owner-approval, or
publication claim.

The immutable `catalogue-policy-v1.json` references the reviewed
`settlement-normalization-v2` name policy without changing its bytes. The pure
catalog domain admits only feature class `P` and its exact populated-place
code allowlist; historic, abandoned, and destroyed codes such as `PPLH`,
`PPLQ`, and `PPLW` remain excluded. Canonical names containing C0, DEL, or C1
controls are rejected. IDs are derived only as `geonames:<geonameId>`,
coordinates preserve the finite WGS84 source values without rounding, and
output and rejection-ledger order is numeric GeoNames ID.
Admin1 is joined by `(countryCode, admin1Code)`: a provider-missing code yields
null code/name, while an unresolved nonempty code is preserved with a null name
and an explicit context notice/count. Duplicate place IDs or admin join keys,
wrong alternate-name bindings, and buckets without a corresponding place fail
the whole normalization. Lineage order is the place row, matched admin1 row,
then selected alternate-name rows.

This internal slice adds deterministic Europe/coastal classification over
the pure catalog. Support and 25 km coastal membership use `ST_Covers`;
distance transforms the point and a separately identified shoreline from
EPSG:4326 to the EPSG:3035 metric plane with explicit XY axis order before
`ST_Distance`; DuckDB then casts its `DOUBLE` result to `BIGINT`, persisting
whole meters with nearest-half-to-even semantics under internal method version
`epsg3035-planar-whole-meter-half-even-v1`. The support boundary and 25 km zone
boundary are prohibited shoreline substitutes. Every fixture geometry binds
its role, version, hash, path, and predicate, while the executable evidence
remains a hash-bound European synthetic fixture,
`selected-scope-approximation`, non-publication, and without an owner-approval
claim. Production classification fails with `shoreline-geometry-unavailable`
until a separate reviewed wiring change binds the pinned shoreline policy and
artifact to the classifier.

This classified output is an internal audit model, not a Place v2 producer.
Support-covered records are retained even when they belong to no browser
shard: `europe-core` requires population >= 500 or feature code `PPLC`, `PPLA`,
`PPLA2`, `PPLA3`, `PPLA4`, or `PPLA5`, while `europe-coastal` depends only on
coastal coverage.

A successor versioned public contract was required because Place v2 requires
at least one `catalogMembership` item and its mandatory distance cannot bind a
`shorelineGeometryVersion` or `distanceMethodVersion`. V3 satisfies that
boundary without changing v2 and makes no full-source, benchmark, production
search-engine, or publication claim.

Consumers support exact `schemaVersion`, artifact `formatVersion`, and search
engine serialization identities. An unknown value is an unsupported artifact;
consumers must not coerce it into a known format.

`lexicographic-key-json-v1` defines the `arrowFields` hash preimage exactly:
encode the array as UTF-8 JSON; preserve array order; sort every object's ASCII
property names in ascending byte order; emit no insignificant whitespace; use
JSON double-quoted ASCII strings and lowercase `true`/`false`; and do not append
a newline. The SHA-256 field hashes those bytes, not an Arrow FlatBuffer.

Search `recordCount` must equal the number of `documents`. A
`europe-coastal` shard may contain only documents whose `isCoastal` is `true`.
The JSON Schema enforces the latter. Python consumers must also call
`validate_settlement_search_shard_semantics`, and TypeScript consumers must
call `validateSettlementSearchShardSemantics`, to enforce the cross-field
count that JSON Schema cannot express.

The v3 reconciliation report binds the exact normalized-catalogue and spatial
database/receipt pairs. Its flow deliberately has two equations:
`sourcePlaceRows = catalogueAccepted + catalogueRejected`, followed by
`catalogueAccepted = spatialClassified + spatialRejected`. Pre-spatial
catalogue rejections therefore cannot be mistaken for records evaluated by
geometry. Country, feature class/code, population band, and coastal-status
buckets count normalized places; language and script buckets count selected
normalized canonical and alternate names. Every bucket preserves classified
and spatial-rejected subtotals. Consumers must apply
`validate_reconciliation_report_semantics` after JSON Schema validation to
enforce arithmetic, order, rejection totals, deterministic identity, and
claim boundaries.

Every artifact envelope carries geography status separately from source
provenance. The current goldens are explicitly a
`selected-scope-approximation` and are never publication eligible. A reviewed
replacement requires a new immutable artifact and contract-compatible status.
