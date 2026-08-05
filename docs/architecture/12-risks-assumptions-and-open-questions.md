# Risks, Assumptions, and Open Questions

> **Status:** Current migration register
> **Authority:** [ADR-021](adr/ADR-021-static-first-offline-geospatial-architecture.md)
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
> **Recovery decision:** [ADR-024](adr/ADR-024-ar6-regional-projection-contract.md) — projection contract accepted; implementation and release remain blocked on #135 and #110

## Current risk register

| ID | Risk | Likelihood / impact | Mitigation and exit evidence |
|---|---|---|---|
| R-01 | The exact IPCC AR6 archive member differs from the documented binding schema | Low / Critical | The full `20210809` archive and three exact scenario members now have byte, CRC/MD5 where available, SHA-256, and NetCDF inspection evidence. The contract fails closed on changed identity; #135 must reproduce the values with an independent reader. |
| R-02 | The binary elevation comparison creates disconnected inland false positives or misrepresents coastal pathways | Inapplicable to ADR-024 / Historical Critical | ADR-024 performs no terrain or connectivity classification. Preserve the v1 controls as historical evidence; any future hazard layer requires a new ADR and validation. |
| R-03 | Source or derivative redistribution terms are incomplete | Medium / Critical | Licence review for each source and derivative; manifest attribution; block publication until all rights and required wording are documented. |
| R-04 | Browser exact lookup disagrees with the source-bound build values because of coordinate, location-ID, unit, quantile, or nodata differences | Medium / Critical | #135 uses offline real-source goldens, two independent readers, a fixed grid-only operator, and Python/TypeScript parity for state, source identity, and q0.167/q0.5/q0.833 values. |
| R-05 | Search indexes are too large or slow on mobile | Medium / High | Core/coastal shards, Brotli, lazy Web Worker load, representative mobile benchmarks, size/count report, deterministic ranking tests. |
| R-06 | GeoNames misses, duplicates, or misclassifies settlements implied by “all coastal cities and villages” | High / High | Publish the operational definition, snapshot/date, feature-code rules, exclusions, corpus counts, duplicate/transcontinental QA, and limitations. |
| R-07 | The approximate 25 km coastal zone is mistaken for flood reach | Medium / High | The deterministic v2 recipe, 27 named-place controls, topology invariant, and Copernicus Coastal Zones comparison are recorded. Keep product-scope language explicit; product-owner approval and release wording remain blocking. |
| R-08 | PMTiles plus analysis COGs exceed free storage or cause excessive R2 range operations | Medium / Medium | Regional size/request spike, range-locality measurement, cache tuning, release cost model, usage alerts; consolidate only after exact-lookup proof. |
| R-09 | Service Worker mixes application and data releases | Medium / High | Namespace caches by app version and `dataReleaseId`; atomic activation; offline/mid-update tests; fail closed on mismatch. |
| R-10 | OpenFreeMap changes or is unavailable | Medium / Low | Treat it as non-authoritative visual context; graceful no-basemap mode; preserve a documented self-host/alternate-style path. |
| R-11 | Cloudflare pricing, limits, or custom-domain behaviour changes | Medium / Medium | Date the cost model, alert on usage, avoid proprietary runtime services, and retain a static host + byte-range object storage portability test. |
| R-12 | Build dependency, source, action, or publication credential is compromised | Medium / Critical | Pin dependencies/actions, verify checksums, scan dependencies/secrets, generate SLSA provenance, Cosign-sign manifests, protect production and use least privilege. |
| R-13 | Static architecture is presented as complete before real-data validation | Medium / Critical | Clearly label synthetic fixtures; block production claims, Phase 1, and decommissioning until #135 evidence passes and the owner approves a zero-blocker #110 release gate. |
| R-14 | Documentation and implementation diverge during staged migration | High / Medium | Mark target vs current state, link to ADR-021, enforce architecture fitness tests, and remove old service docs only as their target contracts are documented. |
| R-15 | Relative AR6 change is compared directly with absolute terrain height | Inapplicable to ADR-024 / Historical Critical | ADR-024 prohibits terrain comparison and reports relative change directly. Tests must continue to reject any reintroduction of the legacy operation. |
| R-16 | A geoid or vertical transform mixes model realization, ellipsoid, permanent-tide convention, epoch, or interpolation semantics | Inapplicable to ADR-024 / Historical Critical | The active path performs no geoid or vertical transform. Phase 0.10 remains immutable evidence for the superseded v1 path. |
| R-17 | A DSM, HEM, MAE, or product accuracy target is treated as bare-earth terrain or a complete per-cell upper bound | Inapplicable to ADR-024 / Historical Critical | The active path consumes no terrain. Phase 0.11 remains immutable evidence and terrain cannot return without a new ADR. |
| R-18 | Green CI or source-integrity checks are mistaken for scientific or release approval | Medium / Critical | The projection contract separates `automatedValidation` from the owner-controlled `releaseDecision`. Only the project owner may approve a zero-blocker #110 gate and unlock #48. |
| R-19 | An offshore mean-sea-surface grid, land filler, or ordinary tide-gauge record is treated as a datum-safe shoreline water reference | Inapplicable to ADR-024 / Historical Critical | ADR-024 does not construct an absolute water reference and prohibits tide-gauge fallback. Retain the v1 finding as historical evidence. |
| R-20 | A global coastal DTM or multi-source mosaic is assumed to have finite European per-cell uncertainty from MAE/RMSE alone | Inapplicable to ADR-024 / Historical Critical | ADR-024 consumes no DTM or terrain uncertainty. Retain the v1 finding as historical evidence. |

