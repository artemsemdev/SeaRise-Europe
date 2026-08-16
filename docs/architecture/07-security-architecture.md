# Security, Privacy, and Supply-Chain Architecture

> **Status:** Accepted target architecture
> **Authority:** [ADR-021](adr/ADR-021-static-first-offline-geospatial-architecture.md)
> **Scope:** Browser application, immutable data releases, offline build plane,
> and Cloudflare delivery

## Security objective

SeaRise Europe is a public, anonymous, read-only application. The target
runtime has no application API, account system, server-side session, database,
or tile server. Its main security objective is therefore not API authorization;
it is to ensure that users receive the intended application and scientifically
validated data release without exposing their searches or coordinates.

The production trust boundary is:

```text
reviewed source + pinned tools
  -> isolated release build
  -> validated and signed immutable artifacts
  -> protected publication workflow
  -> HTTPS static/object origins
  -> browser schema and release checks
```

Removing services reduces attack surface, but it does not remove browser,
dependency, artifact-integrity, hosting-account, or build-pipeline risks.

## Assets and threat model

| Asset | Principal threats | Required protection |
|---|---|---|
| Scientific release | Corruption, source substitution, wrong parameters, mixed versions | Source/artifact SHA-256, schema checks, golden tests, immutable paths, signed provenance |
| Browser bundle | Cross-site scripting, dependency compromise, malicious third-party code | Restrictive CSP, lockfile, dependency review, no unnecessary third-party scripts |
| Publishing account | Credential theft, unauthorized overwrite or deletion | Protected environment, least-privilege credential, MFA, append-only release policy |
| User intent and location | Collection through logs, analytics, error reports, or URL leakage | No project-controlled request logging, no raw query/coordinate telemetry, careful URL/referrer policy |
| Cost availability | Automated range-request abuse or unexpectedly large downloads | CDN caching, object metrics, spend alerts, bounded browser caching |
| Offline cache | Stale or cross-release data mixture | Cache namespace by application and `dataReleaseId`, atomic activation, integrity metadata |

The basemap is not authoritative for assessment. Compromise or outage of the
OpenFreeMap public instance may degrade visual context but must not alter the
assessment state.

## Browser controls

The application must meet these controls:

- Put no API keys, publish credentials, private bucket URLs, or secrets in the
  JavaScript bundle, source maps, manifests, or repository.
- Encode untrusted place names as text. Never inject GeoNames fields, query
  parameters, STAC metadata, or upstream attribution as raw HTML.
- Validate every loaded manifest and configuration object against its versioned
  schema before use. Reject unsupported schema versions and a release ID that
  differs from the application-pinned ID.
- Treat artifact URLs as data from an allowlisted origin and media type. Do not
  follow arbitrary URLs supplied by search records or URL parameters.
- Keep all assessment logic local. Normal operation makes zero calls to
  `/assess`, `/geocode`, or `/config`.
- Use Web Workers only from the application origin; do not execute code from a
  data artifact.
- Keep visible MapLibre/OpenFreeMap/OpenMapTiles/OpenStreetMap attribution.
- Disable embedding unless a later product requirement explicitly permits it.

Both checked-in static entry documents enforce this policy before any
application script runs:

```http
Content-Security-Policy: default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'
Referrer-Policy: no-referrer
```

The `blob:` worker allowance is required by MapLibre. The inline-style
allowance is required by MapLibre's DOM controls; inline scripts remain
forbidden. AJV compiles the release schema into a checked-in standalone
validator at build time, so browser validation does not require `unsafe-eval`.
The only cross-origin runtime access is the exact OpenFreeMap tile origin, for
optional visual context. The current committed fixture and release artifacts
are same-origin. A future separate canonical data origin requires a reviewed
CSP and CORS change before use.

The production response headers should enforce the same policy and add the
controls that a meta policy cannot provide:

```http
Content-Security-Policy: default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'; frame-ancestors 'none'; upgrade-insecure-requests
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
Cross-Origin-Opener-Policy: same-origin
```

`frame-ancestors` must remain a deployment response-header requirement because
browsers do not enforce it from a meta CSP. The exact OpenFreeMap origin is
taken from the pinned style and tested before deployment. If cross-origin
isolation is later enabled, verify that all map and data origins provide
compatible resource policies first. The `'unsafe-inline'` style exception is
accepted only while required by MapLibre; CI records and tests any CSP
relaxation.

## Object delivery and CORS

R2 is served through a custom HTTPS domain. Bucket access and CORS are narrow:

