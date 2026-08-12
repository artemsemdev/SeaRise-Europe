# Phase 1 candidate byte gate

Use the byte gate after all 53 Phase 1 candidate artifacts have been assembled
and `manifest.json` has been written as the terminal completeness marker:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_candidate_bytes.py \
  --candidate-root /absolute/path/to/candidate
```

Normal CI exercises the complete synthetic assembly path with:

```bash
PYTHONPATH=src/pipeline python scripts/release/assemble_candidate_fixture.py \
  --receipt contracts/candidate-completeness/v1/fixtures/assembly/complete-synthetic.json \
  --output /absolute/new/path/to/candidate
```

The output path must not exist. The assembler verifies each of the 50 explicit
fixture inputs, generates both gate reports and the checksum inventory, writes
the manifest last, validates the complete staged bytes, and promotes the
read-only directory with a platform-native no-overwrite rename. This is local
candidate promotion only; it is not public release publication.

The validator fails closed unless the root contains exactly the 53 artifact
paths declared by the candidate contract plus `manifest.json`. It rejects
missing or extra entries, symlinks, hard links, special files, unsafe paths,
byte-size or SHA-256 mismatches, non-canonical `checksums.txt` content, and
identity drift through its final descriptor-bound linearization pass. It rejects
the first unexpected directory entry with bounded diagnostics and rejects more
than 64 GiB for one artifact or 256 GiB across the 53 artifacts. The validator
performs no repair or write operation.

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
