# SeaRise Europe — Metrics and Evidence Plan

> **Owner:** Artem Sem
>
> **Status:** Active target plan
>
> **Version:** 1.0
>
> **Last updated:** 2026-08-04
>
> **Decision source:** [ADR-021](../architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)

## 1. Measurement principles

SeaRise Europe is a public portfolio application, not an engagement-optimized
SaaS product. The baseline therefore measures quality through CI, synthetic
checks, controlled QA, and usability sessions. User analytics are optional and
must earn their privacy cost.

Measurement must:

1. prove that the product is scientifically and technically trustworthy;
2. detect a broken release before or shortly after publication;
3. verify that the static-first architecture improves the user journey;
4. support portfolio claims with reproducible evidence;
5. avoid collecting raw search queries, place names, coordinates, or
   identifiable browsing histories.

No metric may turn `OutOfScope`, `UnsupportedGeography`, or
`DataUnavailable` into a generic product failure. They are distinct outcomes
whose distribution is useful for improving coverage and explanation.

## 2. Evidence tiers

| Tier | Purpose | Primary source |
|---|---|---|
| Release gates | Prevent invalid artifacts or regressions | CI, schemas, scientific tests, browser tests |
| Operational health | Confirm static site and immutable artifacts are deliverable | Privacy-neutral synthetic checks and aggregate host metrics |
| Product quality | Confirm users can find and interpret a place | Controlled QA and usability research |
| Portfolio evidence | Make architecture outcomes inspectable | Generated architecture page and release manifest |

## 3. Release-gate metrics

These metrics are blocking. Results are stored with the release or CI run and
summarized on `/about/architecture`.

| Metric | Target | Measurement |
|---|---:|---|
| Initial application JavaScript | <= 250 KiB Brotli | Build artifact report; map/search chunks excluded |
| Lighthouse scores | >= 90 in performance, accessibility, best practices, and SEO | Agreed mobile profile against production-like preview |
| Search response after worker initialization | p95 < 50 ms | Deterministic multilingual query fixture |
| Search worker initialization | < 1,000 ms | Reference mobile hardware/profile |
| Local assessment after required data is cached | p95 < 100 ms | Golden coordinate/scenario/horizon fixture |
| Runtime application API calls | 0 | Browser network assertions for `/assess`, `/geocode`, `/config` |
| Scenario/horizon completeness | Exactly 9 valid combinations | Manifest/schema validation |
| Scientific regression | 100% approved golden points pass | Pipeline and browser parity tests |
| Large-artifact delivery | 100% pass `HEAD` and partial `GET` | Preview and production smoke tests |
| Integrity and licence mapping | 100% | SHA-256, byte size, source metadata, and attribution checks |
| Offline core | 100% of defined warm-cache cases pass | Service-worker/network-removal suite |
| Accessibility | No critical/serious automated findings and all manual core-flow checks pass | Automated scan plus keyboard/screen-reader checklist |

A temporary waiver records the measured regression, rationale, owner, and
expiry. It does not waive scientific integrity, licence, or five-state
correctness.

## 4. Search quality

The search benchmark is generated from the pinned settlement release and a
reviewed fixture set. It covers:

- canonical, ASCII, localized, and alternate names;
- diacritics and common transliterations;
- duplicate names disambiguated by country and first-level administration;
- small coastal villages and zero-population records allowed by the catalog
  rule;
- inland core places that must resolve and then return `OutOfScope`;
- transcontinental and support-boundary cases;
- empty, malformed, and no-match queries.

| Metric | Initial target |
|---|---:|
| Top-1 accuracy for unambiguous approved queries | >= 95% |
| Intended result within top 5 for ambiguous approved queries | >= 95% |
| Qualifying source records accounted for after normalization | 100% |
| Duplicate normalized IDs | 0 |
| Invalid coordinates or orphan alternate names | 0 |

These are release-quality measures, not claims that GeoNames contains every
settlement in reality.

## 5. Product and comprehension metrics

### 5.1 First-use completion

**Definition:** participant finds a provided test settlement, selects it, and
reaches a completed state without facilitator help.

**Target:** at least 90% across a minimum of five representative participants.
Record time on task and confusion points; do not collect personal location
queries.

### 5.2 Five-state comprehension

**Definition:** participant explains what each state means and, crucially, what
it does not mean.

