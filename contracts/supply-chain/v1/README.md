# Supply-chain contracts

These contracts validate candidate evidence and generate deterministic software
inventory from supported immutable dependency inputs. They do not sign a
candidate, scan vulnerabilities, prove license completeness, or make a
production-release claim.

## npm SBOM generation

`sboms/frontend-npm.cdx.json` is the canonical CycloneDX 1.7 inventory generated
from the real frontend candidate lock. Regenerate it to a new review path with:

```shell
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  npm-sbom \
  --lock src/frontend/package-lock.json \
  --logical-path src/frontend/package-lock.json \
  --output artifacts/sbom/frontend.cdx.json
```

The output parent directory must already exist and must not be a symlink. The
command never replaces an existing path. It writes and synchronizes a unique
same-directory partial file, promotes it without overwrite, and removes the
partial file if publication fails.

Validate the checked-in public bytes against the exact repository lock:

```shell
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  npm-sbom-validate \
  --repository-root . \
  --lock src/frontend/package-lock.json \
  --logical-path src/frontend/package-lock.json \
  --sbom contracts/supply-chain/v1/sboms/frontend-npm.cdx.json
```

Validation rejects non-canonical JSON, schema or graph drift, a different lock
hash or logical path, and symlinked lock or SBOM ancestry. Replace a reviewed
artifact only through a new commit; the publication command itself never
overwrites an existing path.

The generator currently supports package-lock v3 registry packages only. It
rejects links, workspaces, invalid names or aliases, non-registry tarballs,
invalid integrity hashes, unresolved required edges, unreachable package
entries, symlink inputs, and non-regular lock paths. The document binds the
exact input SHA-256, each lock-entry SHA-256, npm SHA-512 integrity, root
dependency groups, and path-qualified dependency relationships.
The real artifact inventories the candidate build lock but does not claim
bundle inclusion, license or vulnerability completeness, signing, or release
approval.

## Python graph annotations

Hash-locked Python requirement files identify exact packages and wheel hashes,
but they do not identify logical roots or dependency edges. The versioned
Python lock graph annotation is the sole reviewed authority for that graph. Its
validator binds every declared target to exact lock bytes and an exact Python
3.11 marker environment, requires package parity and a complete acyclic graph,
and rejects implicit extras or target-dependent edges.

The synthetic fixture remains isolated under `fixtures/python-graph`. Two real,
non-production annotations under `python-graphs` bind the paired release locks
and paired settlement-spatial locks. Their package versions and active edges
were reviewed from exact hash-matched Linux and macOS wheel `METADATA`; every
selected-extra set is empty because neither locked environment installs an
optional dependency set.

Release roots are the candidate-runtime entries declared by the pipeline
manifest and used directly by release, scientific, geospatial, contract, or
command code: Click, Cryptography, GeoPandas, JSON Schema, netCDF4, NumPy,
Pandas, PyArrow, PyProj, Rasterio, rio-cogeo, Shapely, and Xarray. The exact
Python 3.11 locks also contain the `importlib-metadata` backport as an installed
distribution without an active incoming dependency. It therefore remains an
explicit reviewed inventory root so the complete lock is represented; this is
not a claim that code importing the standard-library `importlib.metadata` uses
the backport. DuckDB is the sole explicit root of the isolated
settlement-spatial environment documented in
`docs/operations/settlement-spatial-toolchain.md`.

The stored PEP 508 environments use fixed logical runner targets rather than
the validating host. Both paired targets must resolve to an identical active
graph. These annotations are dependency evidence, not an SBOM, production
artifact, vulnerability scan, license inventory, signing record, release
approval, or scientific approval.
