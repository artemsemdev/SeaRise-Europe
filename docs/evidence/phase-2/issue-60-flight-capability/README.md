# Issue 60 Flight capability design QA

The active visual authority is
[`docs/product/Mock/SeaRise-Flight.html`](../../../product/Mock/SeaRise-Flight.html),
SHA-256 `2f39c5f4d9d1050df7613999bc205bd08086cd689deefed730db3515a5d0b00f`.

## Reviewed states

- `desktop-offline-assessment.png` — production static build at 1440 × 900,
  after the real browser runtime completed the Málaga assessment and derived
  `available-offline` from accepted resources.
- `mobile-375-offline-assessment.png` — the same production runtime path at
  375 × 812. The approved subject label remains intact, the mock-derived mint
  translucent badge and status dot are visible, and the header does not
  overflow.
- Update states are rendered by the same `FlightCapabilityAlerts` React path.
  Unit integration coverage drives `update-available`, `installing`,
  `ready-to-activate`, `activation-blocked`, and `failed`; the production
  runtime wiring test proves coordinator inspection and action dispatch reach
  that controller. No browser test manufactures alert DOM.

## Verification

```text
npm run lint
npm run type-check
npm run test -- --run
npm run build
npx playwright test tests/static-shell.spec.ts --grep "375px Flight renders"
```

Results: lint and contract scans passed; TypeScript passed; 681 unit and
integration tests passed; production build inspection passed; focused
Playwright passed on mobile Chromium (the desktop project is intentionally
skipped by this viewport-specific case).

The coordinator remains conservative: it can expose a non-current candidate
only when the production resource router supplies exact candidate evidence.
It never reloads the page, activates a worker, or invents a candidate.
