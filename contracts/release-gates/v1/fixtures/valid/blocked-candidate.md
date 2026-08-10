# Release gate report

- Candidate: `candidate-fixture-20260810-0123456789ab`
- Data release: `searise-europe-v1.0.0-20260810-0123456789ab`
- Provenance: `synthetic-fixture`
- Authority: `automation`
- Automated validation: `fail`
- Owner disposition: `not-recorded`
- Releasable: `no`
- Generated: `2026-08-10T20:00:00Z`

## Checks

| Check | Status | Target | Measured | Non-waivable | Evidence |
|---|---|---:|---:|---|---|
| Artifact integrity mismatches | `pass` | = 0 count | 0 count | yes | `evidence/artifact-integrity.json` (`sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`) |
| Reproducibility parity ratio | `not-measured` | = 1 ratio | not measured | yes | `evidence/reproducibility.json` (`sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`) |
| Artifacts missing rights records | `fail` | = 0 count | 1 count | yes | `evidence/rights.json` (`sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc`) |

## Stop reasons

- `required-measurement-missing`
- `rights-incomplete`
