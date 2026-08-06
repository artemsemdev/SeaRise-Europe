# Phase 0R owner promotion

The final Phase 0R decision is recorded only by
`.github/workflows/phase-0r-owner-promotion.yml`. JSON created by a local
invocation is not authoritative and must not unlock Phase 1.

## One-time repository prerequisite

Create the GitHub environment `phase-0r-owner-approval` before the first
promotion run. Configure `artemsemdev` as its required reviewer and restrict
deployments to the `master` branch. Because the project currently has one
owner, the environment must allow that reviewer to approve a run they
dispatched. This repository change deliberately does not create or weaken the
external environment policy.

## Promotion sequence

1. Merge the reviewed code integration pull request to `master`. Its exact
   merge commit is candidate source `S`; record that pull-request number in the
   committed evidence summary.
2. Dispatch `CI` on `master@S`. The first run attempt must complete both
   `Full-source Linux AR6 candidate` and `Full-source macOS ARM64 AR6
   candidate`. Keep the two fixed-name artifacts, ZIP digests, distinct job
   IDs, distinct receipt build IDs, distinct validated profiles, and exact
   `build-timing-linux.json` / `build-timing-macos-arm64.json` records. The
   trusted macOS artifact also contains `browser-trace-macos-arm64.json`.
3. Create a separate evidence branch directly from `S`. Commit the trusted
   macOS binding, raw `build-timing-macos-arm64.json` and
   `browser-trace-macos-arm64.json`, canonical delivery report,
   pending-external reproducibility report, strict automated gate, checksums,
   summary, changelog, and final evidence document. The linear `S..E` history
   may change only those fixed paths; code, workflows, contracts, other
   documentation, deletions, symlinks, submodules, merges, and reverted
   intermediate changes are rejected.
4. Merge the evidence-only pull request without intervening `master` changes.
   Its merge commit `M` must have parents `[S, E]`, its tree must equal `E`,
   and current `master` must still equal `M` when promotion starts.
5. Dispatch `Phase 0R owner promotion` from `master`. Supply only the positive
   validation run ID, positive evidence pull-request number, and `approved` or
   `rejected` decision, then approve the protected-environment deployment.
6. The workflow recomputes delivery metrics from the downloaded macOS
   candidate, its trusted timing and browser trace, and the pinned repository
   harness. The committed trace and timing bytes must equal the trusted
   artifact bytes; a summarized report alone is never sufficient.
7. Treat the 90-day Actions artifact only as transport. Immediately open a
   focused record-only pull request that commits its five exact files under
   `src/pipeline/evidence/ar6-regional-release/owner-promotion/`:
   `owner-attestation.json`, `integration-merge.json`, `promotion.json`,
   `final-gate.json`, and `checksums.txt`. Do not close #110 or unlock #48
   until that permanent record PR is merged and its checksums verify.

Rerun attempts are rejected. Fixed global concurrency serializes decisions,
prior successful workflow/artifact history blocks a second decision for the
same release ID and source `S`, and a committed permanent owner-record root
blocks every later decision attempt.

The first successful owner decision is immutable for that release candidate.
A mistaken or intentional rejection cannot later be changed to approval by a
second workflow run or another evidence pull request. Recovery requires a new
reviewed candidate source and new integration/evidence pull requests.

The job fails closed if the actor, triggering actor, repository, ref,
validation workflow, either job/artifact/timing record, source SHA, code
integration pull request, evidence-only pull request, merge parents/tree,
committed evidence, prior-decision history, or either candidate binding
differs. Approval is effective only when the final gate says
`automatedValidation=passed` and the protected owner decision says `approved`.
