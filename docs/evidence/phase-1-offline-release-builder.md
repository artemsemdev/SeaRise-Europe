# Phase 1 Offline Release Builder Evidence

> **Issue:** [#49](https://github.com/artemsemdev/SeaRise-Europe/issues/49)
>
> **Disposition:** implementation evidence complete; candidate publication is
> not authorized by this record.

## Reviewed implementation

The builder is split into strict profile compilation, a typed seven-stage
engine, release handlers, an operator runner/CLI, an external receipt schema,
and a digest-pinned Linux container. The public release contracts delivered by
#48 remain the authority for the assembled candidate. Regional and full-Europe
use controlled reviewed inputs but execute the same graph as the fixture.

The merge sequence into `integration/phase-1-public-contracts` is:

| PR | Boundary |
|---|---|
| [#200](https://github.com/artemsemdev/SeaRise-Europe/pull/200) | typed stage/profile contracts and failure taxonomy |
| [#201](https://github.com/artemsemdev/SeaRise-Europe/pull/201) | identity-safe cache, resume, and atomic promotion |
| [#202](https://github.com/artemsemdev/SeaRise-Europe/pull/202) | explicit fixture/regional/full profiles |
| [#203](https://github.com/artemsemdev/SeaRise-Europe/pull/203) | complete public-release handlers and validation |
| [#204](https://github.com/artemsemdev/SeaRise-Europe/pull/204) | CLI and immutable schema-validated operator receipts |
| [#205](https://github.com/artemsemdev/SeaRise-Europe/pull/205) | required fixture clean/resume CI |
| [#206](https://github.com/artemsemdev/SeaRise-Europe/pull/206) | pinned offline container and runtime identity |

## Determinism and resource evidence

`test_two_independent_fixture_builds_are_byte_identical` builds through two
independent empty cache roots and compares every relative path and byte. The
pinned CI clean/resume job separately compares all 42 candidate files and
requires seven misses followed by seven verified hits. PR #206's
[CI run](https://github.com/artemsemdev/SeaRise-Europe/actions/runs/31415497149)
passed the pipeline suite and the native Ubuntu offline fixture job with
network disabled.

A host-side macOS diagnostic execution at reviewed integration commit
`e55427f1801c70dad4e7e6cea3ddc2a8bc146067` recorded this receipt summary. It
is a receipt-shape and resource-accounting example, not controlled Linux
performance evidence. The timings are observations, not identity inputs or
performance budgets:

```json
{
  "buildId": "build-fixture-778076b014c5",
  "dataReleaseId": "searise-europe-v1.0.0-20260810-a71e683e0a2f",
  "planIdentitySha256": "778076b014c5c56f6600360ebda426329f77f42318c73f1c18a7fd4d1349364f",
  "status": "complete",
  "networkAccess": "disabled",
  "candidate": {
    "fileCount": 42,
    "byteSize": 6241836,
    "inventorySha256": "940afe0d5c50f6a66c0e9cc8db6ec0d6a629a6a0458335ee8448744dca2bed9e"
  },
  "resourceUsage": {
    "totalDurationSeconds": 0.50326,
    "peakProcessRssBytes": 144556032
  },
  "stageDurationsSeconds": {
    "verify-sources": 0.001235,
    "inspect": 0.001316,
    "normalize": 0.000792,
    "derive": 0.011373,
    "package": 0.024741,
    "validate": 0.184412,
    "assemble-release": 0.217452
  }
}
```

Two local clean invocations used independent cache roots and produced the same
42-file candidate inventory above; recursive byte diff returned no
differences. A third invocation using the first cache produced seven hits and
the same `dataReleaseId`, `planIdentitySha256`, final output identities, and
candidate inventory. Operator receipts themselves are not expected to be
byte-identical because they include measured timing and memory.

## Resume and invalidation matrix

| Condition | Expected result | Executable evidence |
|---|---|---|
| unchanged plan and verified cache | seven hits; candidate identity unchanged | `test_cli_resume_reuses_verified_cache_without_changing_candidate_identity` |
| parameter changes | new plan/stage keys; seven misses | `test_identity_changes_invalidate_affected_intermediates[parameter]` |
| code revision changes | new plan/stage keys; seven misses | `test_identity_changes_invalidate_affected_intermediates[code]` |
| tool identity changes | new plan/stage keys; seven misses | `test_identity_changes_invalidate_affected_intermediates[tool]` |
| source receipt changes | source reverified; new plan/stage keys; seven misses | `test_identity_changes_invalidate_affected_intermediates[source]` |
| cached output bytes change | fail `stale-cache`; no new candidate | `test_tampered_cache_fails_closed_instead_of_being_reused` |
| declared input hash/symlink differs | fail before cache reuse; no candidate | `test_declared_inputs_are_reverified_before_cache_use` |

Invalidation is intentionally conservative: each of the four identity classes
invalidates the full graph. This is safe even where a future dependency model
could prove a narrower affected suffix.

## Failure injection and completeness

The engine test injects a typed failure at `normalize`. Only the preceding two
complete cache objects remain, no candidate exists, and the next run records
two hits followed by five misses. Other tests cover empty stage output,
pre-existing immutable candidate, incomplete/extra/tampered cache entries,
unsafe paths, receipt overwrite, and a receipt path nested in a candidate.

The CLI failure test injects `disk-pressure` with a credential-like raw
diagnostic. It proves that the candidate and execution receipt do not exist,
the failure receipt says `candidateState=not-created`, and neither stdout nor
the receipt contains the raw secret. Profile/model tests reject unknown fields,
unsorted identities, invalid timestamps, unsupported profiles, network access,
and a changed or incomplete graph.

## Acceptance conclusion

- Checked-in profiles, public schemas, reviewed source/build receipts, exact
  code revision, tool identities, inputs, and canonical parameters completely
  describe a candidate build.
- Clean, independent, and resumed fixture builds preserve public bytes and
  stable artifact identities.
- Stage outputs and receipts are inventoried, validated, and atomically
  promoted; partial work cannot become a complete candidate.
- No graph stage can upload, mutate a database, change a release pointer, or
  activate production.
- The legacy modules remain checked in for parity through Phase 3.
- Publication, scientific changes, and production authority remain outside
  #49.

Operator recovery and the explicit scientific/packaging reproducibility
boundary are documented in the
[offline release builder runbook](../operations/offline-release-builder.md).
