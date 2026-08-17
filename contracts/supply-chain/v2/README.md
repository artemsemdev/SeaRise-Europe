# Active static-target supply-chain profile

Version 2 is the active supply-chain boundary for the Phase 2 static browser
application. It locks the exact inputs for the `src/web` npm workspace, Python
release/contributor/settlement graphs, retained native and container build
plane, signing tool, vendored CycloneDX schemas, and five reusable static-target
SBOMs. The npm SBOM is published under `v2/sboms` from the root lock whose sole
workspace is `src/web`; active validation rejects Next.js components and any
`src/frontend` workspace property.

The profile deliberately has no active requirement for NuGet, `src/api`,
`src/frontend`, Azurite/blob-seed, Compose, or any legacy runtime image. The
validator rejects those paths even if a profile edit supplies a valid hash.
This makes deletion of those runtime trees independent from the active
supply-chain gate.

The v2 contributor manifest is intentionally separate from the pre-removal
`src/pipeline` development manifests. It retains the static build/data pipeline
dependencies and rejects `psycopg2-binary` and `azure-storage-blob`; exact
candidate execution remains governed by the retained release graphs and locks.

`contracts/supply-chain/v1` remains immutable Phase 1 historical evidence. Its
NuGet and legacy runtime records describe that reviewed candidate boundary;
they are not the current application dependency graph and must not be rewritten
to resemble the Phase 2 target.

Validate the active profile from the repository root:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  static-profile \
  --document contracts/supply-chain/v2/static-target-profile.json \
  --repository-root .
```

Validation is fail-closed over the exact sorted component set, required path
set, safe regular-file ancestry, SHA-256 bindings, static npm SBOM, and four
target-specific Python SBOMs. It makes no production, vulnerability, licence
completeness, publication, signing, or scientific approval claim.

When an active dependency, workflow, recipe, lock, graph, receipt, schema, or
SBOM changes, review that change and update its profile hash in the same pull
request. Adding a new active input requires an explicit validator contract
change; removing a required retained input fails closed.
