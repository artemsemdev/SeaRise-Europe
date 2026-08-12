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
  `phase-0r-ar6-v1/...`, `build-timing-macos-arm64.json`, and
  `browser-trace-macos-arm64.json`.

The browser trace is generated only from the macOS ARM64 candidate. It uses
Node 20, the exact frontend package lock, and that Playwright release's pinned
Chromium revision to exercise the candidate through the real HTTP Range lookup
harness. The trace binds its manifest digest, artifact hashes and sizes,
golden evidence, package-lock digest, browser version, hardware profile, and
cold and warm lookup samples. Before upload, the producer validates the trace
against the candidate manifest, delivery harness, release contract, and macOS
build timing. A missing or invalid trace fails the producer job; the owner
validator independently recomputes the same bindings after download.

Artifacts are retained for 14 days and cannot overwrite an artifact from the
same run. A successful build remains a candidate with a pending scientific
disposition until the owner-validation workflow verifies both artifacts and
their cross-environment bindings.

## Phase 1 COG range validation

Phase 1 binds the exact nine analysis COG paths, SHA-256 digests, and byte sizes
to the approved candidate binding, browser trace, and owner gate before testing
delivery. Each artifact must first match its reviewed local identity. A
transport adapter is then required to return exact `206` responses with
canonical `Content-Range`, `Content-Length`, and `Accept-Ranges: bytes` headers.
Beginning, middle, end, and TIFF-directory ranges derived by the reader are
compared byte-for-byte with the trusted artifact.

The ordinary unit suite keeps a deterministic in-process transport for mutation
coverage. Pipeline CI additionally serves the checked-in release fixture from
an ephemeral loopback HTTP origin and retains an immutable
`cog-range-evidence.json` artifact for 14 days. That report binds the served
manifest, all nine COG hashes and byte sizes, the approved Phase 0R candidate
binding, every one of the 54 successful request/response records, monotonic
runner-local latency measurements, and explicit malformed, ignored, truncated,
substituted, and corrupt-response rejection controls. Its exact `producer`
object also binds the pull-request head revision, checked-out revision, workflow
run ID and attempt, constrained job name, and `time.perf_counter_ns` clock.
Validation requires the caller's expected producer identity and rejects changed
or extra producer fields.

The retained report is labelled
`candidate-bound-loopback-http-validation-only`. Its latency values are raw
process-local observations, not a delivery budget. It makes no public-origin,
CDN, cache, CORS, TLS, publication, or production-readiness claim. Public-host
validation must still run separately against the same immutable identities
before activation. Because this workflow artifact expires after 14 days, issue
#51 still requires a durable candidate-bound capture after the final candidate
is assembled; this report is not that durable release record.
