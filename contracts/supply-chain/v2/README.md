# Static-target supply-chain transition profile

Version 2 defines the target supply-chain boundary for the Phase 2 static
browser application. It locks the exact inputs for the `src/web` npm workspace, Python
release/contributor/settlement graphs, retained native and container build
plane, signing tool, vendored CycloneDX schemas, and five reusable static-target
SBOMs. The npm SBOM is published under `v2/sboms` from the root lock whose sole
workspace is `src/web`; active validation rejects Next.js components and any
`src/frontend` workspace property.

The target graph deliberately has no requirement for NuGet, `src/api`,
`src/frontend`, Azurite/blob-seed, Compose, or any legacy runtime image. The
validator rejects those paths even if a profile edit supplies a valid hash.
This makes deletion of those runtime trees independent from the active
supply-chain gate.

The checked-in profile is honestly `pending-legacy-removal`: issue #70 owns the
frontend/Next.js CI selector; issue #71 owns Azure/PostGIS, API/.NET, CodeQL C#,
and blob-seed removal; issue #72 owns Compose and the legacy API/frontend
Dockerfiles. Exact workflow jobs and Python selector source files are hash-bound;
path-presence
selectors carry issue ownership but intentionally bind existence rather than
mutable legacy content. The validator derives both kinds from repository
bytes; it rejects an `active` claim while any remain. Once the last selector is
removed, only an `active` record with no blockers or pending selectors can pass.
Python package names are parsed and normalized independently of PEP 508
whitespace, punctuation, or case. Clearing #71 also requires both real
contributor manifests to match the v2 static authority package-for-package and
constraint-for-constraint. Active status additionally requires tracked absence
of the API/frontend/blob-seed trees, PostGIS initialization scripts, root
solution, API/frontend Dockerfiles, Compose file, and Compose smoke script.
Absence uses `lstat`-style semantics, so a broken symlink still blocks
activation. Workflow blockers are exact top-level job identities, so whitespace
or split environment-variable indirection cannot erase a job-removal obligation.

The v2 contributor manifest is intentionally separate from the pre-removal
`src/pipeline` development manifests. It retains the static build/data pipeline
dependencies and rejects `psycopg2-binary` and `azure-storage-blob`; exact
candidate execution remains governed by the retained release graphs and locks.

`contracts/supply-chain/v1` remains immutable Phase 1 historical evidence. Its
NuGet and legacy runtime records describe that reviewed candidate boundary;
they are not the current application dependency graph and must not be rewritten
to resemble the Phase 2 target. The v2 transition record binds the complete
48-file v1 subtree tree, exact inventory bytes, reviewed Git commit/tree, and
validator semantics. Historical validation compares every retained v1 path and
byte, materializes the archived schema and dependency inputs, and validates them,
so a Phase 2 workflow edit or later legacy deletion cannot be mistaken for v1
evidence drift.

Validate the active profile from the repository root:

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

Validation is fail-closed over the exact path-to-component-to-role map, bound
repository-local schema, safe regular-file ancestry, SHA-256 bindings, build
profiles and Docker context, static npm SBOM, exact `src/web` manifest/lock
parity, and four target-specific Python SBOMs. It makes no production, vulnerability, licence
completeness, publication, signing, or scientific approval claim.

When an active dependency, workflow, recipe, lock, graph, receipt, schema, or
SBOM changes, review that change and update its profile hash in the same pull
request. Adding a new active input requires an explicit validator contract
change; removing a required retained input fails closed. Current-tree discovery
also rejects unclassified npm manifests/locks, workflows, local actions, Docker
recipes, Python manifests/locks, native tool authority, build profiles, v2 SBOMs,
and scoped schemas.
