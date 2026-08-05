# Phase 0R regional projection release evidence

> **Issue:** [#110](https://github.com/artemsemdev/SeaRise-Europe/issues/110)
> **Measured candidate:** `phase-0r-ar6-v1` at source revision
> `e41be39b4304e4a9835319f8b4935c8a4e68558a`
> **Scientific disposition:** `projection-only`
> **Automated validation:** `pending`
> **Release disposition:** `pending-owner`
> **Phase 1:** locked

## Result

The real, SHA-256-locked AR6 archive produced the complete 3 × 3
scenario/horizon matrix on the source-native 1° grid. The measured macOS
candidate contains nine exact browser-lookup COGs, one exact analytical
GeoParquet file, nine visual-only PMTiles archives, a source-grid identity
sidecar, STAC Collection and Items, attribution, checksums, statistics, and
build/source receipts.

All candidate-local scientific, source-integrity, format, semantic-parity,
licence, and size checks passed. The Chromium range harness also passed its
delivery budgets. This does not complete the recovery gate: an independently
built native Linux candidate must still be compared with the same source
revision, after which the project owner must record the release disposition.

## Measured evidence

| Measure | Result |
|---|---:|
| Candidate artifacts | 31 |
| Exact COGs | 9 files / 184,399 bytes |
| Visual PMTiles | 9 files / 5,656,520 bytes |
| Analytical GeoParquet | 1 file / 251,231 bytes |
| Core artifact total | 6,092,150 bytes |
| Full clean build | 13.384166 s |
| Chromium samples | 10 cold / 100 warm |
| Warm lookup p95 | 1.7 ms |
| Cold COG range requests | 1 |
| Cold transfer | 28,168 bytes |
| Incremental browser heap | 1,328,476 bytes |

The browser trace binds the lookup to the exact selected COG path, source-grid
row and column, source location ID, and q0.167/q0.5/q0.833 values. PMTiles are
validated and decoded as the canonical `projection` visual layer; they are not
used as an exact lookup substitute. GeoParquet is the analytical parity export,
not the browser nearest-location oracle.

## Integrity anchors

- manifest SHA-256:
  `dc8fcec21edab6b615d025bdc01095a10237f62b025e789cbec231c1143dacff`
- build receipt SHA-256:
  `246d9058406352dbb6357f6ac6ff187407d631e61eb3953d18758944e1f3aabf`
- source receipt SHA-256:
  `f24f2f0bd8a9877ef32c33f9e58ddf3c150f6fb48a79a2195e73d5ad739ec037`
- delivery report SHA-256:
  `7b8a1454bf704c97d1764f97cc3dd0282cca8723096aa506492eecd95429b82e`
- Chromium trace SHA-256:
  `dd2a57fb513c9f7342eb4a9577087ccb443c52d15fcd4e7be5d0ff8885ce15d6`
- build timing SHA-256:
  `8a04444126efd88057768c6e09bfe4266eacee7d929895fba09578831a2dfae6`

The machine-readable summary is
[`ar6-regional-release-evidence.json`](../../src/pipeline/science/evidence/ar6-regional-release-evidence.json).
The full candidate directory is intentionally not committed; its hashes and
receipts are the durable identity, and the manual CI job uploads the native
Linux candidate as a temporary GitHub Actions artifact.

## Remaining gate sequence

1. Dispatch `.github/workflows/ci.yml` for the issue branch with
   `release_source_revision=e41be39b4304e4a9835319f8b4935c8a4e68558a`.
2. Download the native Ubuntu candidate and compare it with the measured macOS
   candidate using the repository reproducibility command.
3. Record the resulting cross-environment evidence. Keep
   `automatedValidation=pending` if the comparison is absent or fails.
4. After integration reaches `master`, the project owner records
   `releaseDisposition=approved`, `rejected`, or `blocked`. CI cannot make that
   decision.

Until all four steps are complete, the fallback is
`do-not-publish-or-unlock-phase-1`.
