# Risks, Assumptions, and Open Questions

> **Status:** Current migration register
> **Authority:** [ADR-021](adr/ADR-021-static-first-offline-geospatial-architecture.md), amended by [ADR-024](adr/ADR-024-ar6-regional-projection-contract.md)
> **Review rule:** Update evidence and disposition; do not silently convert an
> assumption into a fact.
>
> **Phase 0.2 evidence:** [source semantics, datum, DEM, and geometry QA](../science/phase-0-2-source-and-geography-evidence.md)
>
> **Phase 0.5 evidence:** [selected vertical methodology](../science/phase-0-5-vertical-methodology-evidence.md)
>
> **Phase 0.6 evidence:** [locked vertical inputs](../science/phase-0-6-vertical-source-evidence.md)
>
> **Phase 0.7 evidence:** [fail-closed vertical reconciliation implementation](../science/phase-0-7-vertical-reconciliation-evidence.md)
>
> **Phase 0.8 evidence:** [terrain, geography, and connectivity controls](../science/phase-0-8-terrain-geography-controls.md)
>
> **Phase 0.9 decision:** [regional scientific gate](../evidence/phase-0-9-regional-gate.md) — `BLOCKED`
>
> **Phase 0.14 decision:** [terminal no-go](../evidence/phase-0-14-final-no-go.md) — investigation `COMPLETE-WITH-NO-GO`; authoritative disposition `BLOCKED`
>
> **Recovery decision:** [ADR-024](adr/ADR-024-ar6-regional-projection-contract.md) — projection contract and #135 source/lookup parity accepted; release remains blocked on #110

## Current risk register

| ID | Risk | Likelihood / impact | Mitigation and exit evidence |
|---|---|---|---|
| R-01 | The exact IPCC AR6 archive member differs from the documented binding schema | Low / Critical | The full `20210809` archive and three exact scenario members have byte, CRC/MD5 where available, SHA-256, and NetCDF inspection evidence. #135 now verifies archive and member hashes before opening NetCDF and reproduced every golden with an independent reader. Re-run this permanent gate for each release. |
| R-02 | The binary elevation comparison creates disconnected inland false positives or misrepresents coastal pathways | Inapplicable to ADR-024 / Historical Critical | ADR-024 performs no terrain or connectivity classification. Preserve the v1 controls as historical evidence; any future hazard layer requires a new ADR and validation. |
| R-03 | Source or derivative redistribution terms are incomplete | Medium / Critical | Licence review for each source and derivative; manifest attribution; block publication until all rights and required wording are documented. |
| R-04 | Browser exact lookup disagrees with the source-bound build values because of coordinate, location-ID, unit, quantile, or nodata differences | Low / Critical | #135 passed offline parity for seven real regional points, 189 q0.167/q0.5/q0.833 values, two scope controls, and synthetic nodata/distance/tie controls. Python and TypeScript agree bit-exactly on integer millimetres and source identity; metre output uses the fixed 1e-6 tolerance. Keep this as a permanent release regression gate. |
| R-05 | Search indexes are too large or slow on mobile | Medium / High | Core/coastal shards, Brotli, lazy Web Worker load, representative mobile benchmarks, size/count report, deterministic ranking tests. |
| R-06 | GeoNames misses, duplicates, or misclassifies settlements implied by “all coastal cities and villages” | High / High | Publish the operational definition, snapshot/date, feature-code rules, exclusions, corpus counts, duplicate/transcontinental QA, and limitations. |
| R-07 | The 25 km coastal product zone is mistaken for flood reach | Medium / High | The deterministic v2 recipe, 27 named-place controls, topology invariant, and prior comparison evidence are recorded. Keep product-scope language explicit: this scope filter is not modeled flood reach. |
| R-08 | PMTiles plus analysis COGs exceed free storage or cause excessive R2 range operations | Medium / Medium | Regional size/request spike, range-locality measurement, cache tuning, release cost model, usage alerts; consolidate only after exact-lookup proof. |
| R-09 | Service Worker mixes application and data releases | Medium / High | Namespace caches by app version and `dataReleaseId`; atomic activation; offline/mid-update tests; fail closed on mismatch. |
| R-10 | OpenFreeMap changes or is unavailable | Medium / Low | Treat it as non-authoritative visual context; graceful no-basemap mode; preserve a documented self-host/alternate-style path. |
| R-11 | Cloudflare pricing, limits, or custom-domain behaviour changes | Medium / Medium | Date the cost model, alert on usage, avoid proprietary runtime services, and retain a static host + byte-range object storage portability test. |
| R-12 | Build dependency, source, action, or publication credential is compromised | Medium / Critical | Pin dependencies/actions, verify checksums, scan dependencies/secrets, generate SLSA provenance, Cosign-sign manifests, protect production and use least privilege. |
| R-13 | Static architecture is presented as complete before real-data validation | Medium / Critical | #135 supplies real-source lookup evidence, but production claims, Phase 1, and decommissioning remain blocked until the owner approves a zero-blocker #110 release gate with measured artifacts. |
| R-14 | Documentation and implementation diverge during staged migration | High / Medium | Mark target vs current state, link to ADR-021, enforce architecture fitness tests, and remove old service docs only as their target contracts are documented. |
| R-15 | Relative AR6 change is compared directly with absolute terrain height | Inapplicable to ADR-024 / Historical Critical | ADR-024 prohibits terrain comparison and reports relative change directly. Tests must continue to reject any reintroduction of the legacy operation. |
| R-16 | A geoid or vertical transform mixes model realization, ellipsoid, permanent-tide convention, epoch, or interpolation semantics | Inapplicable to ADR-024 / Historical Critical | The active path performs no geoid or vertical transform. Phase 0.10 remains immutable evidence for the superseded v1 path. |
| R-17 | A DSM, HEM, MAE, or product accuracy target is treated as bare-earth terrain or a complete per-cell upper bound | Inapplicable to ADR-024 / Historical Critical | The active path consumes no terrain. Phase 0.11 remains immutable evidence and terrain cannot return without a new ADR. |
| R-18 | Green CI or source-integrity checks are mistaken for release approval | Medium / Critical | The projection contract separates `automatedValidation` from owner-controlled `releaseDisposition`. The ADR snapshot calls this authority `releaseDecision`; release artifacts use `releaseDisposition`. Only the project owner may approve a zero-blocker #110 gate and unlock #48. |
| R-19 | An offshore mean-sea-surface grid, land filler, or ordinary tide-gauge record is treated as a datum-safe shoreline water reference | Inapplicable to ADR-024 / Historical Critical | ADR-024 does not construct an absolute water reference and prohibits tide-gauge fallback. Retain the v1 finding as historical evidence. |
| R-20 | A global coastal DTM or multi-source mosaic is assumed to have finite European per-cell uncertainty from MAE/RMSE alone | Inapplicable to ADR-024 / Historical Critical | ADR-024 consumes no DTM or terrain uncertainty. Retain the v1 finding as historical evidence. |

