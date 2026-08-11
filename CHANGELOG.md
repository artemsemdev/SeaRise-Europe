# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Security

- Added descriptor-safe offline pairing with strict Sigstore bundles and regenerated SBOMs.
- Added deterministic unsigned in-toto/SLSA provenance for validated synthetic
  candidates, binding scientific outputs, source payloads, receipts, and the controlled run.
- Added a deterministic CycloneDX 1.7 file-input authority foundation for
  candidate build-plane workflow, container-recipe, and native-toolchain files,
  with exact repository paths, SHA-256 authority, and explicit OpenTofu
  absence, plus full-revision Actions, native binaries/packages, lock-recorded
  DuckDB/Spatial artifacts, OCI bases, and explicit production nonclaims.
- Added immutable, project- and target-specific NuGet CycloneDX inventories for
  deployable API and library projects, with exact artifact/project/lock
  authority, explicit test-project exclusion, and no production claim.
- Added owner-controlled, no-follow private snapshots for settlement spatial inputs, with inode-tracked cleanup and inspectable fail-closed residue when descriptor identity is unavailable.
- Included reviewed real Python graph annotations in exact dependency-input
  discovery and SHA-bound inventory validation while excluding synthetic test
  fixtures.
- Added reviewed, hash-bound Python runtime graphs for the paired release and
  settlement-spatial locks, with explicit roots, complete target environments,
  and identical cross-platform active dependencies without a production claim.
- Added deterministic target-specific Python CycloneDX 1.7 SBOM generation,
  exact graph and wheel-hash validation, inode-verified immutable publication,
  and canonical checked-in SBOMs for the four reviewed release and
  settlement-spatial CPython 3.11 targets. These remain non-production
  dependency evidence and are not attached to a candidate.
- Added a versioned, lock-SHA-bound Python dependency graph annotation contract
  so reviewed roots and edges remain explicit instead of being inferred from
  flat release locks, with synthetic-only fail-closed validation fixtures.
- Added deterministic CycloneDX 1.7 generation for the frontend npm lock with
  exact input and component hashes, path-qualified dependency relationships,
  offline schema validation, immutable publication, canonical validation, and a
  checked-in artifact bound to the real candidate lock.
- Added a versioned, hash-bound inventory of dependency-defining repository
  inputs with exact fail-closed discovery, safe-path enforcement, and explicit
  non-production and OpenTofu-absence claims.
- Defined immutable signed-candidate evidence and dependency-exception
  contracts with a pinned production identity, complete offline validation
  against hash-pinned official CycloneDX 1.7 schemas, and synthetic-only
  fixtures that make no real signing or verification claim.
- Pinned every third-party GitHub Action and build/release container image to
  its reviewed commit SHA or manifest digest, with a fail-closed repository
  validator that rejects mutable references.

### Added

- Added fail-closed offline validation for the exact pre-sign candidate inventory,
  checksum subjects, STAC matrix, and required pending evidence-pair gate without
  reading artifacts, signing, or making a publication decision.
- Added the exact 53-artifact pre-sign engineering candidate contract, with
  manifest-last sealing, complete 3 x 3 and settlement inventory, and a
  mandatory non-recursive supply-chain evidence-envelope gate.
- Added typed JSON and Markdown release-gate report artifacts to the immutable
  public release contract.
- Added an immutable full-source settlement input contract that verifies exact
  archive, decompressed member, row-count, and reviewed-policy identities and
  emits deterministic source bindings without claiming staging or publication.
- Added a neutral, versioned settlement search evaluation foundation with
  deterministic MiniSearch and FlexSearch adapters and synthetic-only evidence.
- Added settlement v3 public place, GeoParquet, and search-shard contracts as
  the version-aware successor to v2, preserving stable source, identity, name,
  location, population, feature, and lineage meanings while binding exact
  spatial identities, record and name roles, whole-meter coastal distance,
  search projections, shared cross-runtime count semantics, and fail-closed
  approval claims. The v2 contract bytes remain unchanged for existing
  consumers.
