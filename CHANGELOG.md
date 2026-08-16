# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Added production-static browser journey evidence for all four ADR-024
  outcomes and all nine scenario/horizon projections, including exact COG
  values, release-scoped PMTiles identity, keyboard and reduced-motion flows,
  URL restoration, stale-operation races, recoverable delivery failure, and
  fail-closed range-integrity corruption. Screenshots and the exact projection
  matrix are retained only as short-lived CI artifacts.

- Added an explicitly browser-only synthetic `DataUnavailable` control at
  62°N, 44°E. The isolated v2 fixture polygon drives the real static geography
  and exact COG lookup chain, while deterministic gates prove all 27 source
  bands are nodata, prove the control is disjoint from audited geometry, pin
  cross-platform Arrow schemas, and keep the sealed v1 release unchanged.

### Changed

- Bound the canonical frontend npm SBOM to the static `src/web` workspace in
  the root lockfile, including the Flight icon dependency and its exact
  registry integrity, instead of retaining the superseded Next.js lock as the
  active frontend authority.

- Confirmed the SeaRise Flight mock as the active canonical visual and
  interaction reference while adding an explicit ADR-024 correction map and a
  fail-closed annotation gate. Its layout, hierarchy, map-first composition,
  controls, responsive behavior, and interaction character remain required;
  binary exposure, terrain/flood/property meaning, and other prohibited claims
  remain excluded from the target application and built assets.

### Security

- Pinned private overlay cleanup to an open directory identity so immediate
  inode reuse cannot redirect recursive deletion to a replacement directory.

- Enforced an exact static-document Content Security Policy and `no-referrer`
  policy on both browser entry routes, with browser/build gates for blocked
  unlisted origins and the one optional OpenFreeMap origin. Manifest schemas
  are now compiled ahead of time so runtime validation needs no `unsafe-eval`;
  deployment retains responsibility for the response-only `frame-ancestors`
  protection.

- Pinned the legacy API test container dependency graph to SSH.NET 2026.0.0,
  removing the high-severity recursive SCP path-traversal advisory from the
  locked restore while that test runtime awaits Phase 2 removal.

### Fixed

- Aligned the static landing copy with the approved product language and bound
  its release disclosure to the verified synthetic, private-engineering, or
  public-promoted disposition instead of hard-coding fixture status.

- Aligned settlement no-match guidance with the approved product copy and
  corrected active product documentation to identify the implemented static
  runtime as the sole code baseline.

- Corrected the application live status after terminal projection failures so
  assistive technology no longer announces that a completed failed operation
  is still being checked, while any previous accepted outcome remains explicit.

- Made the committed browser release checksum list an exact, canonical view of
  the manifest artifact inventory. Comments and blank lines can no longer be
  misread as artifacts, and missing, extra, duplicate, or stale entries fail
  the deterministic fixture gate.

- Corrected the methodology dialog definitions so `OutOfScope` means inside
  supported Europe but outside the versioned coastal analysis area, while
  `UnsupportedGeography` means outside the versioned Europe support geometry.

- Separated the sealed v1 release identity from the deterministic browser
  overlay identity. The v1 build receipt and provenance remain byte-identical;
  the overlay now has dedicated versioned derivation evidence with no
  fabricated run, workflow, platform, timestamp, revision, or SLSA claim, and
  its acyclicity gate is scoped to the overlay-derived digest graph.

- Bound browser support/coastal classification to a shared twelve-case Shapely
  parity golden covering exterior and hole boundaries plus epsilon seams. Exact
  COG reads now cancel uncached post-open range transport only after their last
  caller leaves, preserve concurrent readers, and gate the inclusive 100 km
  decision in the production reader.

- Restored complete npm registry URL and SHA-512 integrity metadata for the
  static browser dependency graph, pinned its scientific readers, and made the
  dependency inventory fail closed if future registry identities are missing.

- Strengthened static COG delivery validation with a deterministic valid COG
  whose unchanged image tiles occupy a later fourth range chunk, strict
  malformed-range rejection, and a production-built same-origin browser lookup
  that proves CSP-compatible `HEAD`/`206` delivery, later-chunk SHA-256
  verification, sub-artifact transfer, and scoped cold-versus-cached budgets.
  CORS headers are inspected separately without claiming public cross-origin
  browser enforcement or Candidate performance.

