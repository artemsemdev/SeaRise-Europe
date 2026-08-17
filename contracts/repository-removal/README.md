# Repository-removal approval contract

Repository deletion under ADR-025 is authorized by three immutable documents:

1. `v1/inventory.json` assigns every in-scope repository item one disposition.
2. `v1/evidence-receipt.json` binds passing replacement evidence to the exact
   audited integration commit and inventory digest.
3. `v1/owner-decision.json` records the project owner's exact, narrow approval.

`v1/census.json` is the canonical #70/#71/#72 scope. The validator expands its
roots against the audited Git tree, verifies every semantic selector exists
exactly once, and requires the delete inventory to match that expanded set
without missing, extra, duplicate, or cross-owned locators.

`v1/historical-allowlist.json` is a separate exact-path, audited-blob document.
It cannot use directory globs or active target paths and never permits an
allowlisted term in active runtime.

`canonical-design-reference` is reserved for the exact reviewed Flight mock.
It preserves that file as the product's visual and interaction reference while
making no scientific authorization claim for embedded prototype logic or copy.
The referenced bytes must remain excluded from the static application and its
built output; the rule is not a general documentation exemption.

The schemas deliberately separate repository cleanup from external cleanup.
Every inventory item must declare `externalMutationAuthorized: false`, and an
owner decision cannot authorize Candidate-v7 publication or mutation of cloud
resources, credentials, GitHub environments, or secrets.

## Dispositions

- `delete-phase-2`: delete only through the named Issue #70, #71, or #72 gate.
- `retain-build-science`: keep as an active deterministic build, science,
  contract, fixture, or target-test asset.
- `retain-historical-evidence`: keep only as clearly classified history that
  cannot enter the active target domain or runtime bundle.
- `defer`: keep with a named owner, reason, and follow-up issue.

Git history is the source-recovery path. Product rollback uses a previously
verified static application/release pair. Neither mechanism expands the
approval to external resources.

## Hash chain

The schemas define the closed document shapes; the trusted validator
enforces all cross-document, Git-object, command, path, and GitHub-comment
relationships. SHA-256 is calculated over the committed file bytes. The evidence receipt
names the inventory digest plus the census, schemas, validator, test inventory,
historical allowlist, and replacement matrix. The owner decision names both
the inventory and evidence-receipt digests, repeats the audited commit, and
records the OWNER-associated Issue #68 comment. Any edit invalidates the
approval chain and requires a new owner decision.

Every check hash is recomputed from its retained command-output file. Every
deletion item links active replacement suites and receipt check IDs, and every
legacy suite owned by #70/#71/#72 is mapped exactly once for retirement. An
approved chain passes only when the recorded Issue #68 comment is fetched from
GitHub and its ID, URL, body, author login, and `OWNER` association all match.

Check outputs are closed JSON documents committed only below
`tests/evidence/repository-removal/v1/`. Each document is schema-validated and
must exactly bind its audited commit, check ID, command, and passing result;
the receipt binds its bytes by SHA-256. A tracked log or arbitrary repository
file cannot substitute for this output. Receipt checks declare the exact
replacement suites and target-owner paths they cover, and deletion items must
match those declarations bidirectionally. A check command must be byte-for-byte
equal to `commands.focused` or `commands.full` for every suite it claims. Each
covered suite must own at least one covered target path through its
`sourcePaths`, and every covered target path must match a covered suite pattern
with slash-aware glob semantics. The canonical census separately limits and
requires replacement suite IDs for each owning issue, so consistent relabelling
across an inventory and receipt cannot turn unrelated evidence into authority.

## Integration gate

PR #421's `approvedRemovalChain` gate must execute the validator with live
comment verification enabled:

```text
python scripts/repository/validate_removal_approval.py --verify-owner-comment
```

The gate needs authenticated, read-only GitHub API access to the public Issue
#68 comment. An offline invocation, or an invocation without that flag, is not
an approved removal chain and must block integration. Apply this exact command
and a failing-without-the-flag integration test when refreshing this hardening
branch after PR #421 and the PR #422 scope-review decoupling change merge into
the integration branch. This focused branch does not edit either separate PR
worktree.
