# Repository-removal approval contract

Repository deletion under ADR-025 is authorized by three immutable documents:

1. `v1/inventory.json` assigns every in-scope repository item one disposition.
2. `v1/evidence-receipt.json` binds passing replacement evidence to the exact
   audited integration commit and inventory digest.
3. `v1/owner-decision.json` records the project owner's exact, narrow approval.

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

The schemas define the closed document shapes; the trusted offline validator
enforces all cross-document, Git-object, command, path, and GitHub-comment
relationships. SHA-256 is calculated over the committed file bytes. The evidence receipt
names the inventory digest plus the schemas, validator, test inventory,
historical allowlist, and replacement matrix. The owner decision names both
the inventory and evidence-receipt digests, repeats the audited commit, and
records the OWNER-associated Issue #68 comment. Any edit invalidates the
approval chain and requires a new owner decision.