- Replaced the cross-port private-candidate harness with one read-only,
  same-origin loopback binding that derives only `verified: false` local
  metadata, strictly allowlists immutable files and ranges, and proves the
  complete ignored Candidate-v7 tree is unchanged after browser testing.

- Bound private real-source candidates to reviewed STAC archive/member lineage,
  an existing Git code revision, the exact local dependency lock, build
  parameters, and pipeline identity. The superseded candidate with fixture
  provenance is retained locally, and a corrected no-upload candidate is
  derived and fully gated without rebuilding the heavy source artifacts. The
  new lock is included in the reviewed dependency inventory and regenerated
  build-plane CycloneDX SBOM.

- Fixed bounded settlement search failing closed on production-scale core and
  coastal shards. The browser now searches the canonical sorted entries through
  compact length and signature-count indexes, applies admissible lower bounds
  before banded fuzzy distance, and uses direct ordinal-array lookup. Results,
  ranking, candidate bytes, and the 250,000-unit work limit are unchanged;
  exact manifest-bound artifacts now pass the browser latency and memory gates.

### Changed

- Adopted an accelerated static-runtime cutover: Phase 2 now removes the
  superseded repository runtime after equivalent-or-stronger target coverage
  exists. Git history is the source rollback; private candidate bytes and
  destructive external cloud cleanup remain outside this authorization.

- Required real-source architecture evidence to expose the exact cryptographic,
  public-readback, and local-handoff receipt links while keeping those
  post-finalization records outside the pre-sign manifest inventory.
- Extended settlement browser-worker evidence to pass explicit spatial source,
  validation-workspace, and release authorities through the v4 shard builder,
  loader, and worker decoder while retaining byte-exact v3 fixture validation.

### Added

- Added a framework-neutral atomic projection state contract that binds every
  accepted outcome to its immutable selection and release, retains prior
  results explicitly during updates, and rejects stale asynchronous
  completions by monotonic token, selection identity, and release identity.

- Added a lazy MapLibre/PMTiles visualization path that resolves all nine
  visual-only overlays from the pinned release context, keeps map clicks on the
  shared selection command, degrades safely without the optional basemap, and
  preserves keyboard, text-alternative, attribution, range-request, and initial
  bundle gates.

- Added an exact browser-side AR6 projection lookup that verifies release-bound
  support geometry, consumes the verified release source-grid identity, checks
  COG `HEAD` and canonical range-chunk hashes, validates embedded
  scenario/horizon/source/quantile metadata, selects the nearest native
  source-grid location within the inclusive 100 km limit, returns the three
  required quantiles, and preserves technical failures outside the four
  scientific outcomes. The committed synthetic release now carries the
  browser-decodable boundary fixtures used by clean-clone tests.

- Added a release-scoped static GeoNames search Worker with deterministic
  normalization and ranking, core-first partial readiness, exact transport-byte
  verification, authoritative v4 release/source/spatial/index validation,
  pinned lazy Brotli decoding, core-then-unseen-coastal merge, private in-memory
  queries, stale-selection prevention, and an accessible keyboard combobox.
  Search failures remain technical errors and do not expand the four scientific
  outcomes.

- Added the browser's pinned-manifest anti-corruption layer: generated
  schema-derived TypeScript contracts, an immutable release context, exact
  nine-combination and artifact-reference validation, origin-safe URLs,
  release-scoped share state, bounded same-release startup retry, and a
  technical-error vocabulary separate from the four scientific outcomes.

- Added the React 19 and Vite 8 static application shell with two direct static
  routes, bundled fonts, honest synthetic-fixture identity, lazy architecture
  evidence, a measured build inventory, zero-API boundary checks, and desktop
  and mobile Chromium accessibility smoke tests.

- Added local retained-evidence PMTiles validation so an exact final candidate
  can be fully gated on Apple Silicon without executing pinned Linux x86_64
  tooling under unstable emulation. Candidate bytes must match both the prior
  validated artifact and its checksum/report authorities.
- Added release v2 attribution and build-receipt contracts that cover the
  settlement search receipt role introduced by the 54-artifact candidate
  contract while leaving the published release v1 contracts immutable.
- Added an authoritative validator for already-built projection PMTiles that
  rechecks pinned tool identities, canonical metadata and headers, and decoded
  source-property parity without rebuilding the archive.
- Added candidate-bound production validators for projection COG, GeoParquet,
  and PMTiles files, exact support and coastal boundary packages, and the
  descriptor-bound settlement GeoParquet spatial stage.
