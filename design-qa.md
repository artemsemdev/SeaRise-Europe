# SeaRise Flight design QA

## Contract

- Canonical source: `docs/product/Mock/SeaRise-Flight.html`
- Target: the production static browser application in `src/web`
- Contract rule: match the mock's map-first layout, hierarchy, typography,
  responsive composition, and Flight interaction. ADR-024 remains authoritative
  for scientific meaning, so the target must not reproduce the mock's historical
  binary-exposure, terrain, flooding, or property-risk language.

## Comparison method

The source and production build were opened in Chrome with the same explicit
viewport and device pixel ratio. Each source/implementation pair was combined
into one side-by-side image before review.

| State | Viewport | Source | Implementation | Combined comparison |
| --- | --- | --- | --- | --- |
| Landing | 1440 × 900, DPR 1 | `docs/evidence/phase-2/issue-59-design-qa/source-desktop-landing.jpg` | `docs/evidence/phase-2/issue-59-design-qa/implementation-desktop-landing.jpg` | `docs/evidence/phase-2/issue-59-design-qa/comparison-desktop-landing.png` |
| Landing | 390 × 844, DPR 1 | `docs/evidence/phase-2/issue-59-design-qa/source-mobile-landing.jpg` | `docs/evidence/phase-2/issue-59-design-qa/implementation-mobile-landing.jpg` | `docs/evidence/phase-2/issue-59-design-qa/comparison-mobile-landing.png` |
| Result | 1440 × 900, DPR 1 | `docs/evidence/phase-2/issue-59-design-qa/source-desktop-result.jpg` | `docs/evidence/phase-2/issue-59-design-qa/implementation-desktop-result.jpg` | `docs/evidence/phase-2/issue-59-design-qa/comparison-desktop-result.png` |

The landing-region geometry was also measured in Chrome. At 390 × 844 the
source and implementation differ by less than one CSS pixel for the heading,
introductory copy, search shell, and privacy/index note boundaries.

## Interaction checks

- Settlement search, keyboard result navigation, selection, Flight transition,
  progress state, scientific result, scenario/horizon changes, replay/reset,
  methodology dialog, share/reload, reduced motion, and technical failures were
  exercised through the production build.
- The result comparison verifies the same map-first floating-panel composition.
  The target intentionally replaces the mock's prohibited exposure result with
  the four-outcome ADR-024 projection contract.
- Desktop, mobile, and reduced-motion Playwright projects cover the complete
  interaction rather than treating screenshots as functional evidence.
- Chrome reported no console errors in the final compared implementation state.

## Findings and corrections

- Removed the unrelated document/dashboard composition from the primary journey.
- Restored the full-viewport Flight shell, overview terrain silhouette, graticule,
  centered search command, floating result card, and responsive header order.
- Matched the canonical heading, introductory copy, settlement examples, control
  dimensions, privacy/index note, typography, spacing, and mobile composition.
- Kept map rendering and scientific output separate: the map is visual context;
  exact nearest-native-grid COG reads remain the sole projection source.
- Preserved accessibility improvements that do not change the visual contract,
  including distinct live regions, deterministic focus transitions, fieldset
  grouping, keyboard operation, and reduced-motion behavior.

Final result: passed
