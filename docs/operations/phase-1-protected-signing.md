# Phase 1 protected keyless signing

`.github/workflows/phase-1-release-sign.yml` is a manual-only, reviewable path
for keyless Cosign signatures over one controlled candidate's exact manifest
and deterministic provenance bytes. The only job allowed to request an OIDC
token is the signing job, and that job targets the protected environment
`phase-1-production-signing`.

The workflow refuses pull-request, fork, non-master, mutable-revision, rerun,
and non-controlled-build inputs. A second job has no OIDC permission or
protected environment. It downloads the original candidate and retained
evidence again, validates the exact uploaded archive and subject bytes, then
verifies both Sigstore identities against:

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

This public repository's authenticated readers can download retained workflow artifacts
during their 14-day lifetime. They contain review evidence, not secrets, and are not
product publication: the workflow does not release, deploy, publish or activate a candidate,
or perform public post-upload readback. Production, publication, and scientific approval
remain false; the later publication/readback gate must produce separately reviewed evidence.
