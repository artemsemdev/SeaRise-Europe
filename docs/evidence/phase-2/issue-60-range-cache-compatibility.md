# Issue #60 range-cache compatibility decision

> **Status:** Accepted implementation input
>
> **Measured:** 2026-08-16
>
> **Scope:** Browser storage behavior on a production-like loopback server;
> public-origin delivery remains gated by issues #62 and #65.

## Question

Issue #60 needs bounded, release-scoped persistence for the byte ranges read by
the exact COG lookup and the visual-only PMTiles renderer. The spike asks
whether the Cache API can safely persist real HTTP `206` responses across the
supported engines, and whether a stored byte record can produce an exact
offline `206` without changing its release authority.

## Method

The dedicated server reads only the committed synthetic release. It exposes
the `ssp2-45`/`2050` analysis COG and visual PMTiles with production-like
`HEAD`/`GET`, single-range, immutable cache, content-type, ETag, and range
headers. Playwright 1.62.1 then runs the same assertions in Chromium, Firefox,
and WebKit:

1. Fetch actual bytes `65536-65599` and verify the origin `206` response.
2. Attempt to store and retrieve that actual `206` through Cache Storage.
3. Store the complete `200` response and match it with a request carrying the
   same URL plus `Range`.
4. Store the 64 bytes with their interval and artifact authority in IndexedDB,
   retrieve bytes `65544-65559`, and synthesize an exact `206` response.

The full machine-readable observation is
[`issue-60-range-cache-compatibility.json`](issue-60-range-cache-compatibility.json).

## Results

| Engine | Version | Artifacts | Direct `Cache.put(206)` | Range request against cached whole response | IndexedDB slice and exact `206` |
|---|---:|---|---|---|---|
| Chromium | 151.0.7922.34 | COG, PMTiles | Rejected with `TypeError` | Returned whole `200` | Passed |
| Firefox | 153.0 | COG, PMTiles | Rejected with `TypeError` | Returned whole `200` | Passed |
| WebKit | 26.5 | COG, PMTiles | Rejected with `TypeError` | Returned whole `200` | Passed |

All six engine/artifact cases received the exact 64 origin bytes with correct
`Accept-Ranges`, `Content-Length`, `Content-Range`, content type, and manifest
SHA-256 ETag. All six retrieved the exact 16-byte IndexedDB slice and produced
the required `206`, range, length, and ETag headers.

Cache Storage is unsafe as the range-byte persistence primitive for two
independent reasons demonstrated here: it rejected the real `206`, and its URL
matching did not use the request's `Range` header to protect a range request
from a cached complete response.

## Decision

The project owner accepted the measured storage behavior and refined its
implementation scope in
[ADR-026](../../architecture/adr/ADR-026-authoritative-browser-range-persistence.md).
This refinement does not alter any engine, response, byte, header, or
IndexedDB observation above. It distinguishes a demonstrated storage mechanism
from the release-supplied interval integrity authority required for production
admission.

- Use Cache Storage only for explicitly routed complete shell and small
  immutable release responses.
- Store only complete integrity-authorized COG chunks in bounded IndexedDB,
  with exact application build, `dataReleaseId`, artifact identity, full
  artifact authority, chunk interval/digest, byte count, and LRU metadata.
- Keep PMTiles network-only and visual-only with a `no-store` caching policy.
  PMTiles must not enter Cache Storage, IndexedDB, or the session-memory range
  store until a separately reviewed promotion contract supplies exact interval
  digests and the other ADR-026 gates.
- Admit bytes, update accounting, and perform eviction in one IndexedDB
  transaction boundary where practical.
- Return only an exact authorized COG chunk or one half-open slice contained by
  that single chunk. Adjacent records are not assembled. A partial hit is a
  miss, not a shortened response or scientific result.
- Never call `Cache.match()` with a range request and treat an arbitrary match
  as range-complete.

This decision selects a storage boundary; it does not implement the production
worker, caching policy, quotas, or UI.

## Scientific and privacy boundaries

The COG range store is transport infrastructure. The analytical COG remains the
only exact scientific input and continues through ADR-024 identity, chunk,
native-grid, quantile, nodata, and inclusive 100 km validation. PMTiles remains
visual-only and cannot become science. A missing range must become a technical
connection-required state, never a fifth outcome.

Technical cache, network, integrity, quota, transaction, and storage failures
remain separate from all four ADR-024 outcomes. The later production store
must not persist search text, coordinates, place
labels, selection history, profile-like records, or query-bearing URLs. This
spike contains no such inputs. Candidate-v7 and TAR files were not read,
copied, served, cached, or uploaded. Explicit Candidate-v7 testing remains
local, read-only, and session-only.

## Limitations

This measurement used macOS 26.5.2 arm64 and Playwright-managed engines on a
same-origin loopback server. Desktop device descriptors emulate browser user
agents; the engine versions in the table are the executed browser binaries.
It does not prove Linux, mobile hardware, browser-restart durability, quota,
eviction, concurrency, overlapping ranges, service-worker lifecycle, public
CDN/CORS/R2 behavior, or production-sized Candidate performance. Those remain
separate issue #60 and public-origin gates.

## Reproduce

From an installed clean clone:

```bash
npx playwright install chromium firefox webkit
npm run e2e:range-cache --workspace @searise/web
```

The command binds only `127.0.0.1:8092`, runs six cases, prints one exact JSON
observation per case, and removes its temporary Cache Storage and IndexedDB
records.
