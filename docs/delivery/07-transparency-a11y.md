# Epic 07 — Transparency, Accessibility, and Content Compliance

| Field            | Value                                                                                |
| ---------------- | ------------------------------------------------------------------------------------ |
| Epic ID          | E-07                                                                                 |
| Phase            | 1                                                                                    |
| Status           | Not Started                                                                          |
| Effort           | ~5 days                                                                              |
| Dependencies     | Epic 06 (result panel, all 5 states, controls exist)                                 |
| Stories          | 7 (S07-01 through S07-07)                                                            |

---

## 1  Objective

Implement the MethodologyPanel for scientific transparency, externalize all UI copy for localization readiness, audit all content against CONTENT_GUIDELINES, and bring the application to WCAG 2.2 AA compliance across all breakpoints.

---

## 2  Why This Epic Exists

This epic addresses two foundational product pillars: Scientific Honesty and Accessibility. The application presents sea-level exposure assessments that users may interpret as predictions. Without a transparent methodology panel, clear disclaimers, and carefully audited copy, users could misinterpret results or form false confidence. Without WCAG 2.2 AA compliance, the application excludes users who rely on keyboard navigation, screen readers, or high-contrast displays. Both obligations are non-negotiable for a responsible public-facing tool. Deferring either increases legal exposure and undermines product credibility.

---

## 3  Scope

### 3.1 In Scope

- MethodologyPanel implementation (drawer/modal, dynamic import, API-driven content, focus management).
- Content copy audit against CONTENT_GUIDELINES sections 3 through 9.
- Prohibited language scan across all UI strings.
- i18n externalization verification (all copy in `lib/i18n/en.ts`, zero hardcoded strings).
- Full keyboard navigation flow with correct Tab order and arrow key support.
- ARIA attributes on all interactive and live regions.
- Responsive layout validation at desktop, tablet, and mobile breakpoints.
- Automated and manual accessibility audit (axe-core, keyboard walkthrough, VoiceOver, color contrast).

### 3.2 Out of Scope

- Adding additional languages beyond English (English-only MVP per BR-017).
- Custom accessibility themes or user-configurable font sizes.
- Resolution of OQ-12 (tablet/mobile parity for advanced interactions).
- Result panel implementation (completed in Epic 06).
- Backend API changes (methodology endpoint already specified in Epic 04).

---

## 4  Blocking Open Questions

No blocking open questions. All prerequisites are resolved by upstream epics. OQ-12 (tablet/mobile interaction parity) remains unresolved but does not block this epic; responsive layout validation in S07-06 documents any gaps for future resolution.

---

## 5  Traceability

### 5.1 Product Requirement Traceability

| Requirement | Description                                                      |
| ----------- | ---------------------------------------------------------------- |
| FR-024      | Disclaimer visible on every result                               |
| FR-032      | Methodology entry point button                                   |
| FR-033      | Methodology panel with all required elements                     |
| FR-034      | Source attribution                                               |
| FR-035      | Methodology version in response and UI                           |
| BR-010      | Result state copy exactly matches taxonomy                       |
| BR-015      | Methodology version always present                               |
| BR-017      | English-only MVP                                                 |
| NFR-010     | No blank/broken UI                                               |
| NFR-015     | WCAG 2.2 AA                                                      |
| NFR-016     | Non-color-dependent communication                                |
| NFR-018     | Copy externalized for localization                               |

### 5.2 Content Guidelines Traceability

| Section | Requirement                                                      |
| ------- | ---------------------------------------------------------------- |
| CG-3    | Result state copy templates (one per state)                      |
| CG-4    | Disclaimer text (exact wording, visible on every result)         |
| CG-5    | Methodology panel content requirements                           |
| CG-6    | Empty state copy                                                 |
| CG-7    | Loading state copy (neutral tone, no false encouragement)        |
| CG-8    | Error state copy                                                 |
| CG-9    | Prohibited language list (must never appear in any UI string)    |

### 5.3 Architecture Traceability

| Architecture Document                              | Relevance                                           |
| -------------------------------------------------- | --------------------------------------------------- |
| `docs/architecture/03a-frontend-architecture.md`   | MethodologyPanel spec, ARIA roles, keyboard flow, responsive layout |
| `docs/architecture/06-api-and-contracts.md`        | GET /v1/config/methodology endpoint                 |
| `docs/architecture/03-component-view.md`           | Component responsibilities                          |
| `docs/product/CONTENT_GUIDELINES.md`               | All copy requirements, prohibited language           |

---

## 6  Implementation Plan

