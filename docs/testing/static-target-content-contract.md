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

Historical terminology is never exempted by directory. Before owner approval,
the scanner reads
`contracts/repository-removal/v1/historical-allowlist.preapproval.json`; after
approval it automatically prefers `historical-allowlist.json`. Each entry must
bind one exact repository path to its Git blob SHA and one constrained rule.
The scanner recalculates the blob ID from committed bytes and rejects changed,
duplicated, active-runtime, or rule/path-mismatched entries.

The preapproval document is evidence classification only. It does not approve
deletion, publication, or an inventory disposition. The final repository-
removal validator remains the authority for the owner-approved hash chain.
Neither document can allow historical terminology in `src/web` or the active
pipeline. The separately marked historical section of `docs/methodology.md`
continues to use its narrow in-file boundary.

ADR-024 remains active authoritative policy, never historical evidence. Its
two obsolete outcome identifiers are accepted only inside the exact sentence
that says they do not appear in an ADR-024 release. The allowlist validator also
understands the schema's exact `canonical-design-reference` rule for
`docs/product/Mock/SeaRise-Flight.html`; that rule preserves design authority
but cannot place the mock in built output.

## Runtime and dependency gates

`static-repository-gates.mjs` rejects legacy application dependencies from
three scopes:

- target source rejects Next.js, .NET/C#/NuGet, PostgreSQL/PostGIS/Npgsql,
  TiTiler, Azurite, runtime Azure geocoding, legacy Compose services, and a Node
  production server;
- emitted output applies the same rules without any tooling exception;
- repository readiness scans every tracked executable/configuration file and
  classifies exact pending-removal roots separately from retained test/build
  tooling, deterministic pipeline code, build-plane containers, and immutable
  v1 supply-chain evidence.

Readiness classification is not removal approval. `--repository-final` changes
every remaining pending-removal reference into a failure and also rejects any
unclassified reference. It is the Phase 2 final clean-repository gate.

Static-output isolation independently rejects both unversioned and `/v1/`
forms of `/assess`, `/geocode`, and `/config`. Only exact
`/releases/<dataReleaseId>/config/*.json` references named by the loaded release
manifest are allowed.

## Commands

```bash
cd src/web
node scripts/check-target-content.mjs
node scripts/static-repository-gates.mjs --target
node scripts/static-repository-gates.mjs --repository-readiness
npm run build
# Run only after approved Phase 2 removal is complete:
node scripts/static-repository-gates.mjs --repository-final
```

The build command invokes the emitted-asset scan automatically.
