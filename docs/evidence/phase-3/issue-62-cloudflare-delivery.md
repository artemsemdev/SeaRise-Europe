# Issue #62 Cloudflare delivery repository evidence

> **Observed:** 2026-08-25T18:02:39+02:00
> **Scope:** credential-free future-state validation only
> **Production claim:** false

The Issue #62 future tree validates with OpenTofu `1.12.6` and Cloudflare
provider `5.23.0`. A synthetic fixture plan produced exactly seven creates,
zero changes, and zero destroys: R2 bucket, CORS, incomplete-multipart
lifecycle, custom domain, two zone rulesets, and Workers Static Assets. The
redacted JSON plan scanner passed its secret-like-value, resource allowlist,
destructive-action, and publication-authority checks.

Eight provider-neutral HTTP/repository cases passed. A versioned synthetic
PMTiles object and a versioned synthetic COG object each proved `GET`, `HEAD`,
`206`, `416`, exact allowed/denied CORS, conditional/range request headers,
strong SHA-256 ETags, exact media types, and `Cache-Control: public,
max-age=31536000, immutable`. The explicitly unversioned `/release.json`
fixture separately proved `no-store`. No Candidate-v7 or TAR bytes were read.

The complete supply-chain directory passed 643 tests after adding an exact
OpenTofu component and both immutable workflow inputs. Repository-removal
regression passed 105 tests and the full harness passed 79 tests. Actionlint
passed; Trivy's embedded checks reported zero HIGH/CRITICAL findings after its
optional remote checks-bundle refresh was unavailable locally.

Warnings are retained honestly: the fixture invokes the deployable root as a
child module, so OpenTofu reports that its backend block is ignored in that
credential-free harness; the real protected workflow initializes the root with
the environment backend. Provider `5.23.0` also warns that the R2 lifecycle
resource cannot be destroyed through OpenTofu, reinforcing the documented
inventory and rollback boundary rather than authorizing a manual deletion.

No Cloudflare or GitHub resource, DNS record, domain, state bucket, environment,
secret, credential, object, or public release was created, changed, deleted, or
uploaded. Live apply, second-plan idempotence, readback, cost, recovery, and
rollback evidence remain external blockers owned by #74/#64 as documented in
the [operations guide](../../delivery/cloudflare-static-delivery.md).
