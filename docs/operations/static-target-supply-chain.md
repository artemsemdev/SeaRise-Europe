# Static-target supply-chain transition validation

The Phase 2 target supply-chain authority is
`contracts/supply-chain/v2/static-target-profile.json`. Run its repository gate
from a clean checkout before approving a dependency, build-plane, workflow, or
SBOM change:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  historical-inventory \
  --profile contracts/supply-chain/v2/static-target-profile.json \
  --repository-root .

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
CI/CodeQL workflows contain the exact job selectors assigned to #70 (frontend),
#71 (Python, API/.NET, CodeQL C#, and blob-seed), and #72 (Compose plus the
legacy API/frontend Dockerfiles).
Removing or changing a selector without updating the transition record
fails closed; claiming `active` before all selectors disappear also fails.
Package selectors are normalized from the actual requirement syntax, so valid
PEP 508 whitespace or underscore variants cannot bypass the gate. After the
Python blockers clear, `pyproject.toml` and `requirements-pipeline.txt` must
both exactly match the static contributor authority. Final activation also
proves the API, frontend, blob-seed, solution, Compose, and Compose-smoke paths
are absent, both PostGIS initialization scripts and the API/frontend Dockerfiles
are absent, and no reviewed .NET/C# legacy workflow jobs remain. A constrained
YAML mapping parser enforces exact top-level job identity, derives any
consistent positive jobs-child indentation, recognizes quoted and colon-spaced
keys, and rejects duplicates; token formatting or split environment-variable
values cannot erase the blocker.

Selector source files carry profile SHA-256 bindings. Path-presence selectors
do not hash mutable legacy content: they use `lstat`-equivalent checks so files,
directories, and broken symlinks all block final activation. The repository
removal approval contract separately binds the audited Git commit and tree.

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
The v2 profile binds its SHA-256, complete 48-file subtree tree, exact reviewed
Git commit/tree, and exact historical validator Git blob. The
`historical-inventory` command first compares every retained v1 path and byte,
then materializes the archived schema, dependency inputs, and validator in a
temporary directory. It verifies the validator SHA-256 and Git blob before
executing that archived implementation; the mutable Phase 2 validator is never
used as historical authority. Git history must therefore be available to this
gate; CI checkout must not omit the recorded commit. A Phase 1 record does not
reactivate a deleted runtime. The retained v1 root and every path component are
resolved strictly beneath the repository before traversal or reads; symlinks at
the root or below it fail closed.

Current-tree discovery fails closed for alternative npm, pnpm, and Yarn locks;
Pipenv, Poetry, uv, requirements, and pyproject Python authorities; and all four
`compose`/`docker-compose` YAML filename aliases unless the profile classifies
them explicitly.

## Updating authority

Review the changed dependency-defining bytes, regenerate the affected SBOM when
applicable, update the exact v2 hash, and run the focused supply-chain tests.
The profile does not authorize publishing local Candidate-v7 bytes, changing
external resources, or making production, signing, scientific-approval,
vulnerability-completeness, or licence-completeness claims.

For a new isolated npm toolchain such as `tools/static-quality`, use this order:

1. Land this versioned transition before changing the current CI workflow.
2. Rebase the toolchain branch onto it and retain all v2 files.
3. Add the tool manifest and lock as a distinct v2 npm component and input map.
4. Update the v2 SHA-256 for the final rebased `ci.yml` bytes in the same commit.
5. Run `historical-inventory` first and `static-profile` second, then run the
   tool installation and host-quality jobs.

The discovery gate rejects the tool manifests until step 3, while the exact CI
hash rejects the workflow change until step 4. Do not refresh v1 inventory or
its build-plane SBOM to make either Phase 2 change pass.
