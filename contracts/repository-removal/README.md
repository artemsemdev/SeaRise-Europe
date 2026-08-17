# Repository-removal approval contract

Repository deletion under ADR-025 is authorized by three immutable documents:

1. `v1/inventory.json` assigns every in-scope repository item one disposition.
2. `v1/evidence-receipt.json` binds passing replacement evidence to the exact
   audited integration commit and inventory digest.
3. `v1/owner-decision.json` records the project owner's exact, narrow approval.

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

SHA-256 is calculated over the committed file bytes. The evidence receipt
names the inventory digest. The owner decision names both the inventory and
evidence-receipt digests and repeats the audited commit. Any edit invalidates
the approval chain and requires a new owner decision.
