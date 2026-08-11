# Settlement Spatial build plane

Settlement geometry transformations use DuckDB `1.5.4` and its `spatial`
extension only through the separately pinned Python 3.11 build plane. This is
not the historic AR6 release environment: do not change either
`requirements-release*.lock` or its evidence when updating this toolchain.

The authoritative identities are in
`src/pipeline/toolchain/duckdb-spatial-extensions.json`. It binds a Python
wheel, the compressed official extension archive, and the uncompressed native
extension for both Linux x86_64 and macOS arm64. The corresponding hash-only
wheel locks are:

- `requirements-settlements-spatial-linux-x86_64.lock`
- `requirements-settlements-spatial-macos-arm64.lock`

## Acquisition and cache preflight

Acquire the manifest's official `extensionArchive.url` outside the repository
while network access is permitted. Do not put the archive or expanded extension
under source control. Install the matching wheel from a reviewed wheelhouse,
then admit and verify the archive before the isolated build starts:

```bash
python -m searise_pipeline.settlements.spatial_toolchain \
  --manifest src/pipeline/toolchain/duckdb-spatial-extensions.json \
  --cache-root /run/cache/settlement-spatial \
  --platform linux-x86_64 \
  --archive /staging/spatial.duckdb_extension.gz
```

The preflight checks the gzip size and SHA-256 before copying it into the cache,
then checks the expanded extension's size and SHA-256 before atomic placement.
A pre-existing cache entry is rechecked; a mismatch or link fails the run.

## Network-isolated runtime

After the network is disabled, run the same command without `--archive`:

```bash
python -m searise_pipeline.settlements.spatial_toolchain \
  --manifest src/pipeline/toolchain/duckdb-spatial-extensions.json \
  --cache-root /run/cache/settlement-spatial \
  --platform linux-x86_64
```

It proves the installed DuckDB version, both cached file identities, loads the
verified extension by its absolute cache path, and requires the deterministic
point/distance smoke result `(12.5, 41.9, 5.0)`. The runtime never asks DuckDB
to fetch or install an extension; a missing cache is a hard failure, not a
fallback to the network.

The standard Linux CI job exercises acquisition and the live load with the
Linux lock. Run the macOS command on a Python 3.11 arm64 runner before admitting
a macOS build-plane change.
