# Public release contracts

The JSON Schemas in [`v1`](v1/) are the only authority for the shape of a
SeaRise Europe public data release. Architecture and delivery documents explain
why the fields exist, but must link here instead of copying field definitions.

The browser enters a release through `manifest.json` only. Static STAC is the
discovery representation; it is not a runtime API and cannot replace the
manifest. COG is the exact projection lookup artifact, GeoParquet is the exact
analytical representation, and PMTiles is visual-only.

## Version 1 catalogue

The `v1` path and every schema's `$id` identify schema version `1.0.0`.

| Contract | Authority |
|---|---|
| Release inventory and nine-dataset matrix | [`manifest.schema.json`](v1/manifest.schema.json) |
| Artifact identity, roles, rights, and scientific use | [`artifact.schema.json`](v1/artifact.schema.json) |
| Scenarios, horizons, defaults, and projection semantics | [`scenario-config.schema.json`](v1/scenario-config.schema.json) |
| Four projection result states | [`projection-result.schema.json`](v1/projection-result.schema.json) |
| Method and prohibited claims | [`methodology.schema.json`](v1/methodology.schema.json) |
| Source licences and attribution | [`attribution.schema.json`](v1/attribution.schema.json) |
| Audited offline source acquisition | [`source-receipt.schema.json`](v1/source-receipt.schema.json) |
| Reproducible build identity | [`build-receipt.schema.json`](v1/build-receipt.schema.json) |
| Local settlement search records | [`search-record.schema.json`](v1/search-record.schema.json) |
| Automated validation evidence | [`quality-summary.schema.json`](v1/quality-summary.schema.json) |
| Static-runtime and privacy evidence | [`architecture-evidence.schema.json`](v1/architecture-evidence.schema.json) |
| Static STAC 1.1.0 profile | [`stac.schema.json`](v1/stac.schema.json) |
| Mutable pointer to one immutable manifest | [`release-pointer.schema.json`](v1/release-pointer.schema.json) |
| Shared closed definitions | [`defs.schema.json`](v1/defs.schema.json) |

JSON Schema validation proves individual document shape. The Python public
contract validator additionally proves cross-document release identity,
artifact references, rights, STAC graph and asset agreement, file sizes, and
SHA-256 hashes. TypeScript AJV and Python validate the same committed positive
and negative fixtures. Browser-facing types are generated from the schemas;
`npm --prefix src/frontend run contracts:check` fails on drift.

## Version identities

Three identities are intentionally independent:

- `schemaVersion` changes when the JSON shape or validation vocabulary changes;
- `methodologyVersion` changes when scientific meaning, lookup, source
  interpretation, or prohibited claims change;
- `dataReleaseId` identifies one immutable set of bytes built with one exact
  schema/method pair.

A data-only rebuild may create a new `dataReleaseId` without changing either
version. A methodology change always creates a new data release and requires a
new ADR. It may also require a new schema version when the encoded shape or
allowed values change.

## Compatibility policy

A schema becomes published when an immutable data release or repository release
references its `$id`. From that point, its bytes, `$id`, and validation meaning
are immutable. Corrections are published at a new URL; released schema files
are never edited in place.

The schemas close public objects with `additionalProperties: false` or
`unevaluatedProperties: false`. Consequently, even an optional field or a new
enum value can be rejected by an older consumer. Such additions require a new
minor schema version and a new immutable directory, for example `v1.1.0`.
Editorial changes that do not alter validation use a new patch URL when they
must be published. New required fields, removed fields, changed meanings, new
result states, or incompatible role/identity rules require a new major version,
for example `v2`.

Consumers declare the exact schema versions they support and fail closed with
an explicit unsupported-version state. They must not ignore unknown public
fields, coerce a newer release into an older model, or fetch a mutable “latest”
schema.

## Deprecation and removal

Deprecation announces the replacement schema, migration notes, last supported
browser version, and planned support end. Normal browser support remains for at
least one successfully validated replacement release and 90 days, whichever is
longer. A security or scientific-integrity incident may shorten runtime support,
but requires a dated advisory and an explicit safe fallback.

Deprecating consumer support never authorizes deleting or overwriting an
immutable release. Historical release/schema pairs remain addressable for
verification. Removal means a future browser no longer loads that version; it
does not mutate its artifacts.

## Rollback

Rollback pins the previous complete application/schema/method/data-release
pair. Files from different releases or schema versions are never mixed. A bad
release receives a new replacement `dataReleaseId`; its original bytes remain
immutable with a rejection or advisory record.