**Target:** at least 80% correctly distinguish:

- `ModeledExposureDetected` from a flood prediction;
- `NoModeledExposureDetected` from a safety guarantee;
- `DataUnavailable` from a zero result;
- `OutOfScope` from unsupported geography;
- `UnsupportedGeography` from a technical error.

### 5.3 Scenario and horizon comprehension

Participants should identify the active SSP pathway and year and understand
that they represent a scenario/horizon combination, not provider-specific
forecasts. Target: at least 80% without facilitator explanation.

### 5.4 Transparency completion

In the QA matrix, 100% of result states must expose the active scenario,
horizon, methodology version, data release, source attribution, limitations,
and required disclaimer.

### 5.5 Offline comprehension

In a network-toggle test, users should distinguish “available offline” from
“not yet cached.” The target is zero observed cases where the UI implies that
missing network data is a no-exposure result.

## 6. Operational health

There is no application server or request log in the target runtime.
Operational checks cover:

- root HTML and versioned application assets;
- the pinned release manifest and search indexes;
- `HEAD`, byte-range `GET`, CORS, ETag, and immutable cache headers for large
  artifacts;
- all nine analysis/visual artifact pairs;
- certificate and custom-domain health;
- aggregate object storage, request volume, errors, and cost;
- OpenFreeMap availability as a separate, non-authoritative dependency.

Suggested initial objectives:

| Measure | Objective |
|---|---:|
| Synthetic site/manifest success | >= 99.5% monthly |
| Artifact range-check success | 100% per release; >= 99.5% scheduled |
| Unexpected application error in scripted journey | 0 per release |
| Storage and request forecast | Reviewed before every publication |
| Budget alert | Configured before paid usage is possible |

An unavailable basemap does not count as assessment downtime when the local
search and textual assessment still function.

## 7. Portfolio evidence

The architecture page should answer these questions from generated evidence:

| Question | Evidence |
|---|---|
| Is the normal path backend-free? | Browser network assertion and dependency diagram |
| Is the data traceable? | Manifest, STAC links, checksums, licences, Git revision |
| Is the release verifiable? | SLSA-compatible provenance and Cosign bundle |
| Is it fast? | Bundle, Lighthouse, search, and assessment measurements |
| Is “offline” honest? | Cache inventory and warm/uncached test results |
| Is it inexpensive? | Dated storage/request/traffic model and current aggregate usage |
| Is it portable? | Open formats and host capability contract |
| Is it scientifically ready? | Gate status, golden-point summary, and explicit synthetic/real-data label |

Portfolio-review target: in three short technical walkthroughs, reviewers can
identify the product value, scientific limits, static-first decision, and
verification evidence within three minutes.

## 8. Optional analytics

Product analytics are disabled by default. They may be enabled only after a
documented privacy review and a clear decision that aggregate behaviour is not
adequately answered by usability studies and synthetic tests.

If enabled, the minimal allowed event families are:

- `search_completed` with coarse outcome only (`selected`, `no_match`,
  `cancelled`);
- `assessment_completed` with domain state, scenario ID, horizon, release ID,
  and coarse latency bucket;
- `control_changed` with scenario/horizon field and release ID;
- `methodology_opened` with result-state context;
- `offline_status_seen` with `available` or `missing_data`;
- `client_error` with scrubbed error category and application version.

The following are prohibited in events, error reports, referrers, or session
replay:

- raw query text, aliases, or selected place label;
- latitude, longitude, geohash, bounding box, or map center;
- full shareable URL or query string;
- IP-derived fine location, advertising identifiers, or cross-site identity;
- free-form text and DOM/session recording.

If analytics are used, prefer aggregate-only or opt-in collection, document
retention and deletion, honor applicable consent requirements, and verify the
production payload in browser tests.

## 9. Review cadence

| Cadence | Review |
|---|---|
| Every pull request | Relevant unit, contract, browser, accessibility, and bundle checks |
| Every data release | Scientific, search, integrity, licence, provenance, cost, and artifact delivery gates |
| Weekly after launch | Synthetic failures, static host/object errors, cost and storage anomalies |
| After material copy or flow change | Five-state comprehension and accessibility review |
| Quarterly while actively maintained | Dependency, source licence, cost assumption, browser support, and portfolio evidence review |

Metrics that are not actively collected must be labelled “not measured,” not
estimated from anecdote.
