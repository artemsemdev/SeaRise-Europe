# Static target content contract

ADR-024 defines one projection product with exactly four scientific outcomes:
`ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, and
`UnsupportedGeography`. The target application reports regional relative
sea-level change and never restores the rejected binary terrain-comparison
product through copy, code, tests, or build output.

`src/web/scripts/check-target-content.mjs` runs during both lint and production
build. It scans production web source, active project documentation, and emitted
JavaScript/CSS/HTML for obsolete outcome identifiers and affirmative exposure,
terrain-comparison, inundation, or property-risk product claims. Built assets
are scanned separately so source transforms or dependencies cannot reintroduce
the language after the source check.

The scanner executes mutation controls on every run. A future change that
weakens detection of a legacy outcome, affirmative exposure claim, binary
classification, or property-risk score fails before repository content is
accepted.

## Historical evidence allowlist

The following locations retain superseded decisions or measurements for audit:

- `docs/architecture/adr/`;
- `docs/evidence/`;
- `docs/science/`;
- the explicitly marked historical section of `docs/methodology.md`;
- `docs/product/Mock/SeaRise-Flight.html`, whose file header identifies it as
  historical evidence;
- `tests/fixtures/tdd/five-state-characterization-v1.json` and its linked
  `tests/evidence/` records.

These paths are not target-domain inputs and must never be copied into
`src/web`, a release fixture, or production build output. The allowlist permits
preservation, not reuse. New exceptions require an explicit historical label,
an accepted authority, and a scanner review; broad term or directory bypasses
are prohibited.

## Commands

```bash
cd src/web
node scripts/check-target-content.mjs
npm run build
```

The build command invokes the emitted-asset scan automatically.
