# Phase 1 Private Final Candidate Runbook

> **Status:** the local candidate passed automated Phase 1 production QA.
>
> **Privacy boundary:** the input TAR, extracted inputs, validation authorities,
> work directories, and final candidate are private local files. Do not commit,
> upload, attach to GitHub Actions or Releases, sign through a public service,
> or copy them to an external retention service.

This runbook records the exact candidate that subsequent local work must use,
how it was assembled, how it was validated, and which repository tests protect
the process. It does not authorize publication or production promotion.

## Canonical local candidate

The repository is expected at:

```text
/Users/artemsemenov/Desktop/Github/SeaRise Europe
```

The final candidate is:

```text
local-data/phase-1/local-production-run/candidate-v5/
```

Its immutable identity is:

| Field | Value |
|---|---|
| Candidate ID | `candidate-phase-1-real-source-20260812-939053bab621` |
| Data release ID | `searise-europe-v1.0.0-20260812-939053bab621` |
| Generated-at input | `2026-08-12T23:30:00Z` |
| Manifest SHA-256 | `0c01fb249ec55e40bc79a78556c16097cd9777714c8d61a5164e42b845a2f035` |
| Declared artifacts | 54 |
| Declared artifact bytes | 64,795,196 |
| Automated QA | 20 of 20 validator groups passed |
| Stop reasons | none |
| Filesystem mode after promotion | read-only directory and files |

Treat this candidate as immutable. Never repair or replace a file in
`candidate-v5`. If code, inputs, authorities, or parameters change, assemble a
new candidate at a new path and assign a new candidate/release identity.

Primary local evidence:

```text
local-data/phase-1/local-production-run/candidate-v5/manifest.json
local-data/phase-1/local-production-run/candidate-v5/checksums.txt
local-data/phase-1/local-production-run/candidate-v5/evidence/gate-report.json
local-data/phase-1/local-production-run/candidate-v5/evidence/gate-report.md
```

`gate-report.json` records `automatedValidation: pass`, 20 passed check groups,
and no stop reasons. It deliberately records no owner publication disposition,
so `releasable` remains false. This is correct for the private local candidate.

## Input bundle and extracted inputs

The exact input archive is:

```text
local-data/phase-1/phase-1-production-inputs-v2.tar
```

| Field | Value |
|---|---|
| Byte size | 198,809,600 |
| SHA-256 | `6f337837a66e661eed38cdfbf00c26a541e1916b1416c1aa8644eb15fda2225a` |
| Archive members | 62, including `input-authority.json` |
| Retained payload files | 61 |

The archive was safely extracted and reverified at:

```text
local-data/phase-1/prepared-production-inputs-v2/
├── authorities/
├── candidate-inputs/
├── evidence/
└── toolchain/
```

The TAR and all paths below `local-data/` are excluded by the root `.gitignore`.
Confirm this before any Git operation:

```bash
git check-ignore -v \
  local-data/phase-1/phase-1-production-inputs-v2.tar \
  local-data/phase-1/local-production-run/candidate-v5/manifest.json
git ls-files local-data
```

The second command must produce no tracked paths.

## Validation authorities

The candidate uses current local inputs plus previously validated exact-byte
authorities. Preserve these directories with the final candidate:

| Authority | Local path | Purpose |
|---|---|---|
| AR6 Linux candidate | `local-data/phase-1/ar6-linux-candidate/phase-0r-ar6-v1/` | Exact hashes and passed `pmtilesStructureAndProperties` evidence for nine projection PMTiles files |
| Boundary candidate | `local-data/phase-1/boundary-current/` | Exact hashes, official PMTiles integrity, decoded geometry parity, and browser evidence for two boundary PMTiles files |
| Settlement spatial receipt | `local-data/phase-1/prepared-production-inputs-v2/authorities/geonames-spatial-stage-v1.receipt.json` | Spatial-stage identity and classification contract |
| Settlement artifact receipt | `local-data/phase-1/prepared-production-inputs-v2/authorities/settlements.receipt.json` | Exact settlement GeoParquet byte, schema, row-group, and rebuild authority |
| Chromium worker report | `local-data/phase-1/browser-worker-performance/browser-worker-performance.chromium.json` | Production shard initialization, query, responsiveness, memory, and static-network evidence |

Executing the pinned Linux x86_64 Tippecanoe and PMTiles binaries in an
`linux/amd64` Docker container on Apple Silicon failed inside QEMU with signal
11. That diagnostic attempt produced no candidate. The successful local run:

