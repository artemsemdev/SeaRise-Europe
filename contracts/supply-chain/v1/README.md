# Supply-chain contracts

These contracts validate candidate evidence and generate deterministic software
inventory from supported immutable dependency inputs. They do not sign a
candidate, scan vulnerabilities, prove license completeness, or make a
production-release claim.

## npm SBOM generation

Generate a canonical CycloneDX 1.7 document from the frontend npm lock:

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

The generator currently supports package-lock v3 registry packages only. It
rejects links, workspaces, invalid names or aliases, non-registry tarballs,
invalid integrity hashes, unresolved required edges, unreachable package
entries, symlink inputs, and non-regular lock paths. The document binds the
exact input SHA-256, each lock-entry SHA-256, npm SHA-512 integrity, root
dependency groups, and path-qualified dependency relationships.