Work through stories in the following recommended order. The execution order map below shows dependencies and parallelization opportunities.

```
S07-01 (Methodology Panel)
  |
  +-----> S07-02 (Content Copy Audit)
            |
            +-----> S07-03 (i18n Externalization)   <-- can start after S07-02
            |
            +-----> S07-04 (Keyboard Navigation)    <-- independent of S07-03
                      |
                      +-----> S07-05 (ARIA + Focus)
                                |
                                +-----> S07-06 (Responsive)
                                          |
                                          +-----> S07-07 (A11y Audit)
```

**Ordering rationale.** S07-01 must come first because the MethodologyPanel introduces the most significant new UI surface and its copy feeds into the content audit. S07-02 follows immediately to ensure all UI strings (including the new panel content) are correct before externalization verification. S07-03 (i18n) and S07-04 (keyboard navigation) are independent of each other and can run in parallel once S07-02 is complete; S07-03 validates string externalization while S07-04 establishes the keyboard flow. S07-05 (ARIA) depends on S07-04 because correct ARIA attributes require the keyboard interaction model to be finalized. S07-06 (responsive) follows S07-05 because layout validation should cover the accessible state of all components. S07-07 (audit) is last by design: it is a comprehensive verification pass that must run against the finished, fully accessible UI.

---

## 7  User Stories

---

### S07-01 — Implement MethodologyPanel

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-01                 |
| Type           | Feature                |
| Effort         | ~1 day                 |
| Dependencies   | Epic 06 complete       |

**Statement**

As a user viewing an exposure result, I want to open a methodology panel that explains how the assessment was produced, so that I can understand the scientific basis and limitations of the result before acting on it.

**Why**

The methodology panel is the primary mechanism for scientific transparency. FR-033 requires it to contain the methodology version, projection source, elevation source, plain-language explanation, explicit limitations list, dataset resolution note, and per-state interpretation guidance. Without this panel, users have no way to evaluate the credibility or boundaries of the assessment they are viewing.

**Scope Notes**

- Implement as a drawer on desktop (right side or modal) and a full-screen bottom sheet on mobile.
- Dynamically import the component (deferred until first open via React `lazy` or Next.js dynamic import).
- Fetch content from `GET /v1/config/methodology` using TanStack Query with session-level caching (`staleTime: Infinity`).
- Render all required elements per FR-033 and CONTENT_GUIDELINES section 5:
  - Methodology version identifier.
  - Sea-level projection source (name, provider, URL as a link).
  - Elevation source (name, provider).
  - Plain-language description of what the methodology does (2-4 sentences).
  - Explicit list of what the methodology does NOT account for.
  - Dataset resolution note.
  - Interpretation guidance per result state.
- Set `role="dialog"`, `aria-modal="true"`, implement focus trap while open.
- On close: return focus to the MethodologyEntryPoint button.
- Entry point: MethodologyEntryPoint button visible when a result is displayed.

**Traceability**

- Requirements: FR-032, FR-033, FR-034, FR-035, BR-015
- Content Guidelines: CG-5
- Architecture: `docs/architecture/03a-frontend-architecture.md` (MethodologyPanel specification)

**Implementation Notes**

- Use `@headlessui/react` Dialog or equivalent for the focus trap and modal behavior; avoid building a custom trap.
- The TanStack Query key should be stable (e.g., `["methodology"]`) so the response is fetched once and reused across opens.
- Methodology content comes from the API, not hardcoded in the frontend. This ensures the methodology version displayed always matches the version used to produce the current assessment.
- Test that dynamic import does not contribute to the initial bundle size.

**Acceptance Criteria**

1. MethodologyEntryPoint button is visible when a result is displayed.
2. Clicking the button opens the MethodologyPanel.
3. Panel displays all FR-033 required elements: methodology version, projection source with link, elevation source, plain-language description, limitations list, resolution note, and per-state interpretation guidance.
4. Panel content is fetched from `GET /v1/config/methodology` and cached for the session.
5. Panel has `role="dialog"` and `aria-modal="true"`.
6. Focus is trapped within the panel while it is open.
7. Closing the panel returns focus to the MethodologyEntryPoint button.
8. Panel is dynamically imported; it does not appear in the initial JavaScript bundle.
9. Desktop renders as a drawer or modal; mobile renders as a full-screen bottom sheet.

**Definition of Done**

- MethodologyPanel component implemented with all required elements.
- Dynamic import verified (bundle analysis or network tab inspection).
- Focus trap and focus return behavior verified manually.
- API integration tested with mock and live endpoints.

**Testing Approach**

