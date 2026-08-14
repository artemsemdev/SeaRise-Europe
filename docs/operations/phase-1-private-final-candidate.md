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
local-data/phase-1/local-production-run/candidate-v7/
```

Its immutable identity is:

| Field | Value |
|---|---|
| Candidate ID | `candidate-phase-1-real-source-20260814-d619aa577cbe` |
| Data release ID | `searise-europe-v1.0.0-20260812-939053bab621` |
| Generated-at input | `2026-08-14T13:00:00Z` |
| Code revision | `d619aa577cbeb28feb458e615a419002a14200b3` |
| Pipeline identity SHA-256 | `cf321be488bb0f24cf46fe4bb50b922a5ef40363421c19ba5b9c15382294fe63` |
| Build parameters SHA-256 | `34761d36013017d2f827d98020bb93fc40dca9b2f6094ef9e50b42b417907dc9` |
| Manifest SHA-256 | `e3aa2a2241df71df7299f666277c6eaacb83c31e6d9e075417e4dab2bb02edc6` |
| Declared artifacts | 54 |
| Declared artifact bytes | 64,795,182 |
| Automated QA | 20 of 20 validator groups passed |
| Stop reasons | none |
| Filesystem mode after promotion | read-only directory and files |

Treat this candidate as immutable. Never repair or replace a file in
`candidate-v7`. If code, inputs, authorities, or parameters change, assemble a
new candidate at a new path and assign a new candidate identity. Change the
data release identity as well when the logical data release changes.

`candidate-v5` is retained as superseded failure evidence. Its byte and format
checks passed, but its build receipt and STAC lineage contained fixture
placeholder hashes and a Git revision that did not exist in the repository.
Never use `candidate-v5` for subsequent application work.

`candidate-v6` was the first corrected local rerun. It passed the same candidate
gate but was superseded before publication when the new environment lock was
added to the repository's mandatory dependency inventory and regenerated SBOM.
Retain it as local history; use only `candidate-v7` going forward.

Primary local evidence:

```text
local-data/phase-1/local-production-run/candidate-v7/manifest.json
local-data/phase-1/local-production-run/candidate-v7/checksums.txt
local-data/phase-1/local-production-run/candidate-v7/evidence/gate-report.json
local-data/phase-1/local-production-run/candidate-v7/evidence/gate-report.md
local-data/phase-1/local-production-run/build-parameters-v7.json
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
  local-data/phase-1/local-production-run/candidate-v7/manifest.json
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

The successful `candidate-v7` assembly used:

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
| Exact environment lock | `src/pipeline/requirements-phase1-final-macos-x86_64.lock` |
| Environment lock SHA-256 | `2988c24e76853ba8f87c3cc756325d5114386389b1548a0a034939473a7b80f0` |

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

## Derive corrected private candidate inputs

The original v2 input tree remains immutable. `candidate-v7` was derived into
`prepared-production-inputs-v4` without rebuilding or downloading the heavy
scientific, settlement, boundary, or tile artifacts. The derivation replaced
fixture provenance values with reviewed local authorities, updated report
links, recomputed changed output identities, and retained all binary bytes.

```bash
git archive --format=tar d619aa577cbeb28feb458e615a419002a14200b3 -- \
  scripts/release src/pipeline/searise_pipeline/candidate_completeness \
  contracts/candidate-completeness/v2 contracts/release/v1 contracts/release/v2 \
  | shasum -a 256

PYTHONPATH=src/pipeline \
/private/tmp/searise-phase1-py311/bin/python \
  scripts/release/derive_phase1_private_candidate_inputs.py \
  --source-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v2/candidate-inputs" \
  --output-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v4/candidate-inputs" \
  --source-authority "$SEARISE_REPO_ROOT/local-data/phase-1/ar6-linux-candidate/phase-0r-ar6-v1/source-receipt.json" \
  --code-revision d619aa577cbeb28feb458e615a419002a14200b3 \
  --generated-at 2026-08-14T13:00:00Z \
  --environment-lock "$SEARISE_REPO_ROOT/src/pipeline/requirements-phase1-final-macos-x86_64.lock" \
  --pipeline-identity-sha256 cf321be488bb0f24cf46fe4bb50b922a5ef40363421c19ba5b9c15382294fe63 \
  --parameters-output "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/build-parameters-v7.json"
```

