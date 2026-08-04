# Observability and Operations

> **Status:** Accepted target operating model
> **Authority:** [ADR-021](adr/ADR-021-static-first-offline-geospatial-architecture.md)

## Operating principle

SeaRise Europe operates a versioned data product and static application, not a
request-processing service. There are no application-server logs, database
health checks, background queues, or tile-server dashboards. Operational
evidence must answer four questions:

1. Was this release built from the declared sources and code?
2. Are its artifacts intact and deliverable through byte-range HTTP?
3. Can representative browsers search and assess correctly and quickly?
4. Can the previous application/release pair be restored safely?

Observability is release-centric, synthetic, and privacy-minimizing.

## Evidence layers

| Layer | Evidence | Retention/use |
|---|---|---|
| Build | Source hashes, tool versions, parameters, test summaries, CI logs | Attached to release/provenance and CI retention |
| Artifact | Manifest/STAC schemas, sizes, SHA-256, PMTiles/COG verification, licences | Immutable with each release |
| Delivery | Public `HEAD`/range probes, cache/CORS/security headers, aggregate R2/CDN metrics | Continuous checks and release report |
| Browser | Synthetic search/assessment/offline flows, Web Vitals, console/network errors | Versioned run results; no user query collection |
| Portfolio | Current release, commit, performance budgets, cost assumptions, provenance links | `/about/architecture` |

The release manifest is the inventory source of truth. A dashboard or log entry
must reference `dataReleaseId` and application commit so evidence from different
versions cannot be combined accidentally.

## Service indicators and targets

The baseline targets are release gates rather than a claim of contractual SLA:

| Indicator | Target | Measurement |
|---|---:|---|
| Site reachability | >= 99.9% monthly observation success | Multi-region HTTPS synthetic probe |
| Manifest reachability and validity | >= 99.9% monthly observation success | Fetch, schema, release-ID check |
| Large-object range delivery | >= 99.9% monthly observation success | `HEAD` and representative partial `GET` |
| Search p95 after worker initialization | < 50 ms | Production browser profile in CI/synthetic run |
| Local assessment p95 after data is cached | < 100 ms | Production browser profile |
| Search worker initialization | < 1,000 ms on reference mobile hardware | Release benchmark |
| Initial JavaScript, Brotli | <= 250 KiB, excluding lazy chunks | Bundle report |
| Lighthouse performance/accessibility/best-practices/SEO | >= 90 each | Agreed mobile profile |
| Runtime application API calls | 0 | Browser network assertion |
| Valid scenario/horizon combinations | exactly 9 | Manifest and artifact validation |

The deployment pipeline fails on a budget regression unless the pull request
contains a measured waiver with rationale, owner, and expiry date. Waivers are
not silently carried into the next release.

## Release-time monitoring

Every candidate release produces a machine-readable and human-readable report
containing:

- code revision, `dataReleaseId`, source snapshot hashes, and build environment;
- scientific golden-point and release-to-release diff results;
- schema, STAC, GeoParquet, PMTiles, COG, licence, and checksum results;
- application bundle sizes and browser performance results;
- search corpus counts, duplicates, exclusions, index bytes, and ranking tests;
- storage bytes and estimated range-request/transfer cost;
- SLSA-compatible provenance and Cosign verification result;
- the prior verified application/release rollback pair.

Publication stops if any required result is missing. “CI passed” without this
versioned evidence is insufficient for a scientific data release.

## Production synthetics

Run lightweight probes from at least two European regions after deployment and
on a schedule:

1. Fetch the HTML shell and verify the expected commit/release marker.
2. Fetch `manifest.json`, validate its schema, and verify exactly nine layers.
3. `HEAD` a search index, PMTiles archive, and analysis COG; verify content
   length, ETag, media type, cache headers, and range support.
4. Request representative beginning, middle, and ending byte ranges and verify
   `206 Partial Content` plus `Content-Range`.
5. Run a browser flow: local search, select, assess, switch scenario/horizon,
   share URL, and reload.