- Added a hash-bound internal settlement spatial classifier with deterministic
  support/coastal membership, whole-meter EPSG:3035 shoreline distance,
  rejection-ledger semantics, and exact pinned DuckDB Spatial CI evidence.
- Added a scoped, hash-locked Natural Earth settlement shoreline recipe using
  direct main and minor-island source lines, deterministic whole-feature
  selection, an explicit EPSG:3035 distance method, and independent named-place
  controls without making a hazard, canonical-coastline, or publication claim.
- Added a separate immutable Python 3.11 DuckDB Spatial build plane for
  settlement processing, with official Linux/macOS extension byte identities,
  checksum-first cache admission, and a network-free live-load preflight.
- Added lossless typed GeoNames `allCountries` and `admin1CodesASCII` row parsers
  with pinned source identity, exact lineage, explicit raw anomaly flags, and
  hash-bound real-format fixtures.
- Added hash-bound `alternateNamesV2` and ISO-language parsing plus a versioned
  settlement inclusion, canonical-name, temporal filtering, and deduplication
  policy with deterministic selected-record lineage.
- Added an offline, checksum-bound full-snapshot validation report for the
  pinned GeoNames alternate-name and ISO-language members.
- Added an immutable v1 pure settlement catalogue policy/domain with
  source-derived IDs, explicit rejections, audited admin1 context, selected
  lineage, and stable ordering.
- Added durable normalized-catalogue publication with a database-first commit,
  a receipt completion marker, and inode-owned rollback that preserves racing
  replacements.
- Added the first versioned Phase 1 public release contracts, locking the exact
  scenario/horizon matrix, defaults, discriminated four-state result payloads,
  grid-only 100 km lookup semantics, source identity, owner authority, and
  prohibited scientific claims in JSON Schema.
- Added audited v1 source and build receipt contracts that bind offline inputs,
  hashes, licences, toolchain/environment identity, outputs, and reproducibility
  comparison fields without publishing source-cache content.
- Added versioned settlement search, automated quality, architecture evidence,
  and release-pointer contracts with explicit synthetic labels, local-only
  search/privacy guarantees, and zero application API calls.
- Added one immutable artifact contract for release-relative paths, typed media
  roles, byte/hash identity, lineage, rights, exact COG/GeoParquet use, and
  visual-only PMTiles use.
- Added the versioned release manifest contract as the only browser entry point,
  with the complete 3 × 3 dataset index, source/authority bindings, immutable
  publication policy, and references to all contract and evidence artifacts.
- Added a pinned STAC 1.1.0 profile for the static catalog, collection, and
  projection items, preserving exact COG, analytical GeoParquet, and visual-only
  PMTiles roles without runtime discovery endpoints.
- Added fail-closed manifest, rights, and STAC semantic validation so individually
  valid documents cannot disagree on release identity, dataset context, artifact
  paths, roles, sizes, or hashes.
- Added shared-fixture validation in TypeScript and path-aware CI routing so every
  public contract change runs both browser and Python contract suites.
- Added deterministic browser-facing TypeScript types generated from the
  authoritative public JSON Schema, with CI-enforced drift detection.
- Added a complete committed 3 × 3 public release fixture with real geospatial
  formats, exact inventory hashes, STAC links, rights, and safe pending status.
- Added the accepted static-first, offline geospatial architecture and its
  phased migration roadmap.
- Added checksum-first source acquisition, an audited source registry, and
  machine-readable contracts for the pinned IPCC AR6 and Copernicus inputs.
- Added a real-source North Sea regional fixture with deterministic receipts,
  exact COG range measurements, and shared Python/TypeScript lookup vectors.
- Added the TDD characterization and migration harness for tracking permanent
  tests, shared fixtures, parity evidence, and mutation controls.
- Added checksum-locked AR6 interval members, a complete 1995–2014 monthly
  Copernicus Marine SLA/MDT baseline, GOCO06S and EGM2008 models, and compact
  GLO-30/GLO-90 terrain-control manifests with licence and coverage evidence.