- public users have `GET` and `HEAD` access only;
- `Access-Control-Allow-Origin` names the production and approved preview
  origins, not `*`, unless an explicit open-data distribution decision changes
  that rule;
- allow the `Range` and `If-Match` request headers;
- expose `Accept-Ranges`, `Content-Length`, `Content-Range`, and `ETag`;
- do not expose bucket administration endpoints or R2 credentials;
- apply `nosniff` and correct media types to every object.

Artifacts are release-versioned and never overwritten. A mutable release
pointer has a short TTL and is not the scientific identity used in a session;
the application pins one immutable `dataReleaseId`.

## Build and publication security

Only reviewed CI publishes production releases. A release job must:

1. Fetch sources from recorded authoritative URLs and verify expected size and
   SHA-256 before processing.
2. Use pinned action revisions, dependency lockfiles, tool/container versions,
   and a clean checkout.
3. Run contract, scientific, licence, malware/dependency, and artifact checks.
4. Generate SLSA-compatible provenance that records sources, code revision,
   tool versions, parameters, and subjects.
5. Create a keyless Cosign/Sigstore signature for the manifest/provenance
   bundle and retain the transparency-log evidence.
6. Upload through a credential limited to the intended bucket/prefix. The job
   cannot change DNS, account ownership, or unrelated releases.
7. Verify the published checksums and byte-range responses before activating
   the application/release pair.

Source and generated-data caches are untrusted build inputs. They are ignored
by Git, checked before use, and never published merely because a file is present
locally. Pull requests do not receive production publish credentials.

Dependency controls include automated update PRs, dependency review, secret
scanning, licence checks, and vulnerability scanning for npm, Python, native
geospatial tools, GitHub Actions, and OpenTofu providers. A critical finding in
a reachable runtime dependency blocks release; documented exceptions have an
owner and expiry date.

## Privacy policy

Searches and selected coordinates stay in the browser. SeaRise Europe does not
send them to a project-controlled backend because no such backend exists.

If analytics or client error reporting is introduced later, it must receive a
separate privacy review and satisfy all of these constraints:

- opt-in or aggregate-only collection;
- no search text, coordinates, full page URLs, IP-derived precise location,
  local cache contents, or stable cross-site identifier;
- URL query/fragment scrubbing before events and errors leave the browser;
- documented retention, processor, purpose, and deletion policy;
- a user-visible way to disable optional collection.

Cloudflare and the basemap provider still process ordinary network metadata.
The privacy notice must distinguish provider access logs from application
analytics and link to the current providers' policies.

## Runtime integrity and offline caches

The browser verifies schema version, `dataReleaseId`, expected scenario/horizon
coverage, and artifact metadata before assessment. HTTPS plus the pinned release
is the normal runtime trust boundary; full signature and checksum verification
runs in CI and is exposed as evidence on `/about/architecture`.

Service-worker caches are versioned. Activation must either expose a complete
new shell/manifest pair or retain the previous pair. Data ranges from two
releases must never share a cache namespace. On a mismatch, malformed response,
or missing uncached range, the UI returns an honest availability state and does
not infer a scientific result.

## Incident response and recovery

| Event | Response |
|---|---|
| Bad application deploy | Redeploy the last known-good static build pinned to its release |
| Bad scientific release | Remove it from mutable discovery, deploy the previous app/release pair, retain artifacts for investigation unless legally unsafe |
| Compromised publish credential | Revoke it, freeze publication, audit object/DNS changes, reissue least-privilege credentials |
| Dependency or provenance compromise | Block releases, identify affected releases from manifests, publish a signed advisory and replacement |
| Unexpected privacy telemetry | Disable collection, preserve minimal audit evidence, follow the documented deletion/notification process |
| Cost/traffic abuse | Enable stricter caching/rate controls at the edge without adding business logic, then review request evidence in aggregate |

Immutable releases make rollback recoverable and auditable. Deleting a
published release is an exceptional incident action, not the normal rollback
mechanism.

## Verification gates

CI and production smoke tests must prove:

- no secrets in built assets and no unexpected external origins;
- the CSP and security headers are present and compatible with supported flows;
- runtime network assertions show no application API calls;
- manifests and STAC are schema-valid and all artifact hashes/sizes match;
- provenance and Cosign verification succeed;
- R2 CORS permits only intended browser access and byte ranges work;
- offline activation never mixes releases;
- dependency, secret, licence, and infrastructure scans pass;
- a rollback drill can restore the previous application/release pair.

## Deferred decisions

Authentication, user-generated content, exact-address geocoding, application
APIs, and detailed client telemetry are outside the baseline. Each would add a
new trust boundary and requires its own ADR before implementation.
