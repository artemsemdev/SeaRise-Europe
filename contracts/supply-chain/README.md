# Supply-chain contracts

`v1` defines the immutable evidence boundary for a Phase 1 release candidate.
It does not alter `contracts/release/v1`, and incompatible changes require a new
versioned directory.

## Evidence boundary

The envelope preserves the candidate-completeness role identifiers exactly:

- `provenance` for an in-toto Statement v1 with the SLSA provenance v1
  predicate;
- `signature` for Sigstore bundle v0.3 sidecars;
- `software-bill-of-materials` for CycloneDX 1.7 JSON documents.

`candidateManifest` and `provenance` are the two signed subjects. Each must have
exactly one signature descriptor with the same subject path and SHA-256. At
least one SBOM is mandatory. Candidate manifest, provenance, signature, and
SBOM artifact paths must be globally unique.

Signature bundles are sidecars. They are not inserted into the bytes they sign,
which avoids a self-referential hash. The evidence envelope is a verification
index over the subjects and sidecars; this contract slice does not create or
cryptographically verify a bundle.

## Production identity policy

`v1/identity-policy.json` pins the only acceptable production identity:

- repository: `artemsemdev/SeaRise-Europe`;
- workflow: `.github/workflows/phase-1-release-sign.yml`;
- ref: `refs/heads/master`;
- certificate identity:
  `https://github.com/artemsemdev/SeaRise-Europe/.github/workflows/phase-1-release-sign.yml@refs/heads/master`;
- OIDC issuer: `https://token.actions.githubusercontent.com`;
- protected environment: `phase-1-production-signing`.

The envelope binds the exact policy-file bytes by SHA-256. The validator rejects
any production claim because cryptographic verification belongs to a later
workflow slice. The committed valid fixture is therefore explicitly
`synthetic-unverified`, `fixtureOnly`, and not a production claim.

## CycloneDX validation

`v1/vendor/` contains the official CycloneDX 1.7 JSON Schema and its three local
references as served by `cyclonedx.org` on 2026-08-11. `vendor/manifest.json`
pins every source URL and file SHA-256. The validator checks those hashes first,
blocks remote schema retrieval, and then validates the complete SBOM with the
official Draft 7 schema. The vendored schemas are Apache-2.0 licensed.

## Dependency-defining input inventory

`v1/dependency-inventory.json` binds the exact bytes of all 43 inputs discovered
at this reviewed revision. The inventory validation command below derives and
reports the current validated count, avoiding a separate operational count.
Coverage includes npm,
Python release and contributor environments, all five NuGet projects and
locks, GitHub workflows, container recipes and manifests, the native
geospatial toolchain, and the vendored CycloneDX 1.7 schema bundle with its
SPDX reference schema. The OpenTofu component is explicitly `not-present`;
adding OpenTofu or Terraform configuration without a provider lock fails
validation.

Discovery is exact, sorted, and duplicate-free. Each recorded input must be a
safe repository-relative regular file, may not traverse a symlink, and is
bound to its SHA-256. New dependency manifests, locks, container recipes,
workflows, or local `.github/actions/**/action.yml` definitions fail closed
until they are deliberately classified and inventoried. Generated dependency
trees, build outputs, and tool caches are excluded from discovery.

This is an inventory of dependency-defining inputs, not a package graph or
SBOM. It does not claim transitive-package completeness, vulnerability status,
artifact signing, cryptographic verification, or production readiness.

## Dependency exceptions

An exception must identify its finding, exact component, owner, affected scope,
rationale, approval time, and expiry. Semantic validation requires
`approvedAt < expiresAt` and an explicit timezone-aware validation instant. A
not-yet-effective or expired exception fails closed.

The checked-in exception fixtures are synthetic test records. They are not
active project exceptions.

## Local validation

From the repository root:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py evidence \
  --envelope contracts/supply-chain/v1/fixtures/valid/evidence-envelope.json \
  --identity-policy contracts/supply-chain/v1/identity-policy.json \
  --sbom sbom/frontend.cdx.json=contracts/supply-chain/v1/fixtures/valid/frontend.cdx.json

PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py exception \
  --document contracts/supply-chain/v1/fixtures/valid/dependency-exception.json \
  --as-of 2026-08-11T12:00:00Z

PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py inventory \
  --document contracts/supply-chain/v1/dependency-inventory.json \
  --repository-root .
```

These commands validate contract structure and deterministic bindings only.
They do not prove that a production signing event occurred.