- Unit test: panel renders all required content sections from a mocked API response.
- Unit test: panel does not render when methodology data is loading or errored (graceful fallback).
- Integration test: TanStack Query caching — panel opens twice without a second network request.
- Manual test: focus trap (Tab does not escape panel), focus return (close returns to trigger button).
- Bundle test: dynamic import confirmed via build output or bundle analyzer.

**Evidence Required**

- Unit and integration test output.
- Screenshot or recording of focus trap behavior.
- Bundle analysis showing MethodologyPanel chunk is separate from the main bundle.

---

### S07-02 — Content Copy Audit and CONTENT_GUIDELINES Compliance

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-02                 |
| Type           | Quality Assurance      |
| Effort         | ~0.5 days              |
| Dependencies   | S07-01                 |

**Statement**

As the engineer maintaining delivery quality, I want every UI string audited against CONTENT_GUIDELINES sections 3 through 9, so that the application never displays prohibited language, scientifically inaccurate copy, or copy that deviates from the approved templates.

**Why**

The application communicates scientific assessments to non-expert users. A single instance of prohibited language (e.g., "will flood", "safe", "guaranteed") could create a false impression of certainty or safety. CONTENT_GUIDELINES defines exact templates for result states, disclaimers, empty states, loading states, and error states. Deviation from these templates introduces liability and undermines the product's scientific integrity.

**Scope Notes**

- Audit every string in `lib/i18n/en.ts` against the prohibited language list (CG-9): "will flood", "will be underwater", "safe", "danger", "risk-free", "guaranteed", "certain", "definite", "proven", "absolute", "100%", "no risk", "threat level".
- Verify result state copy in `en.ts` matches CG-3 templates exactly (one template per state).
- Verify disclaimer text matches CG-4 exact wording.
- Verify empty state copy matches CG-6.
- Verify loading state copy matches CG-7 (neutral, no "almost there!" or similar).
- Verify error state copy matches CG-8.
- Verify methodology panel API response content aligns with CG-5 requirements.
- Document any deviations found and fix them in the same story.

**Traceability**

- Requirements: FR-024, BR-010, NFR-010
- Content Guidelines: CG-3, CG-4, CG-5, CG-6, CG-7, CG-8, CG-9
- Architecture: `docs/product/CONTENT_GUIDELINES.md`

**Implementation Notes**

- Write a script or test that programmatically scans `en.ts` for every prohibited term (case-insensitive substring match).
- This script becomes a permanent CI gate (run in the lint step) to prevent future regressions.
- For template matching (CG-3, CG-4), use exact string comparison, not fuzzy matching.

**Acceptance Criteria**

1. Every string in `lib/i18n/en.ts` passes the prohibited language scan with zero matches.
2. Result state copy matches CG-3 templates exactly.
3. Disclaimer text matches CG-4 exact wording.
4. Empty state copy matches CG-6.
5. Loading state copy matches CG-7 (neutral tone confirmed).
6. Error state copy matches CG-8.
7. A prohibited-language lint script exists and runs in CI.
8. All deviations found during the audit are corrected.

**Definition of Done**

- All UI strings reviewed and corrected.
- Prohibited-language lint script committed and integrated into CI.
- Audit results documented (list of strings checked, deviations found, corrections made).

**Testing Approach**

- Automated test: prohibited-language scanner runs against `en.ts` with zero violations.
- Manual review: side-by-side comparison of each state's copy against CONTENT_GUIDELINES templates.

**Evidence Required**

- Prohibited-language scanner output (zero violations).
- Audit log documenting strings reviewed, deviations found, and corrections applied.

---

### S07-03 — Complete i18n Externalization

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-03                 |
| Type           | Technical Enabler      |
| Effort         | ~0.5 days              |
| Dependencies   | S07-02                 |

**Statement**

As the engineer maintaining delivery quality, I want to verify that zero UI strings are hardcoded in components and that all copy originates from `lib/i18n/en.ts` or the methodology API, so that adding a new language requires only a new locale file and a selector, with no code changes.

**Why**

NFR-018 requires all copy to be externalized for localization. The MVP ships English-only (BR-017), but the architecture must support adding languages without modifying component code. Any hardcoded string discovered after launch becomes a localization blocker that requires a code change, a rebuild, and a redeployment for every new language.

**Scope Notes**

- Scan all React component files (`.tsx`, `.ts` in component directories) for hardcoded user-visible strings.
- Verify every user-facing string references a key from `lib/i18n/en.ts`.
- Verify that methodology panel content comes from the API response (already externalized server-side).
- Verify that ARIA labels, `alt` text, `title` attributes, and `placeholder` text are also externalized.
- Confirm that adding a hypothetical `fr.ts` file alongside `en.ts` requires no component changes.

