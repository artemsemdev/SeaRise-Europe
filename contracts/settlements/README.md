# Settlement artifact contracts

[`v2`](v2/) defines the public record and artifact-envelope contracts for the
European settlement catalogue. It is separate from `contracts/release/v1` so
the already published release-v1 validation meaning remains immutable.

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
is local engineering evidence, not a finished settlement catalogue,
GeoParquet/search-shard build, performance result, or publication approval.

The immutable `catalogue-policy-v1.json` references the reviewed
`settlement-normalization-v2` name policy without changing its bytes. The pure
catalogue domain admits only feature class `P` and its exact populated-place
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

This domain intentionally has no Europe/coastal spatial classification,
DuckDB/toolchain binding, GeoParquet/search-shard serialization, or performance
claim. Those remain later slices.

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
The JSON Schema enforces the latter; both consumer parity suites enforce the
cross-field count, which JSON Schema cannot express.

Every artifact envelope carries geography status separately from source
provenance. The current goldens are explicitly a
`selected-scope-approximation` and are never publication eligible. A reviewed
replacement requires a new immutable artifact and contract-compatible status.