The [Phase 0.3 regional gate evidence](../evidence/phase-0-regional-fixture.md)
records the current blocked disposition for R-01, R-02, R-04, R-07, R-08,
and R-13. It proves a small real COG and lookup/range mechanics, but closes none
of those risks: datum compatibility, scientific controls, connectivity,
canonical coastal scope, PMTiles, public hosting, and human review remain open.
Phase 0.5 selects the vertical strategy but closes none of these measured or
human-review risks by documentation alone. Phase 0.6 closes the exact-input
identity gap for R-01 and R-15 but does not lower the transformation or
publication consequence. Phase 0.7 removes the direct-comparison implementation
path and makes every remaining vertical blocker machine-readable; it does not
lower R-16 until numerical controls and independent review pass.
Phase 0.8 selects terrain, product-scope, and connectivity candidates and adds
executable controls. It reduces implementation ambiguity but does not close
R-02, R-07, or R-17 without the named external reviews and regional evidence.
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
`approved`; the independent review remains pending, so the authoritative
disposition and publication gate remain `blocked` and a superseding method is
required.
Phase 0.14 remains the immutable binary-path no-go. ADR-024 completes #106's
contract decision without reinterpreting that evidence. Recovery now follows
#135 → #110; only passing offline source/implementation evidence plus an
explicit project-owner release decision may unlock #48.

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

- real IPCC, Copernicus DEM, and coastal source snapshots pass licence and
  source-shape review;
- a representative regional pipeline passes independent scientific controls;
- Python and TypeScript exact lookup are bit-exact for approved fixtures;
- browser, artifact, offline, performance, and accessibility gates pass;
- staging proves public byte-range/CORS/cache behaviour;
- old/new path differences are explained and approved;
- rollback to a known application/release pair has been tested;
- current cost and source limitations are visible on `/about/architecture`.

If the scientific spike invalidates the binary methodology, pause the
Europe-wide build and write a superseding ADR. Simpler infrastructure never
overrides scientific correctness.

That stop condition fired for binary exposure. Keep Phase 1 paused through
#135 and #110. Passing CI records automated validation only; the project owner
must separately approve the zero-blocker release decision before #48 unlocks.

## Risk review cadence

- Update this register at each migration phase and data release.
- Link material evidence from release reports rather than marking a risk
  “closed” by assertion.
- Escalate a new Critical risk into an ADR or explicit stop condition.
- Move resolved implementation facts into the owning technical document and
  remove the corresponding assumption from the next reviewed version.
