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

### Changed

- Selected an uncertainty-aware vertical methodology that constructs a
  1995–2014 mean water surface on EGM2008 and returns ambiguous cells as data
  unavailable; publication remains blocked pending exact inputs and review.
- Pull requests now route CI and CodeQL by changed component, so
  documentation-only changes resolve lightweight gates without running
  frontend, API, pipeline, Docker, or full-stack tests.
- Exposure generation now fails closed instead of comparing AR6 relative
  sea-level change directly with absolute EGM2008 terrain heights.
- Phase 0 now records an explicit blocked scientific decision and keeps Phase 1
  locked until vertical-reference, uncertainty, terrain, coastal-scope, and
  independent-review gates pass.
