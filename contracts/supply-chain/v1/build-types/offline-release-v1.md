# Offline release build type v1
Version: `1.0.0`. This contract defines deterministic pre-sign provenance for one validated
SeaRise Europe candidate manifest and its exact offline build receipt.
## Build semantics
Accept only `synthetic-fixture` with all signing, production, publication, scientific, and
cryptographic claims false; validate the pair and derive one canonical unsigned SLSA statement.
## Parameter schemas
External (closed): `candidateId:string`, `dataReleaseId:string`,
`dataProvenanceClass:"synthetic-fixture"`, `actualManifestSha256:sha256`.
Internal (closed): `buildId:string`, `buildMode:"offline"`, `networkAccess:"disabled"`,
`parametersSha256:sha256`, `environment:receipt.environment`, `claims:closed-object`, `policyIdentity:versioned-string`.
## Invocation procedure
Run the controlled offline-release workflow from `master` with no network access; record its
first-attempt GitHub Actions URI, receipt timestamps, and immutable workflow builder identity.
## Subjects, dependencies, and byproduct
Sorted subjects are all COG, GeoParquet, and PMTiles outputs plus `manifest.json`. Sorted
dependencies bind code, environment lock, receipt files, source URL/payload digests, inputs,
and tools. `receipts/build.json` is the sole byproduct, bound by SHA-256 and byte size.
## Example
`{"subject":[{"name":"analysis/projections.parquet","digest":{"sha256":"<64 hex>"}}],"predicate":{"buildDefinition":{"buildType":"<this document URI>"},"runDetails":{"byproducts":[{"name":"receipts/build.json","digest":{"sha256":"<64 hex>"},"annotations":{"byteSize":123}}]}}}`