6. Assert that no request targets `/assess`, `/geocode`, `/config`, a database,
   or a tile server.
7. Warm the core cache, disable the network, and repeat the explicitly supported
   offline flow.
8. Verify that an uncached layer fails honestly rather than returning a guessed
   result.

OpenFreeMap is probed separately. Its failure is a degraded basemap state, not
an assessment outage.

## Platform metrics

Use Cloudflare's aggregate platform metrics for:

- static-site and R2 request volume, response status, latency, and cache ratio;
- R2 stored bytes, Class A/Class B operations, and public transfer;
- errors by application or data origin;
- usage relative to dated free-tier and budget assumptions;
- suspicious request-rate or range-request patterns.

Alerts should trigger on sustained synthetic failure, unexpected 4xx/5xx
changes, missing range support, rapid storage/operation growth, and projected
budget breach. Traffic spikes alone are context, not proof of an incident.

## Browser errors and privacy

The baseline does not require real-user analytics or client error reporting.
CI browser runs and synthetics provide the first line of evidence.

If client reporting is added later, it must be privacy-reviewed and scrub:

- search text and settlement selection;
- latitude/longitude and map bounds;
- full URLs, fragments, and query parameters;
- local-storage, IndexedDB, and cache contents;
- stable user/device identifiers.

Prefer aggregate Web Vitals and coarse browser/version counts. Sampling,
retention, processor, purpose, and user opt-out must be documented. A telemetry
provider may not become required for search or assessment.

## Runbooks

### Site or manifest unavailable

1. Confirm the failure from multiple regions and separate DNS, static origin,
   and data origin.
2. Check the last deployment and provider status.
3. If a deploy caused the issue, redeploy the previous known-good application.
4. Verify the prior manifest and browser flow before resolving the alert.

### Range requests or CORS fail

1. Reproduce with public `HEAD` and partial `GET` requests.
2. Compare OpenTofu plan/state and current bucket/domain rules.
3. Restore the last reviewed CORS/cache configuration.
4. Re-run PMTiles/COG range probes and a real browser assessment.

### Scientific or data-quality defect

1. Stop further publication and identify affected release IDs from manifests.
2. Redeploy the previous application/release pair.
3. Keep the defective immutable release for investigation unless security or
   legal requirements require removal.
4. Correct the pipeline, rerun the full validation set, and publish a new
   release ID; never repair released objects in place.
5. Publish a concise impact note if users could have seen incorrect results.

### Unexpected cost growth

1. Compare storage growth, request count, range size, and cache ratio to the
   release cost model.
2. Check automated abuse and accidental whole-object downloads.
3. Improve caching/range locality or temporarily constrain abusive traffic at
   the edge without changing scientific behaviour.
4. Create an ADR before adding paid always-on compute or proprietary data
   services.

### Compromised publication path

1. Revoke the credential and freeze production publication.
2. Audit DNS, bucket configuration, static deployments, and object inventory.
3. Verify manifests, signatures, and hashes from a trusted checkout.
4. Restore a verified pair and rotate least-privilege credentials.
5. Record affected releases and remediation in the incident report.

## Rollback readiness

At all times the release inventory identifies:

- current and previous application commit;
- corresponding `dataReleaseId` values;
- deployable static build or reproducible build reference;
- public manifest/provenance URLs;
- last successful smoke-test time.

Rollback means redeploying an immutable pair, not editing data. Test the
procedure before decommissioning the old architecture and periodically after
hosting/IaC changes.

## Ownership and review cadence

The project owner owns release approval, incident severity, and cost decisions.
Automation owns deterministic gates but cannot waive them. Review:

- on every release: all scientific, contract, delivery, performance, and cost
  evidence;
- weekly while actively developing: failing synthetics and usage anomalies;
- monthly in production: dependency alerts, provider cost assumptions, access
  credentials, and rollback freshness;
- on every source or methodology change: licence, attribution, golden points,
  and scientific review.

The observability system is successful when it provides enough evidence to
publish or roll back confidently without creating a new runtime platform to
observe.
