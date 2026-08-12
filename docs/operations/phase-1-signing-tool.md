# Phase 1 signing tool

The protected signing workflow is constrained to Cosign `v3.0.6` for
Linux AMD64 by
`contracts/supply-chain/v1/tools/cosign-linux-amd64.json`. The lock binds the
official `cosign-linux-amd64` release asset by SHA-256 and byte size and binds
the exact `cosign_checksums.txt` release asset that contains that digest. Both
URLs are versioned Sigstore project GitHub release URLs; no mirror or locally
invented checksum is authoritative.

Validate the reviewed lock from the repository root using its independently
reviewed file digest:

```shell
PYTHONPATH=src/pipeline python scripts/release/validate_supply_chain_contract.py \
  cosign-tool-lock \
  --lock contracts/supply-chain/v1/tools/cosign-linux-amd64.json \
  --trusted-lock-sha256 dbc14b1ecc49d3fbbfb907504e50c2c18d398e1c5aa55df1f1002d709c7b70e9
```

After separately downloading the two official assets, add `--executable` and
`--checksums`. Validation then requires the exact lock bytes, checksum-file
bytes, one exact checksum entry, executable bytes, sizes, and hashes. It rejects
symlinks and partial asset validation.

The controlled regional and full-Europe builder emits `real-source`
candidates. The manual protected workflow generates deterministic provenance,
downloads and validates these exact tool bytes independently in its signing
and verification jobs, and retains explicit false production, publication,
scientific-approval, environment-verification, and public-readback claims.
Repository-owner configuration of `phase-1-production-signing` remains a
separate prerequisite to any real workflow execution; committed workflow code
cannot prove that environment policy was configured or approved.

This lock and its build-plane SBOM entry do not claim signing, production,
publication, scientific approval, checksum-source authenticity beyond the
reviewed official release asset identity, or a completed release.
