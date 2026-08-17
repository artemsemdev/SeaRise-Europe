# Issue 60 Flight capability design QA

The active visual authority is
[`docs/product/Mock/SeaRise-Flight.html`](../../../product/Mock/SeaRise-Flight.html),
SHA-256 `2f39c5f4d9d1050df7613999bc205bd08086cd689deefed730db3515a5d0b00f`.

## Reviewed states

| Viewport | Canonical mock | Production implementation |
| --- | --- | --- |
| 1440 × 900 | [capture](mock-desktop-1440x900.png) | [capture](implementation-desktop-1440x900.png) |
| 375 × 812 | [capture](mock-mobile-375x812.png) | [capture](implementation-mobile-375x812.png) |

The four comparison captures use identical viewport dimensions and reduced
motion, without resizing either authority. They are not identical application
states: the canonical mock contains its authored demo/fixture and release copy,
while the production capture reports the committed synthetic release contract.
The production `Methodology` and `Fly` controls can also be disabled until the
verified methodology/search state is ready; the self-contained mock presents
its controls immediately. These intentional runtime differences are reviewed
as content/state differences, not treated as pixel mismatches or hidden from
the comparison.

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

Capture reproduction from `src/web`, while `npm run serve` is running:

```text
node -e 'const {chromium}=require("playwright"); const path=require("path"); (async()=>{const b=await chromium.launch(); for(const [n,w,h] of [["desktop-1440x900",1440,900],["mobile-375x812",375,812]]) for(const [kind,url] of [["mock","file://"+path.resolve("../../docs/product/Mock/SeaRise-Flight.html")],["implementation","http://127.0.0.1:4173/"]]){const p=await b.newPage({viewport:{width:w,height:h},reducedMotion:"reduce"}); await p.goto(url); await p.screenshot({path:`../../docs/evidence/phase-2/issue-60-flight-capability/${kind}-${n}.png`}); await p.close();} await b.close();})()'
```

Results: lint and contract scans passed; TypeScript passed; 699 unit and
integration tests passed; production build inspection passed; focused
Playwright passed for root worker identity on desktop Chromium and the 375 px
runtime state on mobile Chromium (the opposite project/viewport combinations
are intentionally skipped).

The coordinator remains conservative: it can expose a non-current candidate
only when the waiting worker reports its exact embedded pair and precache hash
and the pair lifecycle store contains matching complete resource-plan and
receipt authority. The durable transition port uses cross-tab Web Locks and
exact conditional local storage records. Missing or mixed evidence fails
closed without creating a pending or armed intent. It never reloads the page,
activates a worker, or invents a candidate.
