# Issue #59 content review evidence

> **Date:** 2026-08-16
>
> **Review basis:** `agent/issue-59-content-review` from integration commit
> `3eb4d2a9bba5a7ddddbed58e886d71a73305d8c5`
>
> **Authorities:** PRD, Content Guidelines, ADR-024, and the pinned release
> contracts
>
> **Disposition reviewed:** committed synthetic fixture only

## Conclusion

The static target passes the Phase 2 scientific-content review after correcting
the landing/search/release-disposition copy. The target uses exactly the four
ADR-024 scientific outcomes. Delivery, integrity, browser-capability, search,
and other technical failures remain outside that domain.

## Owner correction: Flight design authority

The owner subsequently confirmed that `SeaRise-Flight.html` is the active
canonical visual and interaction reference. It preserves the required layout,
information hierarchy, map-first composition, controls, responsive behavior,
and interaction character. This supersedes only this review's earlier
historical-only classification; it does not change the scientific-content
findings.

The mock's invalid science is handled by an explicit anti-corruption map:
`exposed` and `notexposed` become `ProjectionAvailable`; `unavailable` becomes
`DataUnavailable`; `outofscope` becomes `OutOfScope`; and the missing
`UnsupportedGeography` state must be added. Technical errors remain separate.
Binary exposure, terrain comparison, modeled-water/flood meaning, and property
or hazard claims remain prohibited.

This is source, rendered-DOM contract, and emitted-asset evidence. It does not
replace the separate Playwright journey evidence or manual VoiceOver review,
and it does not approve a public scientific release.

## Reviewed surfaces

- landing, release bootstrap, release status, search, sharing, and application
  alerts in `src/web/src/App.tsx`, `src/web/src/release-copy.ts`, and
  `src/web/src/components/SettlementSearch.tsx`;
- all result, transient, degraded, and technical states in
  `src/web/src/components/ProjectionPanel.tsx` and
  `src/web/src/domain/projection-state.ts`;
- source, method, integrity, limitation, and disposition disclosure in
  `src/web/src/components/MethodologyDialog.tsx`;
- visual-only map semantics and text alternatives in
  `src/web/src/components/map/MapExplorer.tsx` and `MapSurface.tsx`;
- architecture claims in `src/web/src/routes/ArchitecturePage.tsx`;
- the PRD, Content Guidelines, ADR-024, current release methodology, and the
  committed browser release manifest;
- component, domain, golden, content-scan, and existing browser tests linked in
  `tests/test-inventory.json`.

## State and outcome audit

| State | Required meaning and reviewed presentation | Result |
|---|---|---|
| Booting / release loading | Says the pinned release is being validated; no outcome is shown before verification. | Pass |
| Ready | Prompts for a settlement or point without implying an assessment already exists. | Pass |
| Searching | Describes local/in-browser search and separates no-match from an index failure. | Pass |
| Evaluating | Says the selected point is being checked against selected data. | Pass |
| Updating | Names the new exact selection and labels the visible result as the previous accepted result. | Pass |
| Offline | Identifies uncached selected data, requests reconnection, and states that no outcome was produced. | Pass |
| Connection required | Identifies missing immutable data and promises no substitution. | Pass |
| Unsupported browser | Uses a technical capability failure, never a scientific result. | Pass |
| Integrity failure | Hides unverified output and identifies a release-integrity failure. | Pass |
| General technical failure | Explicitly says it is not `DataUnavailable`; a previous accepted result remains separately labelled when present. | Pass |
| `ProjectionAvailable` | Reports regional relative sea-level change rather than hazard, exposure, or property risk. | Pass |
| `DataUnavailable` | Distinguishes source nodata from nearest-grid distance beyond the inclusive 100 km limit; never means zero or no risk and never substitutes another tuple. | Pass |
| `OutOfScope` | Means inside supported Europe but outside the versioned coastal analysis area; explicitly does not imply absence of hazards. | Pass |
| `UnsupportedGeography` | Means outside the versioned Europe support geometry and is described as a normal outcome, not an application error. | Pass |