### Historical v1 risk disposition

The following paragraph records why the binary v1 path stopped. Its terrain,
datum, connectivity, and independent-review blockers are retired from the
active product by ADR-024; the underlying evidence remains immutable.

The [Phase 0.3 regional gate evidence](../evidence/phase-0-regional-fixture.md)
recorded the then-current blocked disposition for R-01, R-02, R-04, R-07,
R-08, and R-13. It proved a small real COG and lookup/range mechanics, but did
not close datum compatibility, scientific controls, connectivity, canonical
coastal scope, PMTiles, public hosting, or human review.
Phase 0.5 selects the vertical strategy but closes none of these measured or
human-review risks by documentation alone. Phase 0.6 closed the exact-input
identity gap for R-01 and R-15 but does not lower the transformation or
publication consequence. Phase 0.7 removes the direct-comparison implementation
path and made every remaining vertical blocker machine-readable; it did not
lower R-16 because numerical controls and independent review did not pass.
Phase 0.8 selects terrain, product-scope, and connectivity candidates and adds
executable controls. It reduced implementation ambiguity but did not close
R-02, R-07, or R-17 under that historical method.
Phase 0.9 attempted the exact nine-layer matrix and stopped before arrays. Its
explicit blocked decision prevents R-13 and R-18 from being hidden by a green
build, but R-02, R-04, R-07, R-08, R-16, and R-17 remain open because the
required numerical, artifact, control, reproducibility, and review evidence
does not exist. The corrected Phase 0.9 evidence is immutable. Issues #94–#97
recorded the follow-up evidence as blocked, and #98 performed the terminal v1
re-evaluation without rewriting it.
Phase 0.11 quantifies the finite source terms but confirms that coastal SLA
representativeness and DSM-to-bare-earth error are not finitely bounded by the
locked evidence. The automated recommendation is therefore `rejected`, not
`approved`; independent review was never obtained, so the authoritative
disposition and publication gate ended `blocked` and required a superseding
method.
Phase 0.14 remains the immutable binary-path no-go. ADR-024 completes #106's
contract decision without reinterpreting that evidence. #135 has now passed
offline source/implementation parity and lowers R-01 and R-04 to permanent
regression risks. Recovery proceeds through #110; only its measured artifacts
and an explicit project-owner release disposition may unlock #48.

