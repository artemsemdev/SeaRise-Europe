# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

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

### Changed

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
- Phase 0 completed with a `BLOCKED` scientific decision and no classified
  release artifacts; Phase 1 stays locked until all numerical, control,
  reproducibility, golden-vector, and independent-review evidence passes.
