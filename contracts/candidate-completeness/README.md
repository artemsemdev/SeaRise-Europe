# Candidate completeness contract

This contract defines the exact Phase 1 engineering candidate boundary before
signing. `v1/required-artifacts.json` is the authoritative 53-artifact
inventory; `v1/candidate.schema.json` closes the public document shape and
reuses the release v1 path, hash, role, media-type, scenario, and horizon
definitions.

The deterministic seal order is:

1. write and validate the 50 data, configuration, receipt, rights, quality,
   architecture, STAC, settlement, COG, PMTiles, and GeoParquet artifacts;
2. write the JSON and Markdown gate reports from that pre-terminal snapshot;
3. write `checksums.txt`, covering every artifact except itself;
4. write `manifest.json` last, covering all 53 artifacts without hashing itself;
5. pass the separate supply-chain evidence-envelope and signing gate before any
   publication.

Provenance, signature, and SBOM sidecars are mandatory publication evidence,
not deferred Phase 1 work. Pair validation is still pending: a dependent
validator must bind candidate ID, release ID, provenance class, and the actual
manifest SHA-256. Sidecars stay outside the candidate inventory to avoid a
recursive manifest/signature dependency.

The checked-in fixture is synthetic. It records no owner geometry approval,
canonical boundary, production, hazard-extent, or publication claim. Schema
validation proves document shape; the executable inventory tests additionally
prove exact artifact identity, rights, counts, 3 x 3 STAC bindings, checksum
coverage, terminal ordering, and the non-recursive supply-chain boundary.

The provenance core closes the synthetic pair as one canonical in-toto Statement v1 with a
SLSA provenance v1 predicate. Sorted subjects bind every scientific COG, GeoParquet, PMTiles,
and the actual `manifest.json` bytes. The controlled workflow on `master` is the builder and
the trusted first-attempt run URI is the invocation. Sorted dependencies bind code, lock,
receipt files, verified source URL/payload digests, inputs, and tools. The exact build receipt
is a run byproduct with its digest and byte size.

Receipts are strict-schema validated beneath the candidate root and must match candidate hash,
size, release, provenance, and attribution bindings. Only `synthetic-fixture` is supported; no
signature, production, publication, scientific, or owner-approval claim is made.