**Traceability**

- Requirements: NFR-018, BR-017
- Architecture: `docs/architecture/03a-frontend-architecture.md` (i18n approach)

**Implementation Notes**

- Write a grep-based or AST-based lint rule that flags string literals inside JSX that are not wrapped in a translation function call.
- Exclude non-user-facing strings (CSS class names, data-testid values, object keys) from the scan.
- The lint rule should run in CI to prevent future regressions.

**Acceptance Criteria**

1. Zero hardcoded user-visible strings exist in any component file.
2. All user-facing strings reference keys in `lib/i18n/en.ts`.
3. ARIA labels, alt text, title attributes, and placeholders are externalized.
4. A lint rule or automated scan enforces externalization and runs in CI.
5. Adding a new locale file (e.g., `fr.ts`) with the same key structure works without component modifications (documented or demonstrated).

**Definition of Done**

- All hardcoded strings replaced with i18n key references.
- Lint rule committed and integrated into CI.
- Verification documented.

**Testing Approach**

- Automated scan: lint rule flags zero violations across all component files.
- Manual verification: duplicate `en.ts` as `test-locale.ts` with modified values, confirm all UI strings change (local verification, not committed).

**Evidence Required**

- Lint rule output (zero violations).
- Documentation confirming the locale-addition path requires no code changes.

---

### S07-04 — Keyboard Navigation and Focus Management

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-04                 |
| Type           | Accessibility          |
| Effort         | ~1 day                 |
| Dependencies   | S07-02                 |

**Statement**

As a keyboard-only user, I want to navigate the entire application using Tab, Shift+Tab, arrow keys, Enter, and Escape, so that I can perform every core flow without a mouse.

**Why**

WCAG 2.2 AA (NFR-015) requires all functionality to be operable via keyboard. The architecture document specifies an explicit Tab order: SearchBar, CandidateList, ScenarioControl, HorizonControl, MethodologyEntryPoint, ResetButton. Focus must be managed programmatically when panels open and close. Without correct keyboard support, the application fails WCAG 2.1.1 (Keyboard) and 2.4.3 (Focus Order).

**Scope Notes**

- Implement the full Tab order: SearchBar, CandidateList (when visible), ScenarioControl, HorizonControl, MethodologyEntryPoint, ResetButton.
- Arrow key navigation within ScenarioControl and HorizonControl (radio group pattern or equivalent).
- Arrow key navigation within CandidateList (Up/Down to move between options, Enter to select).
- When CandidateList appears: focus moves to the first candidate.
- When MethodologyPanel opens: focus moves to panel heading (handled in S07-01, verified here).
- When MethodologyPanel closes: focus returns to MethodologyEntryPoint (handled in S07-01, verified here).
- Escape key closes MethodologyPanel and CandidateList.
- Skip-to-content link for screen reader users.

**Traceability**

- Requirements: NFR-015 (WCAG 2.2 AA)
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 8 (keyboard flow, focus management)

**Implementation Notes**

- Use `tabIndex` attributes sparingly. Prefer semantic HTML elements (`button`, `input`, `select`) that are naturally focusable.
- For ScenarioControl and HorizonControl, implement the WAI-ARIA radio group pattern: Tab moves focus into the group, arrow keys move between options, Space/Enter selects.
- For CandidateList, implement the WAI-ARIA listbox pattern: `role="listbox"` on the container, `role="option"` on each item, `aria-activedescendant` to track the visually focused option.
- Use `useRef` and `focus()` calls for programmatic focus management on panel open/close and candidate list appearance.

**Acceptance Criteria**

1. Tab order follows the specified sequence: SearchBar, CandidateList (when visible), ScenarioControl, HorizonControl, MethodologyEntryPoint, ResetButton.
2. Arrow keys navigate options within ScenarioControl, HorizonControl, and CandidateList.
3. Enter selects the currently focused candidate in CandidateList.
4. Escape closes CandidateList and MethodologyPanel.
5. Focus moves to the first candidate when CandidateList appears.
6. Focus is trapped in MethodologyPanel while it is open.
7. Focus returns to MethodologyEntryPoint when MethodologyPanel closes.
8. A skip-to-content link is present and functional.
9. No keyboard trap exists anywhere in the application (except the intentional MethodologyPanel focus trap).

**Definition of Done**

- Keyboard navigation implemented for all interactive elements.
- Focus management verified for all panel open/close transitions.
- No keyboard traps outside of modal dialogs.

**Testing Approach**

