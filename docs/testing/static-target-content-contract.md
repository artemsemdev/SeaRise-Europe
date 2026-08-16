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

A second, product-copy-only layer scans production web source and emitted
assets, but not guidance that must discuss rejected wording. It rejects
certainty about flooding, safety, risk, personal property, or precision;
unsupported promises about complete settlement coverage, permanent cost, or
fully offline operation; relative `+N years` horizons; forecast-model framing;
five-state target models; and affirmative flood-probability statements.

The scanner executes mutation controls for every category on every run. A
future change that weakens either the target-domain exclusions or the stricter
product-copy rules fails before repository content is accepted.

## Canonical Flight reference exception

`docs/product/Mock/SeaRise-Flight.html` is the active canonical visual and
interaction reference, not historical-only evidence. Its layout, information
hierarchy, map-first composition, controls, responsive behavior, and
interaction character are reusable target requirements. The self-contained
mock also contains rejected prototype science that cannot be scanned as target
product copy or copied into the production bundle.

The scanner therefore excludes the mock body from the target-domain text scan
only after its pre-document annotation proves all of the following:

- active canonical visual and interaction authority;
- explicit preservation of the Flight composition and behavior;
- `exposed` and `notexposed` map to `ProjectionAvailable`;
- `unavailable` maps to `DataUnavailable`;
- `outofscope` maps to `OutOfScope`;
- missing `UnsupportedGeography` must be added;
- technical failures remain outside the scientific outcome domain.

The gate also requires the active preservation contract and four-outcome map in
`MOCK_REQUIREMENTS_MAP.md`, and verifies that its declared SHA-256 matches the
exact canonical mock bytes. Removing or weakening any marker or changing the
mock without updating its reviewed digest fails the content gate. This narrow
exception authorizes reuse of visual and interaction design, not binary
exposure, terrain comparison, modeled-water/flood meaning, hazard claims,
fixture facts, or product copy. The canonical mock is never copied into the
production build.

## Historical evidence allowlist

The following locations retain superseded decisions or measurements for audit:

- `docs/architecture/adr/`;
- `docs/evidence/`;
- `docs/science/`;
- the explicitly marked historical section of `docs/methodology.md`;
- `tests/fixtures/tdd/five-state-characterization-v1.json` and its linked
  `tests/evidence/` records.

These historical paths are not target-domain inputs and must never be copied
into `src/web`, a release fixture, or production build output. The allowlist
permits preservation, not reuse. New exceptions require an explicit historical
label, an accepted authority, and a scanner review; broad term or directory
bypasses are prohibited.

## Commands

```bash
cd src/web
node scripts/check-target-content.mjs
npm run build
```

The build command invokes the emitted-asset scan automatically.
