# Offline Release Builder Runbook

> **Scope:** build an immutable candidate; publication and activation are a
> separate, later operation.
>
> **Profiles:** `fixture`, `regional`, and `full-europe` execute the same seven
> stages from checked-in configuration.

## Safety boundary

The target builder lives in `searise_pipeline.offline_release`, beside the
legacy release and Azure/PostGIS modules. It reads only declared files, runs
with network access disabled, writes a content-bound cache and one new
candidate directory, and commits either a success receipt or a bounded failure
receipt. It has no upload, database, release-pointer, or production-activation
stage. The legacy pipeline remains available until Phase 3 parity.

Run reviewed builds with the pinned image in
`src/pipeline/offline_release/Dockerfile`. Do not install a convenient local
GDAL/Python stack and then describe its output as a controlled build. The
container pins Python, native runtime libraries, Python wheels, locale,
timezone, hash seed, and architecture. Runtime networking must remain
`--network none`.

## Stage contract

Every profile declares this exact graph:

| Order | Stage | Input boundary | Successful output |
|---:|---|---|---|
| 1 | `verify-sources` | source/build receipt hashes and declared input identities | verified source summary |
| 2 | `inspect` | verified source plus manifest inventory | bounded schema, artifact, and dataset observations |
| 3 | `normalize` | inspected input plus canonical parameters | canonical parameter record |
| 4 | `derive` | normalized input | release artifacts derived from the reviewed input tree |
| 5 | `package` | derived artifacts | complete candidate-shaped temporary tree |
| 6 | `validate` | packaged tree and v1 public schemas | semantic, hash, rights, STAC, and public-contract results |
| 7 | `assemble-release` | validated tree | one complete immutable release directory |

Each stage receives a typed context containing the immutable build plan, its
direct dependency directories, and their sorted output identities. A stage
may write only into its temporary output directory. The engine inventories
every non-empty file, records byte size and SHA-256, writes a complete stage
receipt, and atomically renames the cache object. The final candidate is copied
to a sibling temporary directory, re-inventoried, and atomically promoted only
after all seven stages pass.

`fixture`, `regional`, and `full-europe` change only explicit profile data:
provenance class, reviewed input path, source-receipt path, and data volume.
They do not select different code paths or stage graphs.

## Build identity and resume

The plan identity binds:

- profile, data release ID, provenance class, and exact Git revision;
- environment lock and the identities of every declared tool implementation;
- source receipts and the recursively inventoried input and schema files;
- canonical parameters and the complete ordered stage graph.

A stage key binds the plan identity, stage contract version, stage name, and
the identities of direct upstream outputs. Resume is therefore conservative:
a source, parameter, code, tool, schema, or upstream-output change produces a
new key. Existing cache objects are accepted only when their directory shape,
receipt identity, sorted inventory, byte sizes, and hashes all match. A stale,
partial, extra, symlinked, or modified object fails closed instead of being
silently rebuilt under the same identity.

The cache is append-only for a plan identity. A successful build never
overwrites an existing candidate or operator receipt. Use a new candidate and
receipt path for every invocation, including a resume.

## Reproducibility definition

Scientific-array identity is non-waivable: ordered values, nodata, numeric
types, dimensions, coordinates/CRS, source grid IDs, scenarios, horizons, and
source lineage must match exactly. Canonical JSON uses sorted keys, UTF-8,
finite numbers, and explicit receipt timestamps. File discovery and receipt
arrays use stable path/identity ordering. Profiles pin locale, timestamp,
compression, numeric type, and CRS policies.

The committed fixture has the stronger contract that all 42 candidate files
are byte-identical across clean builds and verified resume. For future native
regional/full packaging where byte identity is unavailable, the scientific
arrays must still be identical. Any packaging-only difference must be bounded
to named artifacts, explained by pinned tool/platform evidence, and recorded
in a reproducibility comparison receipt. An unexplained difference is a failed
build gate, never a waiver.

Stage durations, total duration, and peak process RSS are diagnostic evidence;
they are intentionally excluded from candidate identity.

## Fixture operation

Build the image from the repository root:

```bash
docker build \
  --platform linux/amd64 \
  --tag searise-offline-builder:local \
  --file src/pipeline/offline_release/Dockerfile \
  .
```

Create a directory outside the repository, then run the container as the host
user with no network:

```bash
docker run --rm --network none --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  --volume "/absolute/offline-run:/run" \
  searise-offline-builder:local \
  --profile src/pipeline/offline_release/profiles/fixture.json \
  --input-root /workspace \
  --code-revision 0123456789abcdef0123456789abcdef01234567 \
  --release-date 20260810 \
  --started-at 2026-08-10T12:00:00Z \
  --completed-at 2026-08-10T12:00:01Z \
  --cache-dir /run/cache \
  --output-dir /run/candidate-clean \
  --execution-receipt /run/execution-clean.json \
  --failure-receipt /run/failure-clean.json
```

Replace the example revision and timestamps with explicit reviewed values.
They are inputs, not ambient clock reads. To resume, keep `/run/cache` and use
new `--output-dir`, `--execution-receipt`, and `--failure-receipt` paths.

CI performs the same clean/resume operation in the pinned Linux image.