- Manual keyboard walkthrough: complete the full search-to-result flow using only keyboard.
- Playwright test: Tab sequence verification (focus moves through expected elements in order).
- Playwright test: Escape key closes open panels.
- Playwright test: Enter key selects a candidate and triggers assessment.

**Evidence Required**

- Playwright test output (all keyboard navigation tests pass).
- Manual keyboard walkthrough recording or checklist confirming all flows are completable.

---

### S07-05 — ARIA Attributes and Screen Reader Support

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-05                 |
| Type           | Accessibility          |
| Effort         | ~0.5 days              |
| Dependencies   | S07-04                 |

**Statement**

As a screen reader user, I want all interactive elements, live regions, and state changes to be announced correctly, so that I can understand the application's current state and operate it without visual feedback.

**Why**

WCAG 2.2 AA requires assistive technology compatibility. The architecture document specifies exact ARIA roles and attributes for every major component. Without correct ARIA markup, screen readers cannot convey the search interface semantics, result state changes, loading transitions, or error conditions to non-sighted users.

**Scope Notes**

- Apply all ARIA roles specified in the architecture document section 8:
  - SearchBar container: `role="search"`.
  - CandidateList: `role="listbox"`.
  - Each candidate: `role="option"`.
  - MethodologyPanel: `role="dialog"`, `aria-modal="true"` (implemented in S07-01, verified here).
  - Result region: `aria-live="polite"` for result state updates.
  - Loading indicator: `aria-busy="true"` on the result region while loading.
  - Error messages: `role="alert"`.
  - Map container: `role="img"` with dynamic `aria-label` reflecting current state.
- Ensure `aria-activedescendant` is set correctly on the SearchBar when navigating CandidateList.
- Ensure result state changes trigger screen reader announcements via `aria-live`.

**Traceability**

- Requirements: NFR-015 (WCAG 2.2 AA), NFR-016 (non-color-dependent communication)
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 8

**Implementation Notes**

- Use `aria-live="polite"` for result updates so announcements do not interrupt the user's current action.
- Use `role="alert"` for errors so they are announced immediately.
- The map `aria-label` should be dynamic: update it when the result state changes (e.g., "Map showing exposure assessment for Amsterdam under SSP2-4.5 at 2050").
- Use `aria-busy="true"` on the result container during loading to signal that content is being refreshed.
- Test with VoiceOver (macOS) as the primary screen reader.

**Acceptance Criteria**

1. SearchBar container has `role="search"`.
2. CandidateList has `role="listbox"` with individual candidates as `role="option"`.
3. `aria-activedescendant` on the search input tracks the focused candidate.
4. MethodologyPanel has `role="dialog"` and `aria-modal="true"`.
5. Result region has `aria-live="polite"` and announces state changes.
6. Result region has `aria-busy="true"` during loading.
7. Error messages have `role="alert"`.
8. Map container has `role="img"` with a dynamic `aria-label` reflecting current assessment context.
9. VoiceOver reads the correct role, state, and content for every interactive element.

**Definition of Done**

- All ARIA roles and attributes applied per architecture specification.
- VoiceOver walkthrough completed with correct announcements verified.

**Testing Approach**

- Unit test: ARIA attributes are present on rendered components (query by role).
- Manual test: VoiceOver walkthrough of the full search-to-result flow on macOS.
- Playwright test: verify `aria-live` region content updates when result state changes.

**Evidence Required**

- Unit test output confirming ARIA attributes.
- VoiceOver walkthrough checklist (element, expected announcement, actual announcement, pass/fail).

---

### S07-06 — Responsive Layout Validation

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-06                 |
| Type           | Quality Assurance      |
| Effort         | ~0.5 days              |
| Dependencies   | S07-05                 |

**Statement**

As the engineer maintaining delivery quality, I want the application verified at all three responsive breakpoints (desktop, tablet, mobile), so that every core flow is operable and no content is clipped, overlapping, or inaccessible at any viewport size.

**Why**

The architecture defines three layout modes: split-pane at desktop (1024px and above), collapsible bottom panel at tablet (768-1023px), and bottom sheet at mobile (below 768px). Users on any device must be able to search for a location, view the result, read the disclaimer, and open the methodology panel. Layout defects at any breakpoint directly violate NFR-010 (no blank/broken UI) and degrade the accessibility established in prior stories.

**Scope Notes**

