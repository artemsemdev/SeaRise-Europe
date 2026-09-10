# Coastal atlas backlog scope

Reviewed against the open issue bodies on 2026-09-10. The active engineering
phase is [#490](https://github.com/artemsemdev/SeaRise-Europe/issues/490), governed
by [ADR-028](../architecture/adr/ADR-028-coastal-atlas-adoption.md). The
[earlier roadmap](README.md) and #44 preserve the static projection migration
and unfinished public delivery work. This mapping does not close issues,
change historical approvals, or authorize publication.

## Current adoption work

The main atlas uses CoCliCo SSP585, three years, and two defense assumptions.
Normal development/CI uses a labeled illustrative fixture. The same interface
can use separately provisioned data through the explicit read-only loopback
adapter. AR6/Flight remains a reference at `/projections/`, with its own
scientific contract. See the [development quickstart](../operations/coastal-atlas-development.md).

The ordered issue sequence is:

1. #491 corrects documentation; #493 preserves completed removal authority while
   allowing retained application evolution; #496 separates local evidence
   validation from live CI attestation.
2. #494 establishes the current product contract; #495 supplies strict browser
   types and compact fixture inputs.
3. #499 supplies adapters; #500 transfers map/cartography; #501 transfers the
   accepted interface and interactions against those contracts.
4. #503 preserves provisioned real-local browser regressions in a separately
   invoked suite; #502 activates the primary entry, fixture CI, and retained
   projection route.
5. Complete combined validation and documentation review, then open the final
   integration PR. Its merge to master remains the owner's explicit decision.

Issue PRs and their checks determine integration status. A prepared local build
or successful fixture test is not evidence that a slice has merged to master,
that real-local QA is complete, or that a public release is qualified.

## Existing issues: retain purpose, refresh product scope

| Issue | Disposition | Required atlas-specific update |
|---|---|---|
| [#44 — static-first roadmap](https://github.com/artemsemdev/SeaRise-Europe/issues/44) | Historical migration record and parent for remaining public delivery work. | Link #490 as the current product phase. Scope Flight, nine combinations, four ADR-024 outcomes, browser COG lookup, and no-inundation copy to the AR6 reference. Its unchecked #61 entry is stale: #61 closed on 2026-08-25. Preserve completed removal/scientific history and unfinished delivery checks. |
| [#62 — hosting](https://github.com/artemsemdev/SeaRise-Europe/issues/62) | Deferred public delivery. | Reconfirm the atlas artifact/data-serving design and storage/range budgets before provisioning. The local Python adapter is not a public hosting decision. Keep isolated environments, reviewed IaC, narrow CORS, immutable objects, and fixture-only provisioning until publication is separately authorized. |
| [#74 — platform/GitHub IaC](https://github.com/artemsemdev/SeaRise-Europe/issues/74) | Deferred provisioning; inventory and plan work remain useful. | Inventory actual surviving resources and current aggregate checks instead of assuming legacy resources still exist. Preserve protected applies, state safety, least privilege, imports, drift detection, and explicit exceptions. No source deletion implies external retirement authority. |
| [#63 — security/privacy](https://github.com/artemsemdev/SeaRise-Europe/issues/63) | Current local controls plus a later public-origin gate. | Inventory atlas basemap/worker origins and verify edition isolation, private output exclusion, and inert source text. Scope OpenFreeMap and projection service-worker checks to the reference. Search/coordinates sent to the explicit loopback adapter are functional local requests; they do not authorize telemetry or transmission to public infrastructure. Keep public headers, CORS, framing, integrity, and no-secret requirements open. |
| [#64 — promotion/rollback](https://github.com/artemsemdev/SeaRise-Europe/issues/64) | Deferred public publication gate. | Define the atlas's immutable public artifact identity and source/rights qualification before reusing workflows. Preserve exact reviewed source revisions, new protected candidates, signing, co-retention, independent readback, serialized promotion, and current/prior app-data rollback. Never publish private Candidate-v7, its TAR, or the local atlas workspace. |
| [#65 — parity/fitness](https://github.com/artemsemdev/SeaRise-Europe/issues/65) | Split local adoption evidence from the later formal public release exit. | Add six atlas combinations, valid-zero versus unknown, source inspection, full Ukraine/Crimea, constrained navigation, responsive comparison/share/retry, and provider-failure coverage. Preserve nine combinations/four outcomes as AR6 reference tests. Refresh browser/performance budgets using the actual atlas; browser-only lookup, worker-search timing, Flight parity, and projection offline behavior do not describe the local adapter. Public delivery, broader browser/manual accessibility evidence, and scientific/rights/integrity gates remain open. |
| [#66 — public evidence page](https://github.com/artemsemdev/SeaRise-Europe/issues/66) | Correct current documentation now; defer public portfolio qualification. | Label fixture, private engineering, retained projection, and promoted public evidence separately. Replace global Flight/baseline cost claims with atlas evidence when measured. Keep generated claim/link checks, explicit “not measured,” privacy, and no private artifact links. An updated architecture page alone does not close this issue. |
| [#67 — operations/budgets](https://github.com/artemsemdev/SeaRise-Europe/issues/67) | Deferred public operations. | Select probes and budgets after the atlas public delivery design is accepted. Replace AR6-only journeys and OpenFreeMap assumptions with actual atlas sources and failure modes; retain independent basemap/data availability, privacy-safe reports, dated costs, multi-region checks, incident response, and rollback exercises. |
| [#69 — production cutover](https://github.com/artemsemdev/SeaRise-Europe/issues/69) | Deferred protected production action. | Bind cutover to the approved atlas app/data pair and refreshed #63–#67/#74 evidence. Test six atlas combinations and keep AR6 checks separately scoped. Preserve stabilization, previous-pair rollback, no mixed release state, owner acceptance, and the exclusion of destructive external cleanup. |

## Gate boundaries

These public-delivery issues do not block the owner-authorized local adoption:
#490 neither provisions cloud resources nor uploads private data, and its
fixture/local contract explicitly permits the loopback adapter. Their
`gate:blocking` labels apply to the downstream publication or production action
specified by each issue. Obsolete main-product acceptance criteria need reviewed
scope changes, not blanket waivers or deletion of tests.

Local adoption still requires a reproducible fixture build, actual primary-app
CI, explicit edition selection with no fixture fallback in real-local mode,
private-data isolation, honest failures and source labels, and provisioned local
regression evidence. The projection service worker must not cache the atlas
root or private data. Security controls used by these workflows remain active.

The historical binary method's no-go remains a no-go. The approved AR6 recovery
remains approval for its exact regional projection contract; it does not approve
CoCliCo inundation or remove future rights, acquisition-reproducibility, source
validation, provenance, and publication obligations. Public atlas delivery needs
its own reviewed data-distribution contract before #62/#64 can produce release
evidence. No issue should be mass-closed or scientific receipt rewritten to
make the backlog appear complete.

## Minimal issue maintenance

The current-scope notice has been added to #44, and #63/#65 now distinguish
atlas acceptance criteria from retained public-release requirements. Keep
#490's child links/checkmarks and current criteria aligned with merged PR and
validation evidence. Preserve the original issue bodies as historical context.
Refresh #62/#74, #64, #66/#67, and #69 when public delivery design and authorization
make their next actions concrete. This avoids duplicating useful unfinished
work in a second permanent backlog.