- Added fail-closed uncertainty-aware vertical reconciliation with exact AR6
  likely intervals, a complete calendar-weighted water baseline, explicit
  uncertainty provenance, stable nodata reasons, and deterministic evidence
  receipts.
- Added an explicit Phase 0.9 gate and reproducible nine-combination preflight
  record that cannot treat CI success as scientific approval.
- Added a machine-readable 90% coastal uncertainty budget with source hashes,
  eligibility masks, sensitivity controls, and mutation-resistant fail-closed
  semantics.
- Added a checksum-first AR6 projection reader, source-native grid lookup, and
  offline real-source goldens with independent Python-reader and browser parity
  across all nine scenario/horizon combinations.
- Added a protected, owner-only Phase 0R promotion gate that binds the final
  decision to two trusted GitHub candidate artifacts, raw browser/timing
  evidence, exact code and evidence merges, and a mandatory permanent
  owner-record pull request before Phase 1 can unlock.
- Added the trusted Phase 0R Linux and macOS ARM64 release evidence bundle,
  proving byte-identical artifacts, zero scientific-value difference, and
  browser delivery within the release budgets before owner approval.
- Added a deterministic receipt-driven offline release builder with one typed
  fixture/regional/full stage graph, identity-safe resume, atomic immutable
  candidates, pinned network-disabled execution, and separate controlled runs.
- Added a separate settlement v2 public contract with exact source spelling,
  per-record lineage, language/script metadata, and synthetic representative
  GeoParquet and search-shard envelopes that reject incompatible schema,
  format, serialization, geography-publication, and field-identity metadata.
- Added derive-stage validation for the owner-approved Phase 0R projection
  bundle, rechecking exact COG and GeoParquet semantics, independent lookup
  goldens, and the byte-bound decoded-PMTiles parity evidence before promotion.
- Added candidate-bound loopback HTTP evidence for all 54 reviewed COG byte-range
  requests, including raw local latency measurements and fail-closed malformed,
  ignored, truncated, substituted, and corrupt-response controls, with exact
  workflow head, tested revision, run, job, and clock identity, without making
  public CDN or production-delivery claims.
- Added deterministic analytical GeoParquet packaging for the checked-in support
  and coastal engineering boundaries, preserving their approximate,
  product-eligibility-only status and Natural Earth attribution while preventing
  them from being presented as canonical, production, or publication-ready data.
- Added deterministic visual-only PMTiles packaging for those exact boundary
  GeoParquet bytes, with pinned-tool verification and independently decoded
  property and geometry parity that prohibits analytical lookup.
- Added a scoped, hash-locked GeoNames 2026-08-10 settlement snapshot with full
  place, alternate-name, language, admin, format, and licence inputs, while
  preserving the historical Phase 0R source lock byte-for-byte.
- Added a versioned release gate-report contract with closed decision states,
  metric-bound evidence, owner-only release authority, non-downgradable
  critical stops, shared Python/TypeScript semantics, and a deterministic
  human-readable Markdown rendering.
- Added fail-closed byte-range validation for all nine owner-reviewed analysis
  COG identities, covering canonical and TIFF-reader-driven requests plus
  malformed, ignored, truncated, substituted, and corrupted responses.
- Added a fail-closed PMTiles v3 structure contract for visual-only boundary
  candidates, binding checked-in source geometry, lineage, safe metadata,
  directory sections, and tile counts without granting canonical status.
- Added immutable z0/z3/z6 projection-PMTiles QA renders bound to the approved
  Phase 0R bytes, with lower/median/upper value-bin coverage and exact
  source-nodata transparency probes.
- Added an independent decoded boundary-PMTiles parity oracle with exact IDs
  and properties, zoom-6 extent-131072 quantization bounds, independent indexed
  symmetric vertex-to-boundary checks, and compensated topology-loss rejection.
- Added a controlled exact-pinned boundary build that produces support and
  coastal GeoParquet/PMTiles candidates twice, rejects byte or inspection
  drift, compares detail/segmentization profiles, exercises z0/z3/z6 through
  Chromium and MapLibre, and retains candidate-bound receipts, checksums,
  structure, decoded-parity, and browser evidence.

