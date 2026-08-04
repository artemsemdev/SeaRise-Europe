# Source acquisition operator guide

> **Issue:** [#45](https://github.com/artemsemdev/SeaRise-Europe/issues/45)
> **Boundary:** acquisition and integrity only; scientific interpretation starts in #46/#47.

The static-first pipeline acquires source bytes only through the reviewed lock
at `src/pipeline/sources/source-lock.json`. The legacy
`src/pipeline/download.py` remains comparison infrastructure and cannot feed a
publishable release.

## Commands

Run commands from `src/pipeline` after installing the project with its `dev`
extra:

```bash
python -m searise_pipeline.sources validate
python -m searise_pipeline.sources publication-check
python -m searise_pipeline.sources fetch --target natural-earth-10m:ocean
python -m searise_pipeline.sources verify --target natural-earth-10m:ocean
```

Without `--target`, `fetch` and `verify` process every source whose
`selectionStatus` is `selected`. Candidate sources must be named explicitly.
Acquisition still fails closed when their redistribution status is
`unknown`, `restricted`, or `review-required`.

The default cache is `data/raw/sources/<source>/<version>/`; receipts go to
`artifacts/acquisition-receipts/`. Both roots are ignored by Git, separate from
`data/output`, and must never be copied wholesale into a release. The release
builder introduced by #49 must use an allow-list of validated derivatives.

## Audited registry status

| Source | Selection | Version/snapshot | Rights status | Reviewer | Locked evidence |
|---|---|---|---|---|---|
| IPCC AR6 sea-level projections | Selected | `20210809` | Approved, CC BY 4.0 | SeaRise Europe maintainers, 2026-08-04 | `location_list.lst`, 2,659,137 bytes, SHA-256 `431bf1a6…58d88d` |
| GeoNames `cities15000` | Selected | `2026-08-04` | Approved, CC BY 4.0 | SeaRise Europe maintainers, 2026-08-04 | 3,304,425 bytes, SHA-256 `e61d9aeb…fa75c2` |
| Natural Earth 10m | Selected | `5.1.1` | Approved, public domain | SeaRise Europe maintainers, 2026-08-04 | Admin 0 and ocean ZIPs with exact sizes/SHA-256 |
| Copernicus DEM GLO-30 | Candidate | `2021_1` | Approved with mandatory notices | SeaRise Europe maintainers, 2026-08-04 | N52/E004 sample tile, 17,037,271 bytes, SHA-256 `edb30766…851f1` |
| Copernicus Coastal Zones 2018 | Candidate | `V1-2018` | Review required | Unassigned | Metadata only; authenticated asset identity and publication rights remain blocked |

The full URLs, unabridged hashes, licence links, attribution, and required
acknowledgements live in the lock. A selected source cannot pass
`publication-check` unless its redistribution status is `approved` and its
review metadata is present.

## Updating a pin

1. Start from the publisher's canonical record; do not copy a URL from an
   unofficial mirror without recording and reviewing the lineage.
2. Record the immutable version or snapshot date, final resolved HTTPS URL,
   HTTP media type, exact byte size, and SHA-256. Preserve an upstream checksum
   as secondary evidence when one exists.
3. Review the current licence, attribution, redistribution rights, and required
   acknowledgements. `review-required` is the safe default.
4. Update the lock in a focused PR. Never change a checksum merely to make a
   failed download pass.
5. Run the validation, publication check, focused tests, and a targeted fetch
   followed by an offline verify. Include the receipt and before/after metadata
   in the PR without committing raw bytes.

GeoNames uses a mutable daily URL. Once its bytes change, the old lock must fail
instead of silently accepting the new snapshot. Retain the verified raw cache
needed by an in-progress build and update the snapshot only through review.

## Cache cleanup

List the exact source/version directory first. Remove or move only that
resolved version directory; never delete `data/raw`, the repository root, or a
path derived from an unset variable. A later fetch recreates the directory only
after the new bytes pass all lock checks. Receipts may be archived as gate
evidence, but they contain no raw data.

## Upstream-change incident

Treat checksum, size, media type, redirect target, HTML/login response, and
unexpected 404 as incidents:

1. stop the acquisition and retain the rejection receipt;
2. verify the canonical publisher record and current access/licence terms;
3. determine whether bytes, packaging, authentication, or the release identity
   changed;
4. open a reviewed lock-update PR or roll back to the prior retained snapshot;
5. never retry a permanent/auth failure indefinitely and never weaken the
   expected checksum.

An HTTP 404 is considered an expected absent ocean tile only when the exact
asset entry declares `availability: expected-absent`; all other 404 responses
are permanent failures.

## Receipt safety

Each success and rejection writes JSON containing source/asset IDs, timestamp,
sanitized requested/final URLs, status, bytes, SHA-256, cache decision, attempt
count, reason, and tool version. URL userinfo, query strings, and fragments are
removed before writing. Tests scan generated receipts with credential-like
query values and fail if the secret appears.

Example:

```json
{
  "asset_id": "ocean",
  "attempts": 1,
  "byte_count": 3189765,
  "cache_decision": "miss",
  "reason": null,
  "requested_url": "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_ocean.zip",
  "resolved_url": "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_ocean.zip",
  "sha256": "db626fcd5d50b096b156c78a2cc95011b39f32a61b4e47d147e3f7a77b8b2719",
  "source_id": "natural-earth-10m",
  "status": "acquired",
  "timestamp": "2026-08-04T00:00:00+00:00",
  "tool_version": "0.1.0"
}
```
