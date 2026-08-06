# Phase 0R Regional Release Evidence

> **Issue:** [#110](https://github.com/artemsemdev/SeaRise-Europe/issues/110)
>
> **Evidence date:** 2026-08-06
>
> **Candidate:** `phase-0r-ar6-v1`
>
> **Automated validation:** `PENDING` until trusted provenance is bound
>
> **Owner disposition:** `PENDING`
>
> **Phase 1:** `LOCKED`

## Candidate identity

The release candidate was built from the exact `master` revision
`c2ed9074624c7cfe61bf610a1a67f4303aca7580`, produced by integration pull
request [#183](https://github.com/artemsemdev/SeaRise-Europe/pull/183).
The evidence branch is a direct descendant of that revision and contains only
the allowlisted evidence bundle, this report, and the changelog entry.

## Trusted validation run

GitHub Actions run
[#31113582612](https://github.com/artemsemdev/SeaRise-Europe/actions/runs/31113582612),
attempt 1, completed successfully against the candidate revision.

| Job | Job ID | Result |
|---|---:|---|
| Detect changed components | `92657349306` | passed |
| Full-source Linux AR6 candidate | `92657393273` | passed |
| Full-source macOS ARM64 AR6 candidate | `92657393125` | passed |
| CI Gate | `92671397624` | passed |

The two independently produced GitHub artifacts are retained until
2026-08-20:

| Profile | Artifact ID | Bytes | GitHub artifact SHA-256 |
|---|---:|---:|---|
| Linux x86-64 CPython 3.11 | `8973691730` | 5,771,132 | `f864246cbec477339c3246dadca9b4ad9f64bcd92f4b87c6a91ad01a96c40540` |
| macOS ARM64 CPython 3.11 | `8973969557` | 5,776,298 | `ebca8d2e841a9c2df3f2c51dcd55c4ada739cf2523e91e39b632a762b82c7046` |

Their canonical names bind the artifacts to run `31113582612` and source
revision `c2ed9074624c7cfe61bf610a1a67f4303aca7580`.

## Reproducibility result

Strict comparison passed across 31 release artifacts:

- Linux and macOS candidate artifact bytes are identical within the pinned
  toolchains.
- The maximum scientific value difference is `0 mm`.
- The valid source-grid identifier set difference is `0`.
- The GeoParquet artifact is identical with SHA-256
  `d32d6a1ec14161f71f76f68e056844c3b07fafde24e92a92ee22a2d5080888d5`.

The checked-in reproducibility report intentionally remains
`pending-external-provenance`. Local comparison cannot claim that the GitHub
jobs were independent. The protected owner workflow verifies the run, jobs,
artifact metadata, downloads, exact pull-request topology, and candidate
bindings before it changes the automated disposition.

## Delivery result

Trusted Chromium delivery validation passed on macOS ARM64:

| Measurement | Observed |
|---|---:|
| Lookup p95 | 2.3 ms |
| Cold transfer | 28,168 bytes |
| Browser heap | 1,587,037 bytes |
| Full clean build | 19.911667 seconds |
| Range requests per lookup | 1 |

## Gate sequence

This evidence-only merge does not approve the release. The remaining sequence
is deliberately fail-closed:

1. Merge this evidence from the exact candidate revision using a normal merge.
2. Run the protected `Phase 0R owner promotion` workflow with the trusted run
   and evidence pull request.
3. Record the protected owner decision and final gate in a permanent,
   record-only pull request.
4. Update and close #110, then mark the Phase 0 gate in #44 complete and #48
   unblocked.

Until every step is complete, `releaseDisposition` stays `pending-owner` and
`phase1Unlocked` stays `false`.