### Changed

- Replaced the settlement classifier's missing-shoreline blocker with
  fail-closed real-source bindings for the exact reviewed support, coastal, and
  shoreline artifacts while retaining selected-scope and non-publication
  status.
- Aligned user-facing search copy with the settlement-only catalog boundary,
  without promising address, postal code, or landmark lookup.
- Published the public-contract compatibility, deprecation, and rollback policy,
  and aligned active architecture/delivery status with the approved Phase 0R gate.
- Aligned active architecture, runtime, product, and delivery documentation on
  the four-state AR6 projection contract and its owner-controlled evidence flow.
- Full-source AR6 release evidence now builds independently on pinned Linux
  and macOS ARM64 profiles from one exact `master` SHA, with fail-closed
  dispatch guards, separate candidate artifacts, and a locked Chromium
  delivery trace for owner validation.
- Regional release comparison now reports local byte and value parity as
  pending until trusted external build provenance is bound to both candidate
  digests; self-declared receipt profiles can no longer prove independence.
- Replaced the blocked binary terrain-exposure contract with a source-native
  IPCC AR6 regional projection contract that reports the median and published
  likely range, uses one grid-only lookup rule, and keeps release approval
  separate from automated validation.
- Selected fail-closed GLO-30 terrain, explicit Europe and 25 km coastal
  product-scope rules, and an ocean-seeded connectivity screen backed by
  measured controls; scientific publication remains blocked pending complete
  terrain uncertainty bounds and external approvals.
- Selected an uncertainty-aware vertical methodology that constructs a
  1995–2014 mean water surface on EGM2008 and returns ambiguous cells as data
  unavailable; exact inputs and computational contracts are now locked, while
  numerical geoid conventions, bounds, controls, reproducibility, and
  independent review remain blocking.
- Pull requests now route CI and CodeQL by changed component, so
  documentation-only changes resolve lightweight gates without running
  frontend, API, pipeline, Docker, or full-stack tests.
- Exposure generation now fails closed instead of comparing AR6 relative
  sea-level change directly with absolute EGM2008 terrain heights.
- Phase 0.9 completed with a `BLOCKED` disposition and no classified release
  artifacts; its corrected evidence remains an immutable historical record and
  was not rewritten by the later no-go decision.
- Automated methodology analysis now recommends rejecting the current coastal
  binary method because the locked evidence provides no finite SLA shoreline
  or GLO-30 DSM-to-bare-earth bound. Independent review remains pending, so
  the authoritative scientific and release disposition is blocked.
- Completed the Phase 0 investigation with a no-go: all nine release attempts
  stop before arrays, the automated v1 recommendation is rejected, the
  authoritative scientific disposition remains blocked pending independent
  review, and Phase 1 stays locked.
- Superseded ADR-023 as a publication path and defined the recovery order from
  a new product-contract decision through independently validated coastal
  water, bare-earth terrain, methodology v2, and a final reviewed regional
  gate. Historical receipts remain unchanged.

### Fixed

- Corrected the immutable full-source contract to match the official
  `alternateNamesV2.zip` member order while retaining path-based member staging.
- Hardened normalized-catalogue validation with exact source replay, reconciled
  rejection counts, and bounded DuckDB sorting and alternate-name grouping.
- Pinned the single writer-owned GeoParquet Arrow schema FlatBuffer and
  canonicalized Tippecanoe gzip platform markers so the Linux and macOS ARM64
  release profiles produce identical analytical and visual artifact bytes
  without changing their values.
- Pinned the macOS ARM64 Tippecanoe reference build to the hosted Xcode 15.4
  environment and added a lightweight release-change preflight so toolchain
  drift fails before the full AR6 evidence build downloads source data.
- Restored the macOS ARM64 trusted evidence producer with a supported,
  hash-locked CPython 3.11 runtime after GitHub retired Python 3.9 from that
  hosted runner.