## Controlled regional and full-Europe operation

`.github/workflows/offline-release-controlled.yml` is manual-only and accepts
`regional` or `full-europe`. Dispatch it only at the exact reviewed `master`
commit supplied as `source_revision`. The workflow also requires the same-repo
producer run ID, canonical GitHub artifact name, SHA-256 of the contained
`offline-inputs.tar`, release date, and explicit start/completion timestamps.

The downloaded artifact must contain exactly one uncompressed
`offline-inputs.tar`. The tar may contain only regular files and directories
under `build-inputs/offline-release/<profile>/` and must include
`manifest.json` and `receipts/sources.json`. The preparation step verifies the
supplied bundle digest and rejects traversal, absolute paths, links, devices,
duplicates, extra roots, or the wrong profile before atomically exposing the
input directory.

The workflow builds the checked-in pinned image, mounts only the selected
profile input read-only and the run directory read-write, and runs with a
read-only container filesystem, no network, and a non-root UID. Its GitHub
artifact contains the unactivated candidate, operator receipt or failure
receipt, and dispatch evidence. That evidence transfer is not R2 publication,
database registration, pointer mutation, or production activation.

## Reading receipts

A successful operator receipt validates against
`operator-receipt.schema.json` and contains exactly seven ordered stage events,
each with `cacheStatus`, `durationSeconds`, output identities, warnings, and
quality results. It also records the stable candidate inventory identity,
total duration, and peak process RSS. The candidate's public
`receipts/build.json` independently validates against the Phase 1 v1 build
receipt contract and binds inputs, tools, code, parameters, and 19 public
scientific/metadata outputs.

Success is authoritative only for the pair of candidate plus schema-valid
execution receipt, and only when all of these are true:

- the CLI exits zero and says `publication not attempted`;
- no failure receipt exists;
- the execution receipt has `status=complete` and `networkAccess=disabled`;
- the candidate exists at the new path and its complete inventory validates;
- the public build receipt and all release contracts validate.

Console output is deliberately bounded. Raw exception messages and credentials
are not serialized into failure receipts.

## Failure taxonomy and recovery

| Code | Meaning | Operator response |
|---|---|---|
| `invalid-plan` | unsafe paths, malformed profile, existing immutable output/receipt, or missing graph handler | correct the invocation or reviewed profile; do not alter an existing artifact |
| `source-verification-failed` | a declared input is absent, symlinked, outside the root, or has different bytes | quarantine the input bundle and re-run acquisition/review; never update a hash just to pass |
| `stale-cache` | cached receipt, shape, output, size, or hash differs | preserve it for investigation, then move the entire affected cache object out of the active cache |
| `stage-execution-failed` | a typed stage failed without a more specific classification | inspect the stage and its bounded quality evidence; restart with the same verified cache after fixing the cause |
| `output-validation-failed` | stage output is empty, unsafe, or violates its output/public contract | keep the failure receipt and repair the producer; do not promote the partial tree |
| `atomic-promotion-failed` | the final copy differs or the immutable target appeared | choose a new output path or investigate concurrent use; never overwrite the target |
| `incomplete-build` | receipt commit or unexpected operator execution failed | treat any candidate as unreceipted and unusable; investigate storage and rerun to new paths |
| `disk-pressure` | `ENOSPC`/quota prevented stage or receipt completion | follow the disk-pressure procedure below, then resume from verified cache |

### Restart after interruption

1. Confirm there is no success receipt for the attempted candidate.
2. Do not rename a partial directory into place. The engine normally leaves no
   candidate because stage and final promotion are atomic.
3. If an interrupted or older builder reports `complete-unreceipted`,
   quarantine that directory immediately. It is unusable evidence and must
   never be passed to publication or renamed as a complete candidate.
4. Preserve the failure receipt and cache for diagnosis.
5. Re-run the exact reviewed plan with the same cache and new immutable output
   and receipt paths. Verified stages become hits; the interrupted stage and
   downstream stages run as misses.

### Disk pressure

Stop new builds and record the failed build ID. Check free bytes and quota on
the cache, temporary, candidate, and receipt volumes. Remove only disposable
temporary directories whose names begin with the builder's documented dot
prefix and are not open by a running process. Prefer archiving old, complete
cache objects outside the active cache. Never delete a reviewed source bundle,
candidate, or receipt to make a build pass. After capacity is restored, resume
to new output/receipt paths and verify every cache hit.

### Failed verification

Do not repair bytes inside a content-bound cache or controlled input artifact.
Record the expected and observed identities, quarantine the whole object, and
return to the source-acquisition or producing-stage owner. A new reviewed input
or implementation revision must generate a new plan identity.

### Cleanup

Candidate directories and receipts are immutable evidence. Retain them under
the repository's evidence policy. Cache cleanup may remove complete objects
only when no active build references them; removing a cache affects speed, not
candidate identity. Delete abandoned temporary directories only after proving
no builder process is active. Never clean via a broad recursive path, glob, or
unresolved environment variable.

## Publication boundary

Finishing this runbook produces an unactivated local or GitHub evidence
artifact. Upload to R2/static hosting, database mutation, signing authority,
release-pointer changes, public delivery checks, and production activation are
outside this builder and require their own protected workflow and approval.