The command is no-overwrite. It records the original 51-file input inventory,
source authority, code revision, environment lock, and pipeline identity in the
local build-parameters document.

## Assemble the final local candidate

The successful final run used `work-v7` and `candidate-v7`. These paths now
exist and must not be reused. Choose a new suffix for any later candidate.

```bash
chmod 700 "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run"

PYTHONPATH=src/pipeline \
/private/tmp/searise-phase1-py311/bin/python \
  scripts/release/assemble_phase1_production_candidate.py \
  --input-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v4/candidate-inputs" \
  --authority-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v2/authorities" \
  --toolchain-root "$SEARISE_REPO_ROOT/local-data/phase-1/prepared-production-inputs-v2/toolchain" \
  --retained-ar6-root "$SEARISE_REPO_ROOT/local-data/phase-1/ar6-linux-candidate/phase-0r-ar6-v1" \
  --retained-boundary-root "$SEARISE_REPO_ROOT/local-data/phase-1/boundary-current" \
  --brotli /usr/local/Cellar/brotli/1.2.0/bin/brotli \
  --brotli-sha256 22567695dde38e3cb9393ac0ab0b45379e9e188357f6cff69b0ed23959abd5c2 \
  --work-root "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/work-v7" \
  --output "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v7" \
  --candidate-id candidate-phase-1-real-source-20260814-d619aa577cbe \
  --data-release-id searise-europe-v1.0.0-20260812-939053bab621 \
  --generated-at 2026-08-14T13:00:00Z \
  --code-revision d619aa577cbeb28feb458e615a419002a14200b3 \
  --environment-lock "$SEARISE_REPO_ROOT/src/pipeline/requirements-phase1-final-macos-x86_64.lock" \
  --build-parameters "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/build-parameters-v7.json" \
  --pipeline-identity-sha256 cf321be488bb0f24cf46fe4bb50b922a5ef40363421c19ba5b9c15382294fe63
```

Do not reuse the historical identity for changed inputs, code, parameters, or
authorities. For an exact revalidation, retain the old candidate and compare
the new manifest and inventory; do not overwrite `candidate-v7`.

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
  --candidate-root "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v7"

shasum -a 256 \
  "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v7/manifest.json"

jq '{candidateId,dataReleaseId,releasable,authority,stopReasonCodes,
     checkCount:(.checks|length)}' \
  "$SEARISE_REPO_ROOT/local-data/phase-1/local-production-run/candidate-v7/evidence/gate-report.json"
```

Expected byte-gate output:

```text
validated candidate-phase-1-real-source-20260814-d619aa577cbe: 54 artifacts, 64795182 bytes; production and publication not claimed
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
| `test_phase1_private_candidate_inputs.py` | Local-only derivation, real source lineage, code/environment/tool authorities, report links, and changed-output rehashing |
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
  src/pipeline/tests/contracts/test_phase1_private_candidate_inputs.py \
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

## Recorded candidate-v7 validation

The final local run recorded the following results on 2026-08-14:

| Validation | Result |
|---|---|
| Production assembly and complete QA matrix | passed; 20 of 20 groups |
| Independent 54-artifact byte gate | passed; 64,795,182 declared bytes |
| Fixture-placeholder scan in candidate JSON | passed; no known placeholder SHA values |
| Phase 1 focused contract suite | 87 passed |
| Supply-chain inventory/SBOM/handoff regression suite | 63 passed |
| Ruff on changed Python sources and tests | passed |

The unrestricted GitHub CI pipeline remains authoritative for tests that need
loopback sockets, platform-specific spatial extensions, or other runner
capabilities unavailable in the local sandbox. No candidate bytes are supplied
to CI; CI uses bounded fixtures and repository-controlled contracts.

## Failure and recovery rules

- Never modify or delete `candidate-v5`; retain it as superseded failure evidence.
- Never modify or delete `candidate-v6`; retain it as superseded local evidence.
- Never modify or delete `candidate-v7` to make a later validation pass.
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
