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
  --expected-origin https://artemsemdev.github.io \
  --manifest-url https://artemsemdev.github.io/SeaRise-Europe/releases/v0.1.0/manifest.json \
  --provenance-url https://artemsemdev.github.io/SeaRise-Europe/releases/v0.1.0/provenance.intoto.jsonl \
  --receipt /run/audit/public-readback.json
```

Both URLs must use the exact repository-reviewed public origin, default port,
ASCII unescaped path, and no credentials, query, or fragment. Adding or changing
an origin requires a reviewed code change. DNS must resolve entirely to global
addresses; the hook connects to a pinned resolved address and rejects peer drift.
Responses must be direct `200` identity-encoded bodies and complete within the
30-second per-subject deadline. The local and remote subjects are limited to 8
MiB each. The receipt path must have an existing symlink-free parent and must not
already exist. Keep that parent outside the candidate, evidence, and repository
roots; the hook rejects descriptor ancestry overlap and any existing alias before
rerunning cryptographic verification.

On success the command writes one canonical JSON line to standard output with
the candidate, data release, controlled run, receipt path, receipt SHA-256, and
subject count. A closed output stream cannot reverse an already durable receipt;
the receipt bytes remain the authoritative success record.

The canonical receipt proves that the public bytes matched subjects whose
Cosign bundles were reverified for the pinned repository workflow and issuer by
the recorded readback-completion instant. It does not prove future availability or immutability and
does not grant production, publication, or scientific approval. Retain it with
the immutable candidate, cryptographic-verification receipt, bundles, and
rollback release. A failure blocks promotion; continue serving the previous
verified release.
