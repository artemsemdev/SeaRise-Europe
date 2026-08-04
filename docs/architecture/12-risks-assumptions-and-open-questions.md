# Risks, Assumptions, and Open Questions

> **Status:** Current migration register
> **Authority:** [ADR-021](adr/ADR-021-static-first-offline-geospatial-architecture.md)
> **Review rule:** Update evidence and disposition; do not silently convert an
> assumption into a fact.
>
> **Phase 0.2 evidence:** [source semantics, datum, DEM, and geometry QA](../science/phase-0-2-source-and-geography-evidence.md)

## Current risk register

| ID | Risk | Likelihood / impact | Mitigation and exit evidence |
|---|---|---|---|
| R-01 | The exact IPCC AR6 archive member differs from the documented binding schema | Medium / Critical | Heuristics have been removed and the documented `20210809` mapping fails closed. Exit requires SHA-256 locking the regional archive and a direct member inspection report matching the contract. |
| R-02 | The binary elevation comparison creates disconnected inland false positives or misrepresents coastal pathways | High / Critical | Publication now fails closed. Compare the tested eight-neighbour ocean-seeded candidate with unfiltered output and independent controls; supersede methodology ADR if invalid. |
| R-03 | Source or derivative redistribution terms are incomplete | Medium / Critical | Licence review for each source and derivative; manifest attribution; block publication until all rights and required wording are documented. |
| R-04 | Browser exact lookup disagrees with the build array because of CRS, tile, row/column, resampling, or nodata differences | Medium / Critical | Shared golden fixtures across Python and TypeScript; nearest-neighbour binary lookup; bit-exact parity tests at cell edges and nodata. |
| R-05 | Search indexes are too large or slow on mobile | Medium / High | Core/coastal shards, Brotli, lazy Web Worker load, representative mobile benchmarks, size/count report, deterministic ranking tests. |
| R-06 | GeoNames misses, duplicates, or misclassifies settlements implied by “all coastal cities and villages” | High / High | Publish the operational definition, snapshot/date, feature-code rules, exclusions, corpus counts, duplicate/transcontinental QA, and limitations. |
| R-07 | The approximate 25 km coastal zone is mistaken for flood reach | Medium / High | Contract and evidence label it `approximation`; 19 controls pass, but canonical Copernicus comparison, rebuild parity, and topology remain blocking. Keep product-scope language explicit. |
| R-08 | PMTiles plus analysis COGs exceed free storage or cause excessive R2 range operations | Medium / Medium | Regional size/request spike, range-locality measurement, cache tuning, release cost model, usage alerts; consolidate only after exact-lookup proof. |
| R-09 | Service Worker mixes application and data releases | Medium / High | Namespace caches by app version and `dataReleaseId`; atomic activation; offline/mid-update tests; fail closed on mismatch. |
| R-10 | OpenFreeMap changes or is unavailable | Medium / Low | Treat it as non-authoritative visual context; graceful no-basemap mode; preserve a documented self-host/alternate-style path. |
| R-11 | Cloudflare pricing, limits, or custom-domain behaviour changes | Medium / Medium | Date the cost model, alert on usage, avoid proprietary runtime services, and retain a static host + byte-range object storage portability test. |
| R-12 | Build dependency, source, action, or publication credential is compromised | Medium / Critical | Pin dependencies/actions, verify checksums, scan dependencies/secrets, generate SLSA provenance, Cosign-sign manifests, protect production and use least privilege. |
| R-13 | Static architecture is presented as complete before real-data validation | Medium / Critical | Clearly label synthetic fixtures; block production claim and decommissioning until ADR-021 Phase 0–3 gates pass. |
| R-14 | Documentation and implementation diverge during staged migration | High / Medium | Mark target vs current state, link to ADR-021, enforce architecture fitness tests, and remove old service docs only as their target contracts are documented. |
| R-15 | Relative AR6 change is compared directly with absolute EGM2008 DSM height | Certain / Critical | The build now refuses this operation by default. Exit requires a pinned baseline water/tidal surface, reviewed transformation to EGM2008, combined uncertainty controls, and scientific/data approval. |

The [Phase 0.3 regional gate evidence](../evidence/phase-0-regional-fixture.md)
records the current blocked disposition for R-01, R-02, R-04, R-07, R-08,
and R-13. It proves a small real COG and lookup/range mechanics, but closes none
of those risks: datum compatibility, scientific controls, connectivity,
canonical coastal scope, PMTiles, public hosting, and human review remain open.

## Assumptions that require evidence

| ID | Assumption | Required validation |
|---|---|---|
| A-01 | A static browser path can preserve all five domain result states | Golden tests across Europe support, inland coast scope, nodata, exposed, and non-exposed locations |
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
| What is the final Europe support polygon and how are transcontinental states treated? | Candidate explicitly excludes Russia/Turkey, includes Azores, and excludes out-of-clip territories; 19 controls and `covers` boundary semantics are recorded | Product-owner approval; ADR if domain outcomes change |
| Copernicus DEM GLO-30 or GLO-90? | One real window measures 9× pixels, 8.53× bytes, and local differences but lacks representative independent truth | More representative windows and scientific review; record one choice in the contract |
| What coastline-connectivity algorithm is scientifically acceptable? | Eight-neighbour ocean-seeded comparison is deterministic and tested but unreviewed | Independent controls and scientific review; superseding methodology ADR if v1.0 changes |
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

## Risk review cadence

- Update this register at each migration phase and data release.
- Link material evidence from release reports rather than marking a risk
  “closed” by assertion.
- Escalate a new Critical risk into an ADR or explicit stop condition.
- Move resolved implementation facts into the owning technical document and
  remove the corresponding assumption from the next reviewed version.