- Verify desktop layout (1024px and above): split-pane with map and result panel side by side.
- Verify tablet layout (768-1023px): map full width, collapsible bottom panel for results and controls.
- Verify mobile layout (below 768px): map full viewport, bottom sheet for search, results, and controls.
- Verify MethodologyPanel renders correctly at all breakpoints (drawer on desktop, full-screen bottom sheet on mobile).
- Verify all interactive controls are reachable and operable at all breakpoints.
- Confirm only TailwindCSS responsive prefixes are used (no JS-driven breakpoint detection).
- Document any gaps related to OQ-12 (tablet/mobile parity) for future resolution.

**Traceability**

- Requirements: NFR-010 (no blank/broken UI), NFR-015 (WCAG 2.2 AA)
- Architecture: `docs/architecture/03a-frontend-architecture.md` section 7 (responsive layout)

**Implementation Notes**

- Use browser DevTools device emulation at the three breakpoint boundaries: 1024px, 768px, and 375px (common mobile).
- Check for overflow, text truncation, touch target sizes (minimum 44x44px per WCAG 2.5.8), and control reachability.
- Fix any layout defects found during validation.
- If TailwindCSS responsive prefixes are insufficient for a specific case, document the exception and use the simplest CSS-only solution.

**Acceptance Criteria**

1. Desktop layout (1024px+): split-pane renders correctly with map and result panel visible simultaneously.
2. Tablet layout (768-1023px): map is full width, bottom panel is collapsible and contains all controls and results.
3. Mobile layout (below 768px): bottom sheet provides access to search, results, controls, and methodology panel.
4. MethodologyPanel renders as drawer/modal on desktop and full-screen bottom sheet on mobile.
5. All interactive controls meet minimum 44x44px touch target size on mobile.
6. No content is clipped, overlapping, or inaccessible at any breakpoint.
7. Only TailwindCSS responsive prefixes are used for layout switching (no JS-driven breakpoints).
8. Any OQ-12-related gaps are documented.

**Definition of Done**

- Layout verified at all three breakpoints.
- All layout defects found are fixed.
- OQ-12-related gaps documented if any exist.

**Testing Approach**

- Manual test: full flow at 1024px, 768px, and 375px viewports.
- Playwright test: viewport-parameterized test runs the search-to-result flow at each breakpoint.
- Visual inspection: no overflow, clipping, or overlap at any breakpoint.

**Evidence Required**

- Screenshots at each breakpoint showing the result state.
- Playwright test output for viewport-parameterized tests.
- OQ-12 gap documentation (if applicable).

---

### S07-07 — Accessibility Audit

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S07-07                 |
| Type           | Quality Assurance      |
| Effort         | ~1 day                 |
| Dependencies   | S07-06                 |

**Statement**

As the engineer maintaining delivery quality, I want a comprehensive accessibility audit performed against the finished application, so that WCAG 2.2 AA compliance is verified through both automated scanning and manual testing before the application is considered launch-ready.

**Why**

Individual stories in this epic implement specific accessibility features, but compliance must be verified holistically. Automated tools catch approximately 30-40% of accessibility issues; the remainder requires manual keyboard testing, screen reader verification, and visual inspection. This audit is the final gate that confirms all accessibility work is correct and complete.

**Scope Notes**

- Run axe-core automated scan against every distinct UI state: empty, loading, result (all 5 states), error, methodology panel open.
- Require zero critical and zero serious violations from axe-core.
- Manual keyboard walkthrough of the complete flow: land on page, search, select candidate, view result, change scenario, change horizon, open methodology panel, close methodology panel, reset.
- Screen reader test with VoiceOver: same flow as keyboard walkthrough, verify all announcements are meaningful and correctly ordered.
- Color contrast verification: all text meets 4.5:1 ratio (normal text) and 3:1 ratio (large text).
- Non-color-dependent communication check: result states are distinguishable without color (text labels, patterns, or opacity differences).
- Verify the map overlay and legend are comprehensible without color perception.
- Create a Playwright accessibility test suite that runs axe-core on key pages/states and is integrated into CI.

**Traceability**

- Requirements: NFR-015 (WCAG 2.2 AA), NFR-016 (non-color-dependent communication)
- Content Guidelines: CG-3 (result state copy provides text-based differentiation)

**Implementation Notes**

- Use `@axe-core/playwright` for automated scanning within Playwright tests.
- Structure the Playwright a11y test suite to navigate to each UI state before running the axe scan.
- For color contrast, use axe-core's built-in contrast checks plus manual verification with a contrast ratio tool for any custom colors.
- For non-color-dependent communication, verify each result state has a unique text label in addition to its color. Verify the map overlay uses pattern or opacity variation, not color alone. Verify the legend includes text labels.
- Document all findings in a structured audit report.

