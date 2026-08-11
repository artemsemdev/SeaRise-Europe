# Settlement GeoParquet publication

This command builds from an exact spatial database/receipt pair, performs two
byte-identical serializations, validates, and publishes without overwriting.

Run it from the repository root with the release Python environment:

```console
PYTHONPATH=src/pipeline python scripts/release/build_settlement_geoparquet.py \
  --spatial-db /absolute/input/spatial.duckdb \
  --spatial-receipt /absolute/input/spatial-receipt.json \
  --output /absolute/output/settlements.parquet \
  --output-receipt /absolute/output/settlements.receipt.json \
  --data-release-id searise-europe-v1.0.0-20260812-34974982e794 \
  --work-dir /absolute/owner-controlled/work
```

All six arguments are required. Paths must not traverse symlinks; output and
receipt must be distinct names in one owner-controlled directory. Success prints only the receipt identity.

The artifact is linked first, fsynced, and checked. The receipt is linked last;
both entries and artifact contents are checked again. Nothing is overwritten.

Failure rolls back only created device/inode identities; racing and alien entries
remain. Cleanup diagnostics name retained private residue for inspection.

The receipt sets `productionClaim`, `publicationClaim`, `canonicalGeometryClaim`,
`hazardExtentClaim`, `scientificApprovalClaim`, `ownerApprovalClaim`, and
`signingClaim` to false, with `publicationEligible` false. Local placement grants
no production, science, signing, owner, or publication approval. The v3 artifact envelope is unchanged.
