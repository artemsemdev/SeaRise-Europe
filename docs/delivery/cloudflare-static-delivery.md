# Cloudflare static delivery operations

> **Status:** repository implementation; external activation blocked
> **Scope:** Issue #62 infrastructure only
> **Authority:** [ADR-021](../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md) and Issue #62 public-delivery acceptance

## Delivered topology

`infra/cloudflare` is a portable OpenTofu root for three isolated environments:
`fixture`, `staging`, and `production`. Each environment has a distinct release
bucket, custom data domain, static Worker name, protected credential scope,
state bucket, and state key. OpenTofu `1.12.6` and the Cloudflare provider
`5.23.0` are exact pins; `.terraform.lock.hcl` contains checksums for CI and
developer platforms.

The root manages only the delivery plane:

- a Standard R2 release bucket in Western Europe with deletion protection;
- exact-origin `GET`/`HEAD` CORS and range/conditional request headers;
- abort of incomplete multipart uploads after seven days, with no object
  expiry rule;
- an R2 custom domain, cache rules, response/security headers, and strong ETag
  handling;
- Workers Static Assets with no Worker business-logic route.

It deliberately contains no D1, KV, Durable Objects, Queues, R2 object upload,
application API, or data-publication resource. Issue #62 infrastructure
authority is not Issue #64 publication authority.

## Cache and HTTP contract

Every release URL is canonical and versioned under
`/releases/{dataReleaseId}/...`. Versioned COG fixtures prove `GET`, `HEAD`,
`206`, `416`, exact CORS, a strong ETag, the Cloud-Optimized GeoTIFF media type,
and `Cache-Control: public, max-age=31536000, immutable`.

Versioned PMTiles fixtures prove the same `public, max-age=31536000,
immutable` response contract as versioned COGs. Application code may still
decline to persist visual PMTiles, but that client-side retention choice does
not weaken the public origin contract. `no-store` is reserved for the explicit
unversioned mutable discovery alias `/release.json`; it is tested separately
and is never treated as a canonical release object.

The checked-in synthetic fixture contains no Candidate-v7 or TAR bytes. Run:

```bash
python -m unittest tests.infra.test_cloudflare_delivery -v
python scripts/infra/verify_http_delivery.py \
  --base-url https://data-staging.example.invalid \
  --pmtiles-path /releases/REVIEWED_ID/layers/ssp2-45/2050.pmtiles \
  --cog-path /releases/REVIEWED_ID/analysis/ssp2-45/2050.tif \
  --origin https://app-staging.example.invalid \
  --denied-origin https://denied.example.invalid \
  --mutable-alias-path /release.json
```

The second command is live evidence only after exact reviewed URLs exist. It
must never be pointed at private candidate paths.

## Plan, approval, and apply

Pull requests run `.github/workflows/static-delivery-plan.yml` without cloud
credentials. It verifies the repository contract, formatting, provider lock,
fixture plan, plan secret/destruction scanner, HTTP contract, and IaC security
scan. Only the redacted create/change summary is retained.

`.github/workflows/static-delivery-apply.yml` is manual and fails closed unless
all of the following hold:

1. the requested revision is the exact checked-out 40-character `master` SHA;
2. the first job passes its `cloudflare-{environment}-plan` protection;
3. both the Issue #62 infrastructure switch and the independently owned Issue
   #64 static-publication switch are enabled;
4. the assets directory is a repository-contained, tracked, symlink-free tree
   with no Candidate-v7 or TAR path/name;
5. an environment-scoped plan token and state credentials are present;
6. the plan has no delete action, unapproved resource, or secret-like value;
7. exact plan and non-secret environment-configuration digests cross into a
   separately protected
   `cloudflare-{environment}-apply` job;
8. a distinct apply token applies only that plan, then a second plan exits 0.

The backend example fixes the environment-specific state bucket/key, locking,
and encryption flags. The R2 S3 endpoint is derived at runtime from that
environment's protected `CLOUDFLARE_ACCOUNT_ID`; it is not a portable literal
or repository secret. State credentials are separate from Cloudflare plan and
apply tokens.

Each environment uses three non-reusable credential scopes: plan, apply, and
state. The plan token is read-only for the exact account/zone resources; the
apply token may edit only the modeled R2, zone-ruleset, and static-Worker
resources; the S3-compatible state identity is limited to that environment's
private state bucket/key and lock object. #74 must record the exact Cloudflare
permission names and verify denial outside those boundaries before activation.

Issue #64 owns the independent static-publication switch and reviewed app
bytes; Issue #62 cannot enable or substitute it. Issue #74 owns creation of protected environments/reviewers, repository
rulesets, OIDC migration, state-backend bootstrap, existing-resource imports,
drift detection, and the provider-gap exception register. Until those controls
exist, the apply workflow is implemented but not activation evidence.

## Recovery and rollback

Before a first apply, #74 must inventory existing resources and record either
supported imports or an approved provider-gap disposition. Back up encrypted
state and verify restore into an isolated recovery key. Never delete a state
object, release bucket, custom domain, or Worker to test rollback.

For infrastructure rollback, check out the last reviewed configuration, create
a new plan against the same protected state, reject all unreviewed deletes,
and apply only after the normal separate approval. For application/data
rollback, Issue #64 switches the reviewed application/release pointer to an
already verified previous pair; release prefixes remain append-only. A
documented command is not proof: activation requires retained plan/apply
receipts, a zero-change second plan, live HTTP evidence, and a demonstrated
previous-pair recovery.

## Cost and provider gaps

The dated model in `delivery-contract.json` uses Cloudflare's 2026-08-07 R2
Standard pricing: USD 0.015/GB-month storage, USD 4.50/million Class A, USD
0.36/million Class B, and zero internet egress charge. The monthly free
allowance is 10 GB-month, one million Class A, and ten million Class B
operations. The idle target is therefore zero within allowances, excluding
domain registration, but it is not a guarantee. Activation must measure
stored bytes and operation counts, assign a cost owner, and set thresholds.
The checked-in reference scenario (1 GB-month, 0.5 million Class A, 5 million
Class B) estimates USD 0/month within those allowances. A mandatory-review
guardrail of 100 GB-month, 5 million Class A, and 50 million Class B estimates
USD 33.75/month: `(100-10)*0.015 + (5-1)*4.50 + (50-10)*0.36`.

Provider `5.23.0` cannot import R2 custom-domain, CORS, or lifecycle resources,
and exposes no managed R2 spend-budget notification in this root. These are
explicit #74 gaps, not silently completed acceptance criteria.

Current references:

- [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [R2 with Terraform/OpenTofu](https://developers.cloudflare.com/r2/examples/terraform/)
- [R2 CORS](https://developers.cloudflare.com/r2/buckets/cors/)
- [R2 custom domains](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [Workers infrastructure as code](https://developers.cloudflare.com/workers/platform/infrastructure-as-code/)
- [Workers Static Assets provider support](https://developers.cloudflare.com/changelog/post/2025-10-09-assets-terraform/)

## External activation blockers

No Cloudflare account, zone, domain, R2 state bucket, protected environment,
credential, or public data source is bound by this repository state. No live
plan/apply, DNS/resource mutation, object upload, Candidate-v7/TAR inspection,
publication, idempotence, cost, recovery, or live HTTP claim has been made.
Those blockers must be closed by their owning issues with new explicit
authority; repository CI success alone cannot close them.
