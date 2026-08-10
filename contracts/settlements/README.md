# Settlement artifact contracts

[`v2`](v2/) defines the public record and artifact-envelope contracts for the
European settlement catalogue. It is separate from `contracts/release/v1` so
the already published release-v1 validation meaning remains immutable.

The v2 record adds exact source spelling, per-record lineage, and language and
script metadata. The committed envelopes are representative synthetic
goldens: they define deterministic GeoParquet and search-shard boundaries but
are not production-scale evidence and do not select the final browser search
engine.

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
