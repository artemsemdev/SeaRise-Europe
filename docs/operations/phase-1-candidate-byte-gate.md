# Phase 1 candidate byte gate

For the exact private real-source `candidate-v7`, including its local paths,
retained authorities, assembly history, and expected results, use the
[Phase 1 private final candidate runbook](phase-1-private-final-candidate.md).

Use the byte gate after all 54 Phase 1 candidate artifacts have been assembled
and `manifest.json` has been written as the terminal completeness marker:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_candidate_bytes.py \
  --candidate-root /absolute/path/to/candidate
```

Normal CI exercises the complete synthetic assembly path with:

```bash
PYTHONPATH=src/pipeline python scripts/release/assemble_candidate_fixture.py \
  --receipt contracts/candidate-completeness/v2/fixtures/assembly/complete-synthetic.json \
  --output /absolute/new/path/to/candidate
```

The output path must be absolute and must not exist. Every pathname component
must be symlink-free. Its existing parent must be owned by the current user and
must not be group/world writable. The assembler verifies each of the 51 explicit
fixture inputs, generates both gate reports and the checksum inventory, writes
the manifest last, validates the complete staged bytes, and promotes the
read-only directory with a platform-native no-overwrite rename. This is local
candidate promotion only; it is not public release publication.

Staging and rollback use device/inode ownership ledgers and atomically move
owned entries to high-entropy private names before cleanup. A foreign or
ambiguous entry is never unlinked. POSIX provides no conditional unlink, so a
successful or failed run can retain one mode-0700 `.candidate-assembly-*`
wrapper per invocation outside the public output name. Repeated runs can retain
multiple wrappers. Remove a wrapper only after the assembler process has exited,
or let the ephemeral CI workspace remove it. Rollback moves the exact owned
directory away from the public name before any fallible thaw or residue cleanup.
Transient rollback rename failures are retried. A persistent kernel refusal preserves the primary validation error,
adds an explicit `assembly-rollback` cleanup failure, and can leave the exact
owned failed directory at the public name; isolate that failed workspace before
operator cleanup. Once rollback clears the public name, a later thaw or sync
failure can retain the failed candidate under a high-entropy
`.candidate-rollback-*` sibling, but does not restore it to the output name.
Cleanup-only staging or descriptor errors after the final linearization do not
change the already truthful success result.

Run the assembler in one isolated process. It rejects reentrant calls, but its
portable POSIX boundary cannot defend against malicious hooks in that process,
a hostile same-user peer, an inherited/open writable staging-file descriptor,
or an ACL that contradicts the checked mode bits. Those capabilities are outside
this local assembly contract and must be excluded by the protected runner.

The validator fails closed unless the root contains exactly the 54 artifact
paths declared by the candidate contract plus `manifest.json`. It rejects
missing or extra entries, symlinks, hard links, special files, unsafe paths,
byte-size or SHA-256 mismatches, non-canonical `checksums.txt` content, and
identity drift through its final descriptor-bound linearization pass. It rejects
the first unexpected directory entry with bounded diagnostics and rejects more
than 64 GiB for one artifact or 256 GiB across the 54 artifacts. The validator
performs no repair or write operation.

The byte gate dispatches by the candidate's exact `$schema`: the immutable v1
53-artifact contract remains supported for historical verification, while new
assembly uses v2. A v1 candidate cannot be coerced through the v2 inventory, or
vice versa.

Success proves that the locally assembled bytes match the exact engineering
candidate metadata at the linearization point where the candidate pathname is
reopened immediately before the final identity pass. That descriptor remains
open for the complete pass. Matching identities during the pass prove the tree
had not drifted before the point. The summary is an observation, not a lease on
the mutable candidate pathname. Keep the candidate offline and rerun the gate
immediately before another process consumes it. Success does not prove
historical filesystem write order, artifact-format correctness, production
readiness, scientific approval, signing, supply-chain approval, or publication.
Those decisions remain in their independent gates.
