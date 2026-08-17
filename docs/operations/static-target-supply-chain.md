# Static-target supply-chain transition validation

The Phase 2 target supply-chain authority is
`contracts/supply-chain/v2/static-target-profile.json`. Run its repository gate
from a clean checkout before approving a dependency, build-plane, workflow, or
SBOM change:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  static-profile \
  --document contracts/supply-chain/v2/static-target-profile.json \
  --repository-root .
```

The current readiness record validates 53 exact inputs. It also regenerates and compares the
static `src/web` npm SBOM and the Linux/macOS release and settlement Python
SBOMs against their locked graphs. Input paths must be repository-relative,
regular, non-symlinked files with exact SHA-256 values.

The v2 npm artifact uses the explicit `static-web-npm-lock-only` scope and is
derived from a root lock with exactly one `src/web`
workspace. Next.js packages and `src/frontend` workspace metadata fail closed.
The v2 contributor manifest likewise omits and rejects the legacy
`psycopg2-binary` and `azure-storage-blob` adapters while retaining the exact
release and settlement graphs used by deterministic builds.

The current repository is not yet represented as static-only. The profile is
`pending-legacy-removal` while hash-bound Python contributor manifests and
CI/CodeQL workflows contain the exact selectors assigned to issues #71 and
#72. Removing or changing a selector without updating the transition record
fails closed; claiming `active` before all selectors disappear also fails.

## Legacy boundary

The active profile rejects all of these as requirements:

- `src/api` and NuGet;
- `src/frontend` and its separate Next.js lock;
- `infra/blob-seed` and Azurite seed dependencies;
- Compose manifests;
- legacy API, frontend, or blob-seed runtime images.

Phase 1 evidence under `contracts/supply-chain/v1` is retained unchanged for
audit history. Do not run its dependency-input inventory as the current-tree
Phase 2 gate: it intentionally records the Phase 1 repository boundary.
Algorithm tests and historical evidence validators remain useful, but a Phase 1
record does not reactivate a deleted runtime.

## Updating authority

Review the changed dependency-defining bytes, regenerate the affected SBOM when
applicable, update the exact v2 hash, and run the focused supply-chain tests.
The profile does not authorize publishing local Candidate-v7 bytes, changing
external resources, or making production, signing, scientific-approval,
vulnerability-completeness, or licence-completeness claims.