The trusted methodology array is exactly, and in order,
`ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, and
`UnsupportedGeography`. Exhaustive TypeScript unions and reducer/component
tests reject a fifth scientific outcome. Technical errors use their own typed
state and presentation.

## `ProjectionAvailable` disclosure

| Required information | Static target evidence |
|---|---|
| Exact SSP and absolute horizon | Scenario label plus exact `ssp1-26`, `ssp2-45`, or `ssp5-85` ID, and `2030`, `2050`, or `2100` controls/result text. |
| Three quantiles and units | Median q0.5 and q0.167–q0.833 likely range are rendered in metres. |
| Baseline | The pinned `1995-2014 mean` is rendered beside the value. |
| Exact lookup identity | Source-grid latitude/longitude, distance in km, and native 1° resolution are rendered. |
| Method and release identity | Methodology version, data release ID, and AR6 source release are rendered. |
| Source and licence | Dataset title/link, attribution, licence name, SPDX ID, and licence link are rendered from verified release artifacts. |
| Limitations and disclaimer | Release limitations and the complete informational-use disclaimer appear with every completed outcome. |

The methodology surface additionally states the inclusive 100 km limit,
nearest native source-grid operator, required q0.167/q0.5/q0.833 bands, and the
prohibition on interpolation, extrapolation, nodata substitution, and
tide-gauge fallback. It identifies PMTiles as visual context only.

## Map meaning and non-colour access

Every scientific outcome has an outcome-specific textual map meaning. The map
surface identifies the exact scenario, absolute horizon, named quantile band,
artifact, source-grid convention, and selected coordinates in text. It states
that values come from the analysis artifact rather than colour or rendered
pixels. The result panel remains independent of the lazy map renderer, and map
or basemap failure preserves the text alternative. No scientific meaning is
encoded by colour alone.

## Claim and release-disposition review

Production source and emitted assets are mutation-scanned for legacy outcome
names, binary/five-state exposure, terrain comparison, flooding or risk
certainty, property claims, relative `+N years` horizons, forecast-model
framing, and unsupported coverage, precision, cost, or offline promises.
Active documentation is scanned for legacy target-domain claims. Superseded
material is retained only behind the explicit historical-evidence allowlist.
The active Flight mock has a separate fail-closed annotation that preserves its
design authority while mapping and rejecting its obsolete scientific content.

The committed clean-clone release is
`searise-europe-v1.0.0-20260810-c096aeab4e09`, with
`dataProvenanceClass: synthetic-fixture`, automated validation `passed`, owner
disposition `pending-owner`, and required status disclosure. The landing,
result, methodology, and architecture surfaces call it synthetic demonstration
data and make no public-release claim. Private-engineering copy says local
validation only and not verified, public, signed, or approved. Public-promoted
copy is reachable only through a validated public-promoted release context.

Candidate-v7, its TAR, and any local-only inputs were not read, copied,
modified, built, or published by this review.

## Corrections made

- `488d626a75d9d665cc582c024a0ee3759d491467`: aligned the approved landing
  heading/search placeholder and made landing and architecture status copy
  depend on the verified release disposition.
- `96a8c31bfa61292c6d815b37114931f34c4aaad3`: expanded the fail-closed
  content scanner and mutation controls, documented its two scan layers, and
  added permanent test-inventory ownership.
- `bf07abd28675553b929b6dab688b7e08edc4868a`: aligned no-match guidance and
  corrected the PRD's static-runtime status. Its historical-only Flight
  classification was later superseded by the explicit owner correction above.

## Reproducible validation

Run from the repository root with the pinned Node/npm versions:

```bash
npm ci
node src/web/scripts/check-target-content.mjs
npm run web:check
python3 scripts/tests/validate_test_inventory.py
python3 scripts/tests/changed_suites.py --base-ref 3eb4d2a9bba5a7ddddbed58e886d71a73305d8c5
git diff --check 3eb4d2a9bba5a7ddddbed58e886d71a73305d8c5...HEAD
```

Observed locally on 2026-08-16: the focused scan accepted 105 source and active
documentation files; lint and type-check passed; all 295 deterministic tests in
25 files passed; the production static build passed; the emitted-asset scan
accepted 21 files; build inspection validated 106 static files and 32 measured
assets; and all 66 inventoried suites validated. Changed-suite selection also
passed after the evidence commit. Browser E2E and manual VoiceOver results
remain owned by their separate issue #59 evidence records.
