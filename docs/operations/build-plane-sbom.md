# Candidate build-plane observable-component SBOM

`contracts/supply-chain/v1/sboms/build-plane.cdx.json` is the canonical
CycloneDX 1.7 file-input authority and observable inventory for reviewed candidate
build-plane files that are not npm, Python, or NuGet package locks. It binds
four GitHub Actions workflows, five native geospatial toolchain locks, recipes,
and receipts, and the controlled release container recipe. Those ten files yield
29 Action, native binary/package, DuckDB/Spatial, and OCI components.
Action `v*` comments are non-authoritative; recipes and the lock have fixed digests.

OpenTofu is recorded only as `not-present`, matching the reviewed dependency
inventory. No provider or package is invented for an absent ecosystem.

Validate the checked-in artifact from the repository root:

```shell
PYTHONPATH=src/pipeline python scripts/release/validate_build_plane_sbom.py \
  validate \
  --repository-root . \
  --sbom contracts/supply-chain/v1/sboms/build-plane.cdx.json
```

Generate new immutable bytes at a separate review path whose parent already
exists:

```shell
PYTHONPATH=src/pipeline python scripts/release/validate_build_plane_sbom.py \
  generate \
  --repository-root . \
  --output artifacts/sbom/build-plane.cdx.json
```

Generation and validation reject inventory drift, changed input bytes, unsafe
or symlinked paths, noncanonical JSON, mutable/local Actions, changed reviewed
recipes/locks, incomplete platforms, inconsistent receipts, and an existing
output. Components bind authority path/SHA-256, version, platform, digest, and
deterministic dependency edges.

This inventory does not attach anything to a candidate and does not claim
package, license, or vulnerability completeness,
signing, release approval, or production readiness. Native package digest
completeness is false.
