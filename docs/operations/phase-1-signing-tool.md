# Phase 1 signing-tool prerequisite

The future protected signing workflow is constrained to Cosign `v3.0.6` for
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

No signing workflow is added by this prerequisite. The controlled regional and
full-Europe builder emits `real-source` candidates, and the integrated strict
pre-sign provenance contract validates them while retaining explicit false
verification, production, publication, scientific-approval, signing, and
environment claims. The separately reviewed real-source unverified envelope
binds exact pre-verification bytes without treating its Sigstore bundles as
trusted. Only the production evidence finalizer and protected workflow remain
to be reviewed before a workflow may request OIDC, sign, or invoke
cryptographic verification. The protected environment will authorize that
future workflow but cannot itself be proven by a signing certificate receipt.

This lock and its build-plane SBOM entry do not claim signing, production,
publication, scientific approval, checksum-source authenticity beyond the
reviewed official release asset identity, or a completed release.
