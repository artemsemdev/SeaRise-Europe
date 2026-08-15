# Phase 2 private release binding

This optional workflow exercises the static browser against an explicitly
selected, ignored release directory without copying, bundling, committing, or
uploading any release bytes. Clean clones and CI do not use it; they use only
the committed synthetic fixture.

The Phase 1 final candidate remains local at:

```text
local-data/phase-1/local-production-run/candidate-v7/
```

Its TAR and directory are private engineering artifacts, not public releases.
Do not add either path to a Vite public directory, GitHub Actions artifact,
object store, or source-control staging area.

## Explicit read-only test

Use two terminals from the repository root. First, select the path yourself and
start the restricted local release server. The script has no default path and
does not discover candidates:

```bash
export SEARISE_LOCAL_RELEASE_ROOT="/absolute/path/to/local-data/phase-1/local-production-run/candidate-v7"
export SEARISE_LOCAL_RELEASE_ID="$(jq -r .dataReleaseId "$SEARISE_LOCAL_RELEASE_ROOT/manifest.json")"

npm run serve:local-release --workspace @searise/web -- \
  --root "$SEARISE_LOCAL_RELEASE_ROOT" \
  --release-id "$SEARISE_LOCAL_RELEASE_ID" \
  --app-origin http://127.0.0.1:5173 \
  --port 8091
```

The server accepts only `GET` and `HEAD`, confines paths to the selected root,
supports byte ranges, and exposes only the named release on loopback. It has no
write or upload operation.

In the second terminal, start Vite with an explicit private disposition and
matching manifest URL:

```bash
export SEARISE_LOCAL_RELEASE_ID="the exact ID printed/checked above"
export SEARISE_RELEASE_DISPOSITION=private-engineering
export SEARISE_DATA_RELEASE_ID="$SEARISE_LOCAL_RELEASE_ID"
export SEARISE_LOCAL_MANIFEST_URL="http://127.0.0.1:8091/releases/$SEARISE_LOCAL_RELEASE_ID/manifest.json"

npm run web:dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`. The application must display the private,
local-only disposition. The repository rejects a mismatched release identity,
schema, path, artifact reference, provenance class, or origin. It never falls
back to the synthetic fixture or another release.

## Safety and verification

- Never run `web:build` in private-engineering mode; Vite rejects it.
- Never point this workflow at a mutable working directory during a test.
- Stop both local processes after testing. No cleanup of cloud resources,
  credentials, GitHub environments, or secrets is authorized by this runbook.
- Confirm `git status --short` contains no candidate files before committing.
- Normal verification remains `npm run web:check && npm run web:e2e`, which
  exercises only the committed synthetic fixture.