- Added a retained-evidence settlement GeoParquet authority that revalidates
  exact artifact bytes, schema, row groups, spatial identity, and the canonical
  full-replay receipt without transporting the multi-gigabyte DuckDB stage.
- Added candidate-bound JSON validators for release contracts, exact rights
  coverage, build-output inventory, STAC graph and asset identities, and the
  settlement search shard-set receipt.
- Added checksum-pinned, bounded Brotli decoding for production settlement
  search shards with schema, semantic, candidate, and shard-name binding.

- Added a candidate-wide QA executor that byte-gates the complete manifest,
  dispatches every schema-selected artifact in manifest order, retains explicit
  pass, fail, and not-measured dispositions, and rejects candidate mutation
  during validation before any release eligibility can be reported. The same
  authority now validates the exact 51-artifact pre-terminal snapshot before
  gate reports, checksums, and the manifest exist, then renders deterministic
  JSON and Markdown checks grouped by authoritative validator and exact evidence
  hashes without making a publication claim. A manifest-last production
  assembler now seals those inputs into the complete 54-artifact candidate and
  reruns the byte gate and full validator matrix before exclusive publication.
  Repository-controlled terminal validators independently verify the report
  schema and binding, deterministic Markdown rendering, and checksum inventory.
- Added a release-bound settlement Web Worker and Chromium evidence harness
  with core-first loading, monotonic query tokens, bounded search, static-only
  networking, worker-isolate memory telemetry, and accepted production-scale
  initialization and query budget checks.
- Added a version-selected candidate QA routing matrix and explicit-outcome
  dispatcher that cover every v2 artifact role, media type, and content
  encoding and fail closed on missing, duplicate, unsorted, unknown, or
  unimplemented validator routes. Complete synthetic candidates now use the
  shared release-gate schema and deterministic Markdown renderer, with explicit
  targets, measurements, evidence hashes, and blocking unmeasured checks.
- Added a durable Phase 1 settlement production inventory binding the verified
  GeoNames, catalogue, spatial, GeoParquet, search, shard, query-set, and
  Node-worker diagnostic identities while keeping browser and publication
  claims explicitly blocked.
- Added receipt-bound, bounded-memory settlement reconciliation evidence that
  separates pre-spatial catalogue rejections from classified and
  spatial-rejected normalized records, reports decision-split quality
  dimensions, and fails closed on arithmetic, ordering, identity, or claim
  drift without making a production or publication claim.
- Added a checked-in representative synthetic settlement browser-worker report
  with exact shard and query identities, deterministic validation, and explicit
  non-production and no-accepted-browser-budget status.
- Added a receipt-bound settlement search performance harness that measures
  exact raw/compressed shard sizes, record counts, deterministic build and Node
  worker initialization/query distributions, and observed worker memory while
  preserving explicit browser, production, owner, scientific, and publication
  nonclaims.
- Added the settlement v4 public browser-search envelope and receipt-last set,
  binding the code-point-trie shards to one explicit data release, exact spatial
  receipt and geometry identities, source provenance, runtime, ranking, merge,
  and Brotli semantics while retaining fail-closed nonpublication claims. The
  build now replays the projection against its exact spatial database and lists
  the receipt-last completion marker in the candidate v2 inventory while the
  published candidate v1 and release v1 definition bytes remain unchanged.
- Added a deterministic complete-candidate fixture assembler that verifies 51
  explicit synthetic inputs, generates the terminal gate reports and checksum
  inventory, writes the manifest last, runs the independent byte gate, and
  exclusively promotes a read-only 54-artifact candidate without making
  production, scientific, format-validity, or publication claims.
- Added a read-only, descriptor-bound Phase 1 candidate byte gate that requires
  the exact 54-artifact inventory with no extra entries, streams and verifies
  declared sizes and SHA-256 values, reconstructs checksum content, and rejects
  symlink escapes or identity drift through a final descriptor linearization
  pass. Directory diagnostics and declared byte budgets are bounded; the result
  is a point-in-time observation without a production or publication claim.
- Added an immutable Cosign Linux AMD64 tool lock backed by the official
  versioned release checksum asset, with fail-closed local validation and
  build-plane SBOM coverage. Signing remains blocked on the reviewed evidence
  finalizer and protected workflow.

### Fixed

