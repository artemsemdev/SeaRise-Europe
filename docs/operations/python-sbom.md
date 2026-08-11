# Python SBOM generation and validation

SeaRise emits one deterministic CycloneDX 1.7 SBOM for one explicit Python
target. The reviewed Python graph annotation is the authority for roots and
dependency edges; the target's hash-locked requirements file is the authority
for package versions and wheel SHA-256 values.

The checked-in `python-graph/valid.json` annotation and its locks are synthetic
contract fixtures. They exercise the boundary but are not production evidence.
The generated root component preserves `data-provenance-class` and the
`production-claim=false` boundary from the annotation review.

## Generate one target

Run from the repository root with the pipeline package on `PYTHONPATH`:

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  python-sbom \
  --repository-root . \
  --annotation contracts/supply-chain/v1/fixtures/python-graph/valid.json \
  --target linux-x86-64-cp311 \
  --output artifacts/sbom/python-linux-x86-64-cp311.cdx.json
```

The output parent must already exist and contain no symlinked path component.
The command never creates parent directories and never overwrites an existing
file, directory, or symlink. Use a distinct output path for every target.

Publication writes canonical bytes to a descriptor-relative unique partial,
fsyncs the file, promotes it without replacement, verifies inode ownership,
and fsyncs the stable parent directory. A failed publication removes only an
output that still has the inode created by that invocation; a racing
replacement is never deleted.

## Validate an existing SBOM

```bash
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  python-sbom-validate \
  --repository-root . \
  --annotation contracts/supply-chain/v1/fixtures/python-graph/valid.json \
  --target linux-x86-64-cp311 \
  --sbom artifacts/sbom/python-linux-x86-64-cp311.cdx.json
```

Validation reopens the annotation and exact target lock, reruns the graph
contract and vendored CycloneDX schema, regenerates the expected document, and
compares canonical bytes. It fails closed on target ambiguity, component or
edge drift, altered hashes or marker identity, non-canonical JSON, symlinks,
unsafe paths, and authority mutation.

To regenerate an artifact, publish to a new path, validate it, update its
owning manifest or evidence envelope, and only then retire the old artifact
through the release process. Do not delete an existing SBOM merely to make a
generation command succeed.
