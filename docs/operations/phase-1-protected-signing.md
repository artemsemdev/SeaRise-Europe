# Phase 1 protected keyless signing

`.github/workflows/phase-1-release-sign.yml` is a manual-only, reviewable path
for keyless Cosign signatures over one controlled candidate's exact manifest
and deterministic provenance bytes. The only job allowed to request an OIDC
token is the signing job, and that job targets the protected environment
`phase-1-production-signing`.

The workflow refuses pull-request, fork, wrong-repository-ID, non-master,
mutable-revision, rerun, and non-controlled-build inputs. Its four jobs keep
the trust planes separate:

1. `intake` has no OIDC permission or protected environment. It authenticates
   the complete controlled-run artifact inventory, downloads the artifact by
   numeric ID, safely extracts exact authority-bound bytes, runs the candidate
   byte gate, and generates deterministic provenance.
2. `sign` is the only protected job and the only job with `id-token: write`.
   It revalidates the prepared candidate and provenance before signing only
   `manifest.json` and `provenance.intoto.jsonl`.
3. `finalize` has no OIDC permission or protected environment. It runs the
   reviewed production-evidence finalizer once with dedicated private mode-0700
   snapshot and output parents. Only the exact durable evidence leaf is
   retained; the workflow contains no duplicate finalization implementation.
4. `verify` has no OIDC permission or protected environment. It independently
   authenticates and extracts the original candidate and the retained evidence
   archive, validates the truthful pre-verification envelope, and verifies both
   Sigstore identities against:

- repository: `artemsemdev/SeaRise-Europe`;
- workflow: `.github/workflows/phase-1-release-sign.yml`;
- ref: `refs/heads/master`;
- certificate identity: `https://github.com/artemsemdev/SeaRise-Europe/.github/workflows/phase-1-release-sign.yml@refs/heads/master`;
- OIDC issuer: `https://token.actions.githubusercontent.com`.

## Required owner configuration

Configure the following settings only after the reviewed final Phase 1 pull
request is merged to `master`; the certificate identity is deliberately bound
to that branch and workflow path.

1. Create the GitHub Actions environment named exactly
   `phase-1-production-signing`.
2. Add at least one required reviewer representing the repository owner's
   explicit approval. Prevent self-review and disable administrator bypass when
   the repository plan exposes those controls.
3. Restrict deployment branches and tags to the selected branch `master` only.
4. Do not add signing secrets or long-lived keys. The signing job requests the
   short-lived GitHub OIDC token through job-scoped `id-token: write`.
5. Keep default workflow token permissions read-only. The workflow explicitly
   requests only `actions: read`, `contents: read`, and, in the protected
   signing job alone, `id-token: write`.

Repository environment settings cannot be created or proven by committed code.
Until an owner configures and reviews them, the protected-environment gate is
pending and no real workflow execution is claimed.

This public repository's authenticated readers can download retained workflow
artifacts during their 14-day lifetime. They contain review evidence, not
secrets, and are not product publication: the workflow does not release,
deploy, publish or activate a candidate, or perform public readback. Production,
publication, scientific approval, protected-environment verification, and
public-readback claims remain false; any later publication/readback gate must
produce separately reviewed evidence.

## Exact local evidence handoff

The workflow artifact is an execution handoff, not the durable product-release
record. After a separately reviewed public upload and successful
`verify_public_signed_subjects.py` run, retain the exact evidence set with:

```bash
PYTHONPATH=src/pipeline python scripts/release/retain_release_evidence.py \
  --candidate-root /absolute/path/to/candidate \
  --evidence-root /absolute/path/to/finalized-evidence \
  --cryptographic-receipt /absolute/path/to/cryptographic-verification.json \
  --public-readback-receipt /absolute/path/to/public-readback.json \
  --repository-root "$PWD" \
  --output-root /absolute/release-store/<dataReleaseId>/supply-chain
```

The output parent must already exist, be owned by the runner, have mode `0700`,
and sit outside the candidate, evidence, receipt, and repository authorities.
The command publishes one no-overwrite tree containing 18 initially read-only
files: the manifest, 14 finalized evidence files, both verification receipts,
and `retention-receipt.json`. The receipt binds the other 17 exact ordered files
by byte size and SHA-256. Verify a committed tree independently with:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_release_evidence_retention.py \
  --retention-root /absolute/release-store/<dataReleaseId>/supply-chain
```

The local command proves atomic no-overwrite publication only. It cannot prove
or enforce the external store's release-lifetime policy, deletion prevention,
or co-retention with the data release. Configure and audit those controls
separately before treating this handoff as durably retained. The two retained
verification receipts remain audit records from their separate verifier gates;
the handoff does not reauthenticate them, publish or activate the candidate, or
make a production, publication, or scientific-approval claim.

A failure before the final commit never leaves `supply-chain` as a completion
path. Cleanup may preserve the owned partial tree as one bounded private
`.evidence-incomplete-*` residue under the output parent. After the process
exits, an operator may inspect and remove that residue; never rename it to the
completion path or repair a failed handoff in place.