- Replaced full-corpus settlement reconciliation sorts with single-pass,
  order-checking stage scans so production evidence remains within the 1 GiB
  no-spill memory boundary.

### Security

- Added an atomic local supply-chain evidence handoff and independent validator
  that bind the exact manifest, finalized evidence, cryptographic-verification
  receipt, and public-readback receipt under the data release ID. The receipt
  explicitly leaves external retention, deletion prevention, and data-release
  co-retention unverified and makes no production, publication, or scientific
  approval claim.

- Added fail-closed, descriptor-bound finalization for exact pre-verification
  candidate evidence, with complete source authority, a durable pathname
  checkpoint, a machine-readable whole-evidence commit identity, isolated work
  parents, and bounded private snapshot residue retained for pathname-race safety
  on isolated ephemeral runners.
- Hardened complete-candidate assembly with inode-bound private staging,
  foreign-preserving bounded quarantine rollback, an owner-controlled isolated
  runner boundary, and a coherent point-in-time final tree-identity pass before
  success is returned.
- Added a standard-library-only protected-workflow artifact boundary that
  atomically binds the exact successful controlled `master` run to its complete
  GitHub artifact inventory, publishes its immutable canonical authority receipt
  through a private same-directory partial and atomic no-overwrite promotion,
  and safely streams distinct candidate and evidence ZIP inventories without
  following links or making production, publication, or scientific claims.
- Added a manual protected-environment workflow for keyless Cosign signing of
  exact controlled-candidate bytes, with job-scoped OIDC, fork and pull-request
  refusal, and separate no-OIDC verification of freshly downloaded immutable
  artifacts. It makes no production, publication, scientific-approval,
  protected-environment-execution, or public-readback claim.
- Added a fail-closed HTTPS readback hook that reruns identity-bound Cosign
  verification before proving public manifest and provenance bytes exactly
  match the signed subjects, with a canonical non-approval audit receipt.
  Retrieval is restricted to reviewed origins, entirely public DNS answers,
  pinned TLS peers, direct responses, and an enforced per-subject deadline;
  descriptor-bound output isolation prevents the receipt from mutating verified
  inputs, and post-commit output failures cannot reverse durable success.
- Added deterministic pre-sign provenance for validated real-source controlled
  candidates, with explicit nonclaims for cryptographic verification,
  production, publication, scientific approval, signing, and environment approval.
- Added a distinct immutable real-source pre-verification evidence envelope
  that binds exact candidate bytes while rejecting signing, identity,
  environment, production, publication, and scientific-approval claims.
- Added identity-bound Cosign verification for exact manifest and provenance
  bytes with immutable non-publication receipts and independently reviewed tool locks.
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

- Added deterministic non-publishing settlement GeoParquet serialization bound to the exact spatial database, receipt identity, v3 Arrow schema, and false approval claims.
- Added inode-safe, no-overwrite publication of reproducibly rebuilt settlement GeoParquet artifacts with canonical receipts and fail-closed rollback.
- Added a receipt-bound, streaming settlement search-projection contract that
  preserves normalized names, context, lineage, and spatial membership while
  explicitly making no production or publication claim.
- Added deterministic, Brotli-compressed code-point-trie browser candidates for
  the core and coastal settlement memberships, with exact projection binding,
  descriptor-relative receipt-gated handoff, rebuilt index verification,
  canonical compression, core-first duplicate-free merge semantics, and
  explicit nonpublication claims.
- Added fail-closed offline validation for the exact pre-sign candidate inventory,
  checksum subjects, STAC matrix, and required pending evidence-pair gate without
  reading artifacts, signing, or making a publication decision.
- Added the exact 54-artifact pre-sign engineering candidate v2 contract, with
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
- Added a receipt-bound spatial-classification stage with exact identities and
  an expiring opaque capability for authority-snapshotted `LOAD` and `ST_Read`.
- Added an immutable spatial-stage runner that validates descriptor-bound inputs and publishes the database before its canonical receipt without broadening scientific, owner, hazard, geometry, or publication claims.
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

- Replaced full-corpus settlement search-projection sorts with single-pass,
  order-checking spatial-stage scans while retaining the 1 GiB no-spill
  validation profile and exact receipt reconciliation.
- Closed settlement reconciliation rejection reasons to the reviewed stage
  vocabularies and prevented reserved DuckDB WAL output names from reaching staging.
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