1. revalidated COG, GeoParquet, JSON, STAC, rights, receipt, search-shard, and
   terminal artifacts directly;
2. required every projection and boundary PMTiles byte to match its retained
   candidate and canonical checksum entry; and
3. required the associated prior tool-validation report check to be passed.

This is exact-byte reuse of prior tool validation, not an unvalidated skip.

## Historical execution environment

The successful `candidate-v5` assembly used:

| Component | Historical value |
|---|---|
| Python executable | `/private/tmp/searise-phase1-py311/bin/python` |
| Python | CPython 3.11.15, macOS x86_64 under Rosetta |
| PyArrow | 16.1.0 |
| Rasterio | 1.4.3 |
| JSON Schema | 4.25.1 |
| DuckDB | 1.5.4 |
| Brotli executable | `/usr/local/Cellar/brotli/1.2.0/bin/brotli` |
| Brotli SHA-256 | `22567695dde38e3cb9393ac0ab0b45379e9e188357f6cff69b0ed23959abd5c2` |

The `/private/tmp` Python environment is operational state, not durable project
evidence. Before future revalidation, confirm it still has the recorded
identity and versions. If it is absent or differs, recreate and review a pinned
Python 3.11 environment; do not silently substitute versions.

```bash
/private/tmp/searise-phase1-py311/bin/python -c \
  'import platform; print(platform.python_version(), platform.machine())'
shasum -a 256 /usr/local/Cellar/brotli/1.2.0/bin/brotli
```

## Reverify and extract the TAR

Run from the repository root. The destination must not already exist.

```bash
SEARISE_REPO_ROOT="/Users/artemsemenov/Desktop/Github/SeaRise Europe"
cd "$SEARISE_REPO_ROOT"

shasum -a 256 local-data/phase-1/phase-1-production-inputs-v2.tar

/private/tmp/searise-phase1-py311/bin/python \
  scripts/release/prepare_phase1_production_inputs.py \
  --archive "$SEARISE_REPO_ROOT/local-data/phase-1/phase-1-production-inputs-v2.tar" \
  --destination "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-next" \
  --expected-sha256 6f337837a66e661eed38cdfbf00c26a541e1916b1416c1aa8644eb15fda2225a
```

The extractor rejects a changed archive digest, duplicate or extra inventory,
unsafe paths, links, special files, non-canonical authority, changed payload,
and an existing destination. Inspect the historical run in
`prepared-production-inputs-v2`; use a new destination for a new verification.

## Assemble a new local candidate

The historical run used `work-v5` and `candidate-v5`. Those paths now exist and
must not be reused. This example intentionally uses `work-v6` and
`candidate-v6`; choose another unused suffix if either exists.

```bash
chmod 700 "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run"

PYTHONPATH=src/pipeline \
/private/tmp/searise-phase1-py311/bin/python \
  scripts/release/assemble_phase1_production_candidate.py \
  --input-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v2/candidate-inputs" \
  --authority-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v2/authorities" \
  --toolchain-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v2/toolchain" \
  --retained-ar6-root "$SEARISE_REPO_ROOT/local-data/phase-1/ar6-linux-candidate/phase-0r-ar6-v1" \
  --retained-boundary-root "$SEARISE_REPO_ROOT/local-data/phase-1/boundary-current" \
  --brotli /usr/local/Cellar/brotli/1.2.0/bin/brotli \
  --brotli-sha256 22567695dde38e3cb9393ac0ab0b45379e9e188357f6cff69b0ed23959abd5c2 \
  --work-root "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/work-v6" \
  --output "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v6" \
  --candidate-id candidate-phase-1-real-source-YYYYMMDD-NEWIDENTITY \
  --data-release-id searise-europe-v1.0.0-YYYYMMDD-NEWIDENTITY \
  --generated-at YYYY-MM-DDTHH:MM:SSZ
```

Do not reuse the historical identity for changed inputs, code, parameters, or
authorities. For an exact revalidation, retain the old candidate and compare
the new manifest and inventory; do not overwrite `candidate-v5`.

The assembler performs pre-terminal QA on 51 supplied artifacts, generates the
JSON and Markdown reports plus canonical checksums, writes `manifest.json`
last, freezes the tree, performs the terminal byte gate, reruns the complete QA
matrix, and promotes with no-overwrite semantics. A failed or unmeasured
non-waivable check prevents promotion.

## Validate the final candidate independently

