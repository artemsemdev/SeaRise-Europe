# Candidate build-plane input SBOM foundation

`contracts/supply-chain/v1/sboms/build-plane.cdx.json` is the canonical
CycloneDX 1.7 file-input authority foundation for reviewed candidate
build-plane files that are not npm, Python, or NuGet package locks. It binds
four GitHub Actions workflows, five native geospatial toolchain locks, recipes,
and receipts, the controlled release container recipe, and the reviewed Cosign
Linux AMD64 tool lock. It expands those files into 30 Action, native,
DuckDB/Spatial, signing, and OCI components; Action `v*` comments are
non-authoritative.

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
or symlinked paths, noncanonical JSON, and an existing output. Each file
component binds its exact repository-relative path, role, inventory component,
and reviewed SHA-256. Mutable/local Actions, changed reviewed recipes/locks,
incomplete platforms, and inconsistent receipts also fail closed.

This scoped foundation does not attach anything to a candidate and does not
claim component or package completeness, license or vulnerability completeness,
signing, release approval, or production readiness. Native package digest
completeness is explicitly false.
