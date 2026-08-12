# Phase 1 protected artifact boundary

The protected signing workflow must not trust a downloaded artifact merely
because its name matches. Before download, capture the GitHub run response and
the complete artifact-list response for the controlled run. Then create one
authority receipt atomically:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  protected-candidate-authority \
  --run-json candidate-run.json \
  --artifacts-json candidate-artifacts.json \
  --profile regional \
  --source-revision "$SOURCE_REVISION" \
  --candidate-run-id "$CANDIDATE_RUN_ID" \
  --output candidate-artifact-authority.json
```

The validator requires the reviewed repository name and numeric ID, controlled
workflow path and name, `master`, exact source SHA and run ID, first attempt,
`workflow_dispatch`, completed/success state, no pull requests, and one exact
unexpired artifact. Its name, numeric ID, byte size, SHA-256 digest, API URLs,
repository IDs, branch, source SHA, and workflow-run binding must all agree.
The emitted receipt is canonical JSON, completed and synchronized under a
bounded private same-directory partial name, re-read through its held
descriptor, and exposed only by an atomic no-overwrite hard-link operation at
mode `0400`. The private link is ownership-checked and removed before the
directory is durably synchronized; the durable directory sync and final
descriptor/path checks are the success boundary. A write, synchronization,
promotion, cleanup, or ownership failure rolls back only the implementation's
inode through a private quarantine and never deletes racing bytes. Partial
receipt bytes are never exposed at the destination. The receipt carries
explicit false production, publication, and scientific-approval claims.

After downloading the exact artifact ZIP by numeric artifact ID, extract it
through the authority receipt:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  protected-candidate-extract \
  --archive candidate.zip \
  --authority candidate-artifact-authority.json \
  --output-root candidate-download
```

Candidate extraction verifies the archive's exact size and digest from the
authority, applies the candidate byte-gate ceilings, and requires exactly the
`candidate/`, `dispatch.json`, and `execution.json` top-level boundary. The
dispatch, complete execution, and real-source offline build receipts are
strictly validated and mutually bound. Run the separate candidate byte gate on
`candidate-download/candidate` before signing; extraction is transport
validation, not candidate approval.

Evidence extraction has a smaller, distinct inventory and byte budget:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  protected-evidence-extract \
  --archive evidence.zip \
  --expected-sha256 "$EVIDENCE_ARCHIVE_SHA256" \
  --expected-byte-size "$EVIDENCE_ARCHIVE_BYTES" \
  --output-root evidence-download
```

Both extractors reject traversal, absolute or non-canonical paths, duplicate
members, encrypted entries, links and other non-regular entries, unsupported
compression, unexpected inventories, empty or oversized members, aggregate
expansion beyond the policy, existing destinations, archive mutation, and
descriptor identity drift. Files are streamed into a new private directory
with `O_EXCL` and `O_NOFOLLOW`; the implementation never uses recursive ZIP
extraction or recursive filesystem discovery. A failed extraction may leave a
private, incomplete destination for inspection and must never be reused.

None of these commands signs bytes or establishes production readiness,
publication, scientific approval, protected-environment approval, or public
readback. Their success records are canonical single-line JSON with exact run,
artifact, digest, byte-size, and output identity where applicable, plus the
three false claims. Output is explicitly flushed as a best-effort diagnostic
after the operation commits: a closed or failed stdout cannot turn committed
receipt or extraction bytes into a false nonzero result that invites an unsafe
retry.
