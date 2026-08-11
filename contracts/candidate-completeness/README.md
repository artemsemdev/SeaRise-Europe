# Candidate completeness contract

This additive contract defines the exact Phase 1 engineering candidate that can
be handed to release assembly. It validates an observed immutable inventory; it
does not build files, upload a release, make a production claim, or implement
the provenance, signing, or SBOM work owned by issue #53.

## Required inventory

[`v1/required-artifacts.json`](v1/required-artifacts.json) is the normative
path/role/media-type/encoding matrix. A complete candidate has exactly 44
sealed artifacts plus `manifest.json`:

| Artifact group | Count | Required paths |
| --- | ---: | --- |
| Scenario, methodology, attribution config | 3 | `config/*.json` |
| Analysis COG | 9 | `analysis/{scenario}/{horizon}.tif` |
| Visual projection PMTiles | 9 | `layers/{scenario}/{horizon}.pmtiles` |
| Projection GeoParquet | 1 | `analysis/projections.parquet` |
| Support boundary | 2 | `boundaries/europe.{parquet,pmtiles}` |
| Coastal boundary | 2 | `boundaries/coastal-analysis-zone.{parquet,pmtiles}` |
| Settlement GeoParquet and search shards | 3 | `search/settlements.parquet`, `search/europe-{core,coastal}.index.br` |
| STAC catalog, collection, and items | 11 | `stac/catalog.json`, `stac/collection.json`, `stac/items/*.json` |
| Quality summary | 1 | `evidence/quality-summary.json` |
| Gate reports | 2 | `evidence/gate-report.{json,md}` |
| Checksums | 1 | `checksums.txt` |

All paths are release-relative and immutable. IDs and paths are unique; no
missing, extra, unsafe, mutable, or cross-release reference is accepted. Every
declared byte size and SHA-256 must equal its observed value. The public v1
projection grid, all nine scenario/horizon STAC links, redistribution rights,
and Python/TypeScript row/column, stored-class, nodata, and final-state evidence
must agree exactly.

The selected support and coastal geometry remains a non-canonical engineering
approximation. `canonical`, `production`, `publicationEligible`, and
`hazardExtentClaim` are therefore all fail-closed `false`.

## Acyclic sealing order

Write sequences are contiguous and have one meaning:

1. sequences 1–41 write every subject validated by the gate report;
2. sequences 42–43 write the machine and human gate reports for that
   pre-manifest snapshot; neither report references a manifest hash;
3. sequence 44 writes `checksums.txt`, covering the exact sorted path/SHA-256
   entries for the other 43 artifacts and excluding itself and the
   not-yet-written manifest;
4. sequence 45 writes `manifest.json` last and seals the 44-artifact inventory.

The final completeness validator checks the gate reports, checksum coverage,
and manifest after the seal. This avoids checksum self-reference and a
gate-report/manifest hash cycle.

## Shared validation vectors

The synthetic valid candidate and JSON Patch negative catalog under
`v1/fixtures/` are consumed independently by Python and TypeScript. They cover
missing, duplicate, extra, unsafe, and cross-release artifacts; byte/hash drift;
bad STAC links and rights; grid and runtime parity drift; incomplete checksum
coverage; invalid sealing order; a gate/manifest cycle; and premature signing.

Run the focused parity checks from the repository root:

```bash
PYTHONPATH=src/pipeline python -m pytest src/pipeline/tests/release/test_candidate_completeness.py -q
cd src/frontend && npm test -- src/lib/contracts/candidate-completeness.test.ts
```