## Assumptions that require evidence

| ID | Assumption | Required validation |
|---|---|---|
| A-01 | A static browser path can preserve all four projection domain states | Golden tests across Europe support, inland coast scope, source nodata, and projection-available locations |
| A-02 | Nine Europe-wide visual PMTiles and exact lookup artifacts are practical to publish and query | Regional spike extrapolation plus full-build size, range-count, memory, and latency measurements |
| A-03 | GeoNames CC BY 4.0 data and selected alternate names can be redistributed in derived indexes | Recorded licence review and complete attribution in manifest/product |
| A-04 | Cloudflare Workers Static Assets + R2 can remain at or near EUR 0/month for portfolio traffic | Current provider allowance/pricing snapshot and measured release/traffic model |
| A-05 | R2 custom-domain delivery returns correct `HEAD`, `206`, CORS, ETag, and immutable cache behaviour | Staging probes from public origins and representative browsers |
| A-06 | React 19 + Vite 8 meets the static shell, accessibility, and bundle budget | Production build, Lighthouse profile, network assertions, and browser compatibility matrix |
| A-07 | A core-first local index gives useful results before the complete coastal shard loads | Search relevance tests and reference-mobile worker/load measurement |
| A-08 | Cached core behaviour is useful without promising all nine layers offline | User-visible cache state, warm-cache browser tests, and honest uncached-layer failure |

## Decisions deliberately open

These are not blockers to documenting the target architecture, but they must
be resolved by the named evidence before their implementation is fixed:

| Question | Decision evidence | Resolution mechanism |
|---|---|---|
| What is the final Europe support polygon and how are transcontinental states treated? | The v2 candidate uses an explicit 50-feature allow-list, fixed clip/tolerance, 27 controls, and `covers`; Russia/Turkey and named territories have explicit outcomes | Product-owner approval; ADR if domain outcomes change |
| MiniSearch or another compact open-source search engine? | Index bytes, initialization, p95 query latency, multilingual relevance, licence | Implementation design note and pinned tests |
| Can exact PMTiles lookup replace companion COGs? | Bit-exact parity over golden and edge cases plus range/size improvement | New ADR before COG removal |
| Should users be able to download a regional offline pack? | Storage quota behaviour, UX, privacy, failure/recovery, artifact size | Product decision after browser spike |
| Should optional analytics or error reporting exist? | Concrete learning need, privacy review, provider/retention/opt-out | Separate privacy decision before integration |
| Which registrar/custom domain is used? | Annual price, DNSSEC, account recovery, Cloudflare integration | Operational choice recorded with cost model |

Exact street-address search, accounts, uploads, personalized saved places, and
server-side analytics are out of scope. They are not “open implementation
questions”; each would change privacy, cost, and runtime boundaries and needs a
new ADR.

## Migration stop conditions

Do not remove the old runtime implementation or present the static path as the
validated production product until all of these are true:

- real IPCC, GeoNames, and Natural Earth source snapshots pass licence and
  source-shape review for the release that consumes them;
- the AR6 release passes the trusted dual-platform source, artifact, browser,
  and owner-disposition controls defined by #110;
- Python and TypeScript exact lookup are bit-exact for approved fixtures;
- browser, artifact, offline, performance, and accessibility gates pass;
- staging proves public byte-range/CORS/cache behaviour;
- old/new path differences are explained and approved;
- rollback to a known application/release pair has been tested;
- current cost and source limitations are visible on `/about/architecture`.

The scientific stop condition already fired for binary exposure; ADR-024 is its
superseding decision. Keep Phase 1 paused through #110. Passing CI records
automated validation only; the project owner must separately approve the
zero-blocker `releaseDisposition` before #48 unlocks.

## Risk review cadence

- Update this register at each migration phase and data release.
- Link material evidence from release reports rather than marking a risk
  “closed” by assertion.
- Escalate a new Critical risk into an ADR or explicit stop condition.
- Move resolved implementation facts into the owning technical document and
  remove the corresponding assumption from the next reviewed version.
