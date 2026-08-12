# Phase 1 candidate byte gate

Use the byte gate after all 53 Phase 1 candidate artifacts have been assembled
and `manifest.json` has been written as the terminal completeness marker:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_candidate_bytes.py \
  --candidate-root /absolute/path/to/candidate
```

The validator fails closed unless the root contains exactly the 53 artifact
paths declared by the candidate contract plus `manifest.json`. It rejects
missing or extra entries, symlinks, hard links, special files, unsafe paths,
byte-size or SHA-256 mismatches, non-canonical `checksums.txt` content, and
identity changes during validation. Reads are descriptor-bound and the
validator performs no repair or write operation.

Success proves that the locally assembled bytes match the exact engineering
candidate metadata at the time of validation. It does not prove historical
filesystem write order, artifact-format correctness, production readiness,
scientific approval, signing, supply-chain approval, or publication. Those
decisions remain in their independent gates.
