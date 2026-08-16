# Phase 2 private release binding

This optional workflow exercises the static browser against the exact ignored
Phase 1 candidate without copying candidate bytes into source, `dist`, CI, an
artifact upload, or external storage. It is a private engineering test, not a
release, signature, verification event, publication, or promotion.

The candidate remains local at the owner-recorded path:

```text
local-data/phase-1/local-production-run/candidate-v7/
```

The required AR6 source-grid identity is also an explicit ignored local input.
The harness has no default paths and performs no discovery.

## One-command browser check

From the repository root, set both absolute paths explicitly:

```bash
export SEARISE_LOCAL_CANDIDATE_ROOT="$PWD/local-data/phase-1/local-production-run/candidate-v7"
export SEARISE_LOCAL_SOURCE_GRID="$PWD/local-data/phase-1/ar6-regional-candidate/phase-0r-ar6-v1/analysis/source-grid.json.gz"
export SEARISE_LOCAL_PORT=4174

npm run e2e:local-candidate --workspace @searise/web
```

The owned Node runner first starts the normal Vite development server and
proves its explicit filesystem allowlist denies exact and encoded Candidate and
source-grid `/@fs` probes while required modules, fonts, and the committed
synthetic fixture remain readable. It then creates a temporary,
non-distributable browser bundle under the private `0700` overlay and starts
one loopback origin. The bundle, ephemeral private manifest, and allowlisted
candidate artifacts are served from that origin, so the production document
CSP remains unchanged and the private server has no `/@fs` route.

For interactive inspection, use the same explicit environment and run:

```bash
npm run serve:local-release --workspace @searise/web
```

Open the exact loopback origin printed by the process. Stop it with `Ctrl-C`.

## Read-only and private guarantees

Before listening, the adapter:

1. requires an absolute, real, non-symlink candidate directory whose
   directories and files have no write bits;
2. hashes the complete candidate tree and validates every declared artifact
   size and SHA-256 against the local candidate manifest;
3. requires an explicit, non-symlink, read-only source-grid file with the
   reviewed AR6 byte size and SHA-256;
4. creates only small release-v2 adapter metadata beneath a newly created
   `0700` operating-system temporary directory and writes every file as `0600`;
5. serves candidate artifacts in place through an exact manifest-derived
   allowlist—there is no generic filesystem route;
6. rechecks real path, symlink status, regular-file type, inode, device, byte
   size, and full SHA-256 on every open, rejecting same-size mutation; and
7. pins the exact temporary directory identity and refuses cleanup if that
   directory was replaced.

For the automated command, the owning runner awaits server shutdown in a
`finally` block after either Playwright success or failure. It compares the
exact temporary-overlay inventory before and after and fails if the run leaves
a new overlay. Unit controls exercise both lifecycle paths. Pre-existing
temporary directories are never deleted. Interactive `serve:local-release`
performs the same pinned cleanup on handled `SIGINT`/`SIGTERM`; an uncatchable
process kill cannot provide a cleanup guarantee.

The adapter accepts `GET` and `HEAD` only. It implements strict single byte
ranges, returns `416` for suffix, malformed, out-of-bounds, or multi-range
requests, emits hash ETags, and rejects cross-origin or unlisted paths. Its
actual response cache policy is `private, no-store`.

The ephemeral metadata states all of the following explicitly:

```json
{
  "privateEngineeringOnly": true,
  "verified": false,
  "publicPromotionAuthorized": false,
  "signatureAvailable": false
}
```

No public signature or base-candidate provenance is created: the private
manifest declares `baseReleaseSignature` and `baseReleaseProvenance` as
`null`. The base Candidate identity is recorded separately from the browser
adapter invocation. Dedicated deterministic browser-derivation receipt and
in-toto evidence use `executionIdentity: "not-recorded"` and make no build-run,
workflow, platform, timestamp, code-revision, approval, or publication claim.

## Browser evidence

The private Playwright suite runs in page context and proves:

- the unchanged production CSP and same-origin CORS identity;
- the private disclosure and a schema-valid release-v2 adapter manifest;
- `HEAD`, exact `206` ranges, hash ETags, and `416` malformed/multi ranges;
- all nine scenario/horizon combinations through the real
  `AssessmentEngine` and `CogAnalysisArtifactReader`, including exact
  three-band values and nearest native source-grid identity;
- all four ADR-024 scientific outcomes and a separate technical-failure path;
- denial of `/@fs`, encoded traversal, and direct absolute local-file probes;
- denial of the same exact inputs through the separately started normal Vite
  development server without breaking required modules, fonts, or the
  committed synthetic fixture;
- rejection of a non-allowlisted release path;
- zero `/assess`, `/geocode`, or `/config` application requests; and
- the complete Candidate-v7 snapshot is byte-identical before and after; and
- no new private temporary-overlay identity remains after the owned run.

Normal `npm run web:check` and `npm run web:e2e` remain clean-clone tests over
the committed synthetic fixture. They never read these environment variables
or private paths.

## Prohibited actions

- Do not create or retain a distributable production build with
  `private-engineering` disposition. The harness's sealed temporary test bundle
  is deleted with its private overlay.
- Do not copy the candidate, source grid, or temporary overlay into `src/web`,
  `dist`, a Git worktree, CI, GitHub Actions artifacts, R2, or another store.
- Do not relax candidate permissions or modify Candidate-v7 to make a test
  pass.
- Do not treat `verified:false` local metadata as approval or promotion.
- Do not delete cloud resources, credentials, environments, or secrets; this
  workflow authorizes no external cleanup.
