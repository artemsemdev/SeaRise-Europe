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

### Changed

- Selected an uncertainty-aware vertical methodology that constructs a
  1995–2014 mean water surface on EGM2008 and returns ambiguous cells as data
  unavailable; exact inputs are now locked, while implementation and
  independent review remain blocking.
- Pull requests now route CI and CodeQL by changed component, so
  documentation-only changes resolve lightweight gates without running
  frontend, API, pipeline, Docker, or full-stack tests.
- Exposure generation now fails closed instead of comparing AR6 relative
  sea-level change directly with absolute EGM2008 terrain heights.
- Phase 0 now records an explicit blocked scientific decision and keeps Phase 1
  locked until vertical-reference, uncertainty, terrain, coastal-scope, and
  independent-review gates pass.
