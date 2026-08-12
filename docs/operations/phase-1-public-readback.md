# Phase 1 public signed-subject readback

Run the readback hook only after the candidate manifest, provenance, and
Sigstore evidence have been uploaded to their final immutable HTTPS paths. The
command reruns identity-bound Cosign verification locally, then fetches the two
public subjects without redirects or content encoding and requires exact byte
equality with the freshly verified local subjects.

```shell
PYTHONPATH=src/pipeline python scripts/release/verify_public_signed_subjects.py \
  --candidate-root /run/candidate \
  --evidence-root /run/evidence \
  --repository-root . \
  --controlled-build-run-id 123456789 \
  --cosign-executable /run/tools/cosign \
  --cosign-tool-lock contracts/supply-chain/v1/tools/cosign-linux-amd64.json \
  --trusted-cosign-tool-lock-sha256 dbc14b1ecc49d3fbbfb907504e50c2c18d398e1c5aa55df1f1002d709c7b70e9 \
  --expected-origin https://downloads.example.org \
  --manifest-url https://downloads.example.org/releases/v0.1.0/manifest.json \
  --provenance-url https://downloads.example.org/releases/v0.1.0/provenance.intoto.jsonl \
  --receipt /run/audit/public-readback.json
```

Both URLs must use the same reviewed canonical public DNS HTTPS origin, default
port, ASCII unescaped path, and no credentials, query, or fragment. Responses must be
direct `200` identity-encoded bodies. The local and remote subjects are limited
to 8 MiB each. The receipt path must have an existing symlink-free parent and
must not already exist.

The canonical receipt proves that the public bytes matched subjects whose
Cosign bundles were reverified for the pinned repository workflow and issuer at
the recorded instant. It does not prove future availability or immutability and
does not grant production, publication, or scientific approval. Retain it with
the immutable candidate, cryptographic-verification receipt, bundles, and
rollback release. A failure blocks promotion; continue serving the previous
verified release.