**Acceptance Criteria**

1. axe-core scan across all UI states produces zero critical and zero serious violations.
2. Full keyboard walkthrough is completable without mouse interaction.
3. VoiceOver walkthrough produces correct, meaningful announcements for every state and transition.
4. All text meets WCAG 2.2 AA color contrast ratios (4.5:1 normal, 3:1 large).
5. All result states are distinguishable without color (text + color, not color alone).
6. Map overlay and legend are comprehensible without color perception.
7. Playwright a11y test suite is committed and runs in CI.
8. Audit report is committed documenting findings, remediations, and residual items (if any).

**Definition of Done**

- axe-core scan passes with zero critical and zero serious violations.
- Manual keyboard walkthrough documented and passing.
- VoiceOver walkthrough documented and passing.
- Color contrast verified.
- Non-color-dependent communication verified.
- Playwright a11y test suite committed and integrated into CI.
- Audit report committed.

**Testing Approach**

- Automated: Playwright + axe-core scan of all UI states.
- Manual: keyboard walkthrough checklist.
- Manual: VoiceOver walkthrough checklist.
- Manual: color contrast spot-check with browser DevTools or dedicated tool.
- Manual: non-color-dependent communication review (grayscale screenshot comparison).

**Evidence Required**

- axe-core scan report (zero critical/serious violations).
- Keyboard walkthrough checklist (every flow step marked pass/fail).
- VoiceOver walkthrough checklist (every element's announcement documented).
- Color contrast verification results.
- Grayscale screenshot confirming result states are distinguishable without color.
- Playwright a11y test suite output (all tests pass).
- Audit report committed to repository.

---

## 8  Technical Deliverables

| Deliverable                                | Format                           | Produced By |
| ------------------------------------------ | -------------------------------- | ----------- |
| MethodologyPanel component                 | React component (committed)      | S07-01      |
| Prohibited-language lint script            | JS/TS script (committed, in CI)  | S07-02      |
| Content audit log                          | Markdown (committed)             | S07-02      |
| i18n externalization lint rule             | JS/TS lint rule (committed, in CI)| S07-03     |
| Keyboard navigation implementation         | Component updates (committed)    | S07-04      |
| ARIA attribute implementation              | Component updates (committed)    | S07-05      |
| Responsive layout fixes                    | Component/CSS updates (committed)| S07-06      |
| Playwright a11y test suite                 | Test files (committed, in CI)    | S07-07      |
| Accessibility audit report                 | Markdown (committed)             | S07-07      |

---

## 9  Data, API, and Infrastructure Impact

- **API dependency:** `GET /v1/config/methodology` must be implemented and returning all required fields before S07-01 can be completed against a live endpoint. If the endpoint is not yet available, S07-01 can proceed with a mocked response, but integration must be verified before the epic is marked complete.
- **CI pipeline impact:** Two new CI gates are added — the prohibited-language scanner (S07-02) and the i18n externalization lint rule (S07-03). Both run in the lint step of the existing GitHub Actions CI workflow.
- **No database or infrastructure changes.** This epic operates entirely within the frontend codebase and CI configuration.

---

## 10  Security and Privacy

- The MethodologyPanel fetches data from a public API endpoint (`GET /v1/config/methodology`). No authentication is required for this endpoint. No user data is transmitted or stored.
- The i18n string file (`en.ts`) must not contain any secrets, API keys, or internal URLs.
- No new security concerns are introduced by this epic.

---

## 11  Observability

- No new observability instrumentation is required. The MethodologyPanel API call is covered by existing frontend request logging (if instrumented in Epic 05/06).
- The Playwright a11y test suite produces structured output that can be archived as a CI artifact for trend tracking.

---

## 12  Testing

| Story   | Testing Approach                                                                  |
| ------- | --------------------------------------------------------------------------------- |
| S07-01  | Unit tests, integration test (TanStack Query caching), manual focus trap test, bundle analysis |
| S07-02  | Automated prohibited-language scan, manual copy review against CONTENT_GUIDELINES |
| S07-03  | Automated i18n lint rule, manual locale-file duplication test                     |
| S07-04  | Playwright keyboard navigation tests, manual keyboard walkthrough                |
| S07-05  | Unit tests (ARIA attributes), manual VoiceOver walkthrough, Playwright live region test |
| S07-06  | Playwright viewport-parameterized tests, manual visual inspection at 3 breakpoints |
| S07-07  | Playwright + axe-core automated scan, manual keyboard/VoiceOver/contrast audit   |

---

## 13  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| `GET /v1/config/methodology` endpoint is not ready when S07-01 begins | Medium | Medium | Proceed with a mocked response. Verify integration before epic close. |
| axe-core flags issues in third-party components (MapLibre GL, headless UI) that cannot be fixed without upstream patches | Medium | Low | Document as residual items in the audit report. Apply workarounds (ARIA overrides, wrapper elements) where possible. |
| VoiceOver behavior differs across macOS versions, producing inconsistent results | Low | Low | Test on the macOS version used in the development environment. Document the tested version in the audit report. |
| Responsive layout defects require significant refactoring of components built in Epic 05/06 | Medium | Low | Responsive layout was a design consideration from Epic 05. This story validates and fixes edge cases, not a full rewrite. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| Epic 06 is complete: all five result states, the result panel, ScenarioControl, HorizonControl, and ResetButton are implemented and functional. | Stories S07-02 through S07-07 cannot be fully executed. Partial work is possible but the audit (S07-07) cannot close. |
| The `GET /v1/config/methodology` endpoint contract is stable and matches the architecture specification. | S07-01 requires rework if the response schema changes. |
| TailwindCSS responsive prefixes are sufficient for all layout requirements without custom media queries. | Minor CSS additions may be needed; effort impact is negligible. |
| The prohibited language list in CONTENT_GUIDELINES section 9 is complete and stable. | If terms are added later, the lint script must be updated and a re-scan performed. |

---

## 14  Epic Acceptance Criteria

1. MethodologyPanel is implemented with all FR-033 required elements, fetched from the API, dynamically imported, and accessible (`role="dialog"`, focus trap, focus return).
2. Every UI string in `lib/i18n/en.ts` passes the prohibited-language scan with zero matches.
3. All copy matches CONTENT_GUIDELINES templates exactly (result states, disclaimer, empty, loading, error).
4. Zero hardcoded user-visible strings exist in component files; all copy originates from `en.ts` or the methodology API.
5. Full keyboard navigation works per the specified Tab order; all panels and controls are operable without a mouse.
6. All ARIA roles and attributes are applied per the architecture specification.
7. The application renders correctly at desktop (1024px+), tablet (768-1023px), and mobile (below 768px) breakpoints.
8. axe-core automated scan produces zero critical and zero serious violations across all UI states.
9. VoiceOver walkthrough confirms correct announcements for all elements and state transitions.
10. Color contrast meets WCAG 2.2 AA ratios; all result states are distinguishable without color.
11. Prohibited-language lint script and i18n externalization lint rule are committed and running in CI.
12. Playwright a11y test suite is committed and running in CI.

---

## 15  Definition of Done

- All 7 user stories completed with evidence committed to the repository.
- MethodologyPanel fully functional with API integration, dynamic import, and correct accessibility behavior.
- Content audit complete with zero prohibited-language violations and all copy matching CONTENT_GUIDELINES templates.
- i18n externalization verified with zero hardcoded strings.
- Keyboard navigation verified through manual walkthrough and Playwright tests.
- ARIA attributes verified through unit tests and VoiceOver walkthrough.
- Responsive layout verified at all three breakpoints.
- axe-core scan passes with zero critical and zero serious violations.
- Accessibility audit report committed.
- Two new CI gates (prohibited-language scan, i18n lint rule) and Playwright a11y test suite committed and passing.
- No unresolved blocker remains within this epic's scope.

---

## 16  Demo and Evidence Required

| Evidence                                                    | Location (expected)                                          |
| ----------------------------------------------------------- | ------------------------------------------------------------ |
| MethodologyPanel component with all required elements       | `src/components/MethodologyPanel/`                           |
| Bundle analysis confirming dynamic import                   | CI artifact or screenshot                                    |
| Prohibited-language lint script                             | `scripts/lint-prohibited-language.ts` (or equivalent)        |
| Content audit log                                           | `docs/delivery/artifacts/content-audit-log.md`               |
| i18n externalization lint rule                              | Integrated into ESLint config or standalone script            |
| Playwright keyboard navigation tests                        | `tests/a11y/keyboard-navigation.spec.ts`                     |
| Playwright a11y test suite (axe-core)                       | `tests/a11y/axe-scan.spec.ts`                                |
| VoiceOver walkthrough checklist                             | Included in accessibility audit report                        |
| Color contrast verification results                         | Included in accessibility audit report                        |
| Grayscale screenshot (non-color-dependent verification)     | Included in accessibility audit report                        |
| Responsive layout screenshots (3 breakpoints)               | Included in accessibility audit report                        |
| Accessibility audit report                                  | `docs/delivery/artifacts/a11y-audit-report.md`               |
