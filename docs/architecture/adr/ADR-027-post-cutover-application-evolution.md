# ADR-027 — Application evolution after completed repository cutover

> **Status:** Accepted
>
> **Decision date:** 2026-09-10
>
> **Decision owner:** Project owner
>
> **Scope:** Repository development and validation; no publication approval

## Context

Issues #72, #70, and #71 completed the repository removals authorized under
ADR-025. Their exact plans, owner decisions, validators, and application
receipts remain evidence of what was approved and applied.

The issue-71 post-application validator also requires every retained file in
the removal plan to remain identical to its application-commit version. That
includes current CI, test inventory, supply-chain profile, and content gates.
This prevents normal reviewed application maintenance after successful cutover.

The owner has authorized continued development toward the accepted coastal
atlas under epic #490; issue #493 implements this validation boundary.
Development requires evolving retained application and validation files while
preserving completed removal authority.

## Decision

Use `scripts/repository/validate_post_cutover.py` for current development and CI:

1. Pin the completed issue-71 receipt commit
   `fd38eddccb5dce6405df48a8f25c045e740efdca` and require it to be an ancestor
   of the current checked revision.
2. In CI, run the original issue-71 validator against that completed receipt.
   Keep exact historical plans, owner decisions, owner-comment verification,
   application hashes, and the full inherited approval chain mandatory.
3. Require historical authority files from all three completed removal stages
   to retain their exact Git identities and current working bytes and modes.
   Reject symlinked authority files or parent directories.
4. Require all originally deleted paths to remain absent in both the checked
   revision and working tree. Also prohibit reintroducing any content under
   the removed application and database directories.
5. Allow retained application, build, CI, dependency, and test files to evolve
   through focused reviewed pull requests and current quality gates. Their
   original approved versions remain bound to the historical application.

The JavaScript content gate and the CI removal job use the same adapter. The
current dependency/content scanners, supply-chain input hashes, test inventory,
private-data isolation, and build-output checks continue to run. This changes
the temporal scope of completed removal validation, not its historical result.

Issue #496 separates two explicitly selected validation modes. Routine source
validation uses `--evidence-only`: standard-library Python and local Git check
the pinned completed evidence, recomputed authority blob digests, current
authority files, ancestry, and removed-path absence. Missing historical objects
fail without fetching. This trusts the reviewed receipt commit as its starting
point; it does not replay historical approval validation or attest that a
GitHub comment still exists or remains unchanged today.

The CI authority job runs for both repository-authority and web changes and
selects `--verify-owner-comment`. It performs the same integrity checks and
then runs the unchanged historical validator with live GitHub verification.
Omitting a mode or selecting both fails. Output distinguishes offline evidence
integrity from live owner attestation. No synthetic GitHub responses or
substitution for the historical validator are used.

## Unchanged boundaries

This ADR does not change the current AR6 scientific contract, Flight product
reference, or browser storage authority. A later explicit product contract must
define the atlas before its runtime replaces the current application.

Candidate-v7 and other ignored local inputs remain local-only. Development
acceptance grants no source publication, production deployment, external
resource mutation, or release approval. The rejected scientific methods and
their evidence remain unchanged.

## Validation

Mutation tests must distinguish valid retained-file edits from changed receipt,
decision, validator, or filesystem authority, and from restored runtime paths.
The historical owner-verification call must remain mandatory and pinned to
the completed receipt; current-state failure must stop validation.
