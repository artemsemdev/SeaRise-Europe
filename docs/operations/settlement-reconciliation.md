# Settlement reconciliation report

Build the report only after both the normalized-catalogue and spatial-stage
receipts exist. The receipt is each stage's completion marker; a database
without its exact receipt is not an input.

Run from the repository root with the pinned Python 3.11 settlement-spatial
environment:

```console
PYTHONPATH=src/pipeline python scripts/release/build_settlement_reconciliation.py \
  --catalogue-db /absolute/input/geonames-normalized-catalogue-v1.duckdb \
  --catalogue-receipt /absolute/input/geonames-normalized-catalogue-v1.receipt.json \
  --spatial-db /absolute/input/geonames-spatial-stage-v1.duckdb \
  --spatial-receipt /absolute/input/geonames-spatial-stage-v1.receipt.json \
  --output /absolute/output/settlement-reconciliation.json \
  --data-release-id searise-europe-v1.0.0-20260812-939053bab621 \
  --work-dir /absolute/owner-controlled/work
```

Success prints the deterministic report identity. The output is canonical JSON
and is published without overwrite after descriptor-bound snapshots, receipt
and database reconciliation, semantic validation, file sync, and directory
sync. An output in a source database directory must not use either database's
reserved `<database-name>.wal` sidecar name. The implementation streams rows
in numeric GeoNames order, merges the two spatial decision tables with bounded
lookahead, disables DuckDB spill, and caps distinct dimension keys.

Success is committed only after private staging cleanup, a second output-parent
sync, closure of the original directory authority, and a fresh pathname,
inode, size, and SHA-256 check. Failures before that point roll back only the
owned output inode and preserve a racing foreign replacement. Descriptor
cleanup after that point is best-effort and cannot turn durable success into a
false failure.

## Reading the flow

The record flow is intentionally two-stage:

```text
sourcePlaceRows
  = catalogueAccepted + catalogueRejected

catalogueAccepted
  = spatialClassified + spatialRejected
```

`catalogueRejected` means the source record failed before geometry. Those rows
appear only in the catalogue rejection-reason ledger. Every normalized row
reaches exactly one later outcome: `spatialClassified` or `spatialRejected`.
Catalogue reasons are closed to the reviewed catalogue-v1 precedence list.
The only spatial-v1 rejection reason, `outside-support`, remains distinct from
the classified `coastal` and `inland` statuses.

Country, feature class, feature code, population band, and coastal-status
dimensions use normalized-place counts. Language and script use
selected-normalized-name counts, including one canonical name and every
selected alternate name. Missing language and script metadata use `und` and
`Zzzz`, respectively. Each bucket includes classified, spatial-rejected, and
total values; no dimension silently includes pre-spatial catalogue rejections.

The report binds the SHA-256 and byte size of both databases and receipts, both
stage candidate identities, and the geometry contract identity. It makes no
production, publication, signing, canonical-geometry, hazard, scientific, or
owner-approval claim. Schema-valid consumers must additionally call the
semantic validator because JSON Schema cannot prove the flow equations,
bucket sums, ordering, or deterministic identity.

The intended future candidate path is
`evidence/settlement-reconciliation.json`. This focused change does not alter
the exact 53-artifact candidate-completeness contract; adding that 54th
artifact and updating its manifest/checksum sequencing is a separate contract
change.