```bash
PYTHONPATH=src/pipeline \
/private/tmp/searise-phase1-py311/bin/python \
  scripts/release/validate_candidate_bytes.py \
  --candidate-root "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v5"

shasum -a 256 \
  "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v5/manifest.json"

jq '{candidateId,dataReleaseId,releasable,authority,stopReasonCodes,
     checkCount:(.checks|length)}' \
  "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v5/evidence/gate-report.json"
```

Expected byte-gate output:

```text
validated candidate-phase-1-real-source-20260812-939053bab621: 54 artifacts, 64795196 bytes; production and publication not claimed
```

Expected report facts are `automatedValidation: pass`, 20 checks, zero stop
reasons, and `releasable: false` because no publication disposition exists.

## Test ownership map

These tests use bounded synthetic files in CI. The private TAR and candidate
are never uploaded as test fixtures.

| Test file | Responsibility |
|---|---|
| `test_phase1_production_input_bundle.py` | Deterministic TAR bytes, exact input/tool/authority inventory, canonical metadata, overwrite and symlink rejection |
| `test_phase1_production_input_extractor.py` | Archive digest, safe extraction, authority/payload identity, traversal/link rejection, and no overwrite |
| `test_phase1_production_candidate_cli.py` | Production dispatcher wiring, retained authorities, Brotli identity, private work roots, and immutable output |
| `test_candidate_production_assembler.py` | Pre-terminal validation, manifest-last sealing, 54-artifact assembly, read-only promotion, and rollback |
| `test_candidate_production_binary_validators.py` | Projection, boundary, settlement formats and retained exact-byte authority failures |
| `test_candidate_production_validators.py` | Strict JSON, STAC, rights, receipts, references, release binding, and terminal validation |
| `test_candidate_search_shard_validator.py` | Pinned Brotli decoding plus shard schema, semantics, size, membership, and candidate binding |
| `test_candidate_qa_matrix.py` | Exact version-selected route coverage and unknown/missing/duplicate rejection |
| `test_candidate_qa_execution.py` | Stable hashing, mutation detection, explicit outcomes, and complete execution |
| `test_candidate_qa_report.py` | Deterministic reports, evidence hashes, ordering, and stop reasons |
| `test_candidate_bytes.py` | Exact inventory, hashes, sizes, path/file safety, and final identity pass |
| `test_candidate_completeness_contract.py` | Immutable v1/v2 compatibility and the exact 54-artifact v2 contract |

Run the focused suite from the repository root:

```bash
PYTHONPATH=src/pipeline /private/tmp/searise-phase1-py311/bin/python -m pytest \
  src/pipeline/tests/contracts/test_phase1_production_input_bundle.py \
  src/pipeline/tests/contracts/test_phase1_production_input_extractor.py \
  src/pipeline/tests/contracts/test_phase1_production_candidate_cli.py \
  src/pipeline/tests/contracts/test_candidate_production_assembler.py \
  src/pipeline/tests/contracts/test_candidate_production_binary_validators.py \
  src/pipeline/tests/contracts/test_candidate_production_validators.py \
  src/pipeline/tests/contracts/test_candidate_search_shard_validator.py \
  src/pipeline/tests/contracts/test_candidate_qa_matrix.py \
  src/pipeline/tests/contracts/test_candidate_qa_execution.py \
  src/pipeline/tests/contracts/test_candidate_qa_report.py \
  src/pipeline/tests/contracts/test_candidate_bytes.py \
  src/pipeline/tests/contracts/test_candidate_completeness_contract.py \
  -q
```

The full pipeline suite remains the integration authority used by GitHub CI.

## Failure and recovery rules

- Never modify or delete `candidate-v5` to make validation pass.
- A digest mismatch means the affected object is no longer reviewed. Stop and
  investigate.
- Fix a failed source or implementation and run into new work/output paths.
- Do not use Linux x86_64 tools under QEMU as evidence unless that platform
  failure is resolved and the new path is reviewed.
- Preserve the TAR, prepared inputs, AR6/boundary authorities, Chromium report,
  candidate, manifest, checksums, and gate reports together.
- Rerun the byte validator immediately before a local consumer uses the
  candidate.
- Do not infer signing, external retention, public delivery, or production
  approval from this local automated pass.

## Related documentation

- [Phase 1 offline builder evidence](../evidence/phase-1-offline-release-builder.md)
- [Phase 1 candidate byte gate](phase-1-candidate-byte-gate.md)
- [Offline release builder runbook](offline-release-builder.md)
- [Settlement browser worker performance](settlement-browser-worker-performance.md)
- [Settlement GeoParquet publication](settlement-geoparquet-publication.md)
