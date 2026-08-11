# Candidate build-plane observable-component SBOM

`contracts/supply-chain/v1/sboms/build-plane.cdx.json` is the canonical
CycloneDX 1.7 inventory generated only from reviewed candidate build-plane
authority bytes that are not npm, Python, or NuGet package locks. It retains
the ten exact file components for four GitHub Actions workflows, five native
geospatial toolchain locks, recipes, and receipts, and the controlled release
container recipe. It also expands those bytes into 29 deterministic,
platform-qualified observable components:

- nine unique external GitHub Actions at their full commit revisions;
- Tippecanoe and tippecanoe-decode 2.79.0 binary digests for Linux x86-64 and
  macOS arm64;
- DuckDB 1.5.4 wheels plus Spatial v1.5.4 compressed and unpacked extension
  artifacts for both platforms, including exact URLs, paths, sizes, and hashes;
- the Ubuntu and Python OCI bases at their manifest digests; and
- eight exact Linux build/runtime package versions recorded by the native
  receipt and cross-checked against the build recipe where applicable.

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
or symlinked paths, noncanonical JSON, mutable Action or OCI references,
incomplete platform locks, inconsistent receipts and recipes, and an existing
output. Each observable component binds canonical authority path/SHA-256 pairs,
an exact version and platform, and its artifact digest or authority-observation
digest. Dependency edges retain which workflow, lock, receipt, or recipe
observed each component and the exact native runtime and Spatial archive
relationships.

This observable inventory does not attach anything to a candidate and does not
claim package completeness, license or vulnerability completeness, signing,
release approval, or production readiness. The native receipt records exact
Debian package versions but no package-level content digests, so the root
explicitly records native-package digest completeness as false.
