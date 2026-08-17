# Phase 2 private-candidate isolation gate

The Phase 2 static target is developed and validated from committed synthetic
fixtures. Candidate-v7 and `phase-1-production-inputs-v2.tar` stay below the
ignored `local-data/` root and are never CI or build inputs.

Run the metadata-only isolation gate after producing the static build:

```bash
python scripts/repository/check_candidate_isolation.py \
  --repository-root . \
  --build-root src/web/dist
```

The gate checks committed path names, ignore policy, committed workflow text,
and static-output path/symlink metadata. It deliberately does not enumerate or
read Candidate-v7 or TAR bytes. Run it from the clean clone used for the Issue
#68 evidence receipt so the production build's inputs are limited to committed
synthetic fixtures.

This local gate cannot prove absence from every external storage service.
`uploaded: false` remains an explicit owner/operator declaration; repository
approval does not authorize publication, upload, deletion, or mutation of the
candidate, external resources, credentials, GitHub environments, or secrets.
