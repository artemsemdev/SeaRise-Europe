# AR6 release evidence runbook

This runbook creates the two independent full-source candidates required for
Phase 0R release evidence. It does not promote either candidate or close the
scientific gate by itself.

## Preconditions

- Merge the reviewed release code and workflow to `master` first.
- Wait for the ordinary CI run on `master` to pass.
- Use the exact current `master` commit as the source revision. The workflow
  rejects integration branches, symbolic revisions, uppercase hashes, SHA
  mismatches, and re-run attempts.
- Confirm that the source archives and pinned toolchain assets are still
  reachable. Each runner needs enough temporary disk for the 9.24 GB AR6
  archive, the extracted source, and the candidate output.

## Dispatch

Fetch `master`, capture its complete 40-character SHA, and dispatch the CI
workflow from that same ref:

```bash
git fetch origin master
ar6_source_revision="$(git rev-parse origin/master)"

gh workflow run ci.yml \
  --ref master \
  -f release_evidence=true \
  -f release_source_revision="${ar6_source_revision}"
```

When using the GitHub interface, select the `master` branch, enable
`release_evidence`, and paste the complete current `master` SHA into
`release_source_revision`.

The dispatch is valid only when all of these bindings hold:

- `github.ref_name` is `master`;
- `release_source_revision` equals `github.sha`;
- `github.run_attempt` is `1`.

Do not use **Re-run jobs** for release evidence. If a job fails, resolve any
source or workflow defect through review, verify the current `master` SHA, and
start a new workflow dispatch.

## Expected evidence

One dispatch starts these independent GitHub-hosted jobs from the same source
revision:

- `Full-source Linux AR6 candidate` on `ubuntu-24.04`;
- `Full-source macOS ARM64 AR6 candidate` on `macos-14`.

Both jobs must pass. Record the workflow run ID, source SHA, job IDs, job
conclusions, and artifact IDs and digests. The expected artifacts are:

- `ar6-linux-candidate-<sourceRevision>-<runId>` containing
  `phase-0r-ar6-v1/...` and `build-timing-linux.json`;
- `ar6-macos-arm64-candidate-<sourceRevision>-<runId>` containing
  `phase-0r-ar6-v1/...` and `build-timing-macos-arm64.json`.

Artifacts are retained for 14 days and cannot overwrite an artifact from the
same run. A successful build remains a candidate with a pending scientific
disposition until the owner-validation workflow verifies both artifacts and
their cross-environment bindings.
