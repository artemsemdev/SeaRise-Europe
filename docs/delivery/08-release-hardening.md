# Epic 08 — Testing, Security Hardening, and Release Readiness

| Field          | Value                                                                        |
| -------------- | ---------------------------------------------------------------------------- |
| Epic ID        | E-08                                                                         |
| Phase          | 1                                                                            |
| Status         | Not Started                                                                  |
| Effort         | ~7 days                                                                      |
| Dependencies   | ALL prior epics (E-01 through E-07)                                          |
| Stories        | 8 (S08-01 through S08-08)                                                    |

---

## 1  Objective

Achieve release readiness by completing all test suites, hardening security controls, verifying every non-functional requirement, and confirming the MVP Definition of Done checklist item by item. This epic is the release gate — the MVP is not complete until every story in this epic passes.

---

## 2  Why This Epic Exists

Epics 01 through 07 produce the application's decisions, infrastructure, data, backend, and frontend. But none of those epics prove the system works end-to-end, prove it is secure, or prove it meets its non-functional targets. Without a dedicated hardening and verification pass, the project ships with untested assumptions about correctness, performance, accessibility, and privacy. This epic converts those assumptions into evidence. It is intentionally the last epic because it requires all prior work to be complete — there is nothing to test, audit, or harden until the application exists.

---

## 3  Scope

### 3.1 In Scope

- Backend unit and integration test suites (pytest, xUnit, Testcontainers).
- Frontend unit and integration test suites (Vitest, React Testing Library, MSW).
- End-to-end test suite (Playwright) covering all 28 acceptance criteria and all 10 demo scenarios.
- Security hardening: CORS, CSP headers, rate limiting, input validation, SSRF prevention, Key Vault verification, HTTPS enforcement.
- Log audit: scan all log statements for PII leakage (raw addresses, precise coordinates).
- NFR verification: measured evidence for NFR-001 through NFR-023.
- Accessibility audit: axe-core automated scan plus manual keyboard and screen reader walkthrough.
- Release readiness checklist: every item from the MVP Definition of Done verified and evidenced.
- Staging deployment confirmation via CI/CD.

### 3.2 Out of Scope

- Load testing or stress testing beyond NFR target verification.
- Penetration testing by external parties.
- Production deployment (separate operational step).
- Custom domain and DNS configuration.
- Analytics integration (OQ-10).
- Post-launch monitoring dashboards.

---

## 4  Blocking Open Questions

None. All blocking open questions were resolved in Epic 01. This epic consumes the outputs of all prior epics and requires no new decisions.

---

## 5  Traceability

### 5.1 Product Requirement Traceability

| Requirement           | Description                                              |
| --------------------- | -------------------------------------------------------- |
| AC-001 through AC-028 | All acceptance criteria                                  |
| FR-039                | Error states                                             |
| BR-010                | Result state taxonomy                                    |
| NFR-001               | Shell cold load LCP ≤4s                                  |
| NFR-002               | Geocoding p95 ≤2.5s                                      |
| NFR-003               | Assessment p95 ≤3.5s                                     |
| NFR-004               | Control switch ≤1.5s from cache                          |
| NFR-005               | HTTPS on all communication                               |
| NFR-006               | No secrets in client source                              |
| NFR-007               | No raw addresses in logs                                 |
| NFR-011               | Health endpoint returns accurate status                  |
| NFR-015               | WCAG 2.2 AA                                              |
| NFR-019               | Stateless containers                                     |
| NFR-021               | Methodology versioning                                   |
| NFR-022               | Reproducibility of exposure results                      |
| SM-1                  | Search-to-result completion ≥85%                         |
| SM-7                  | 100% methodology version visibility                      |
| SM-8                  | 0 copy integrity findings                                |

### 5.2 Architecture Traceability

| Architecture Document                                      | Relevance                                    |
| ---------------------------------------------------------- | -------------------------------------------- |
| `docs/architecture/10-testing-strategy.md`                 | Primary reference for all test suites        |
| `docs/architecture/07-security-architecture.md`            | Security hardening checklist, CORS, CSP, rate limiting |
| `docs/architecture/06-api-and-contracts.md`                | API endpoint contracts for integration tests |
| `docs/architecture/03a-frontend-architecture.md`           | AppPhase transitions, component structure    |
| `docs/architecture/09-observability-and-operations.md`     | Log format, correlation IDs, structured logging |
| `docs/architecture/08-deployment-topology.md`              | Container Apps deployment, staging environment |
| `docs/architecture/13-domain-model.md`                     | ResultState definitions, domain entities     |
| `docs/architecture/16-geospatial-data-pipeline.md`         | Pipeline test expectations                   |

---

## 6  Implementation Plan

Work through stories in the following recommended order. The execution order map shows dependencies and parallelization opportunities:

```
S08-01 (Backend Test Suite)
  |
  +----> S08-02 (Frontend Test Suite)     <-- parallel with S08-03
  |
  +----> S08-03 (Security Hardening)      <-- parallel with S08-02
  |        |
  |        +----> S08-04 (Log Audit)
  |
  +----> S08-05 (E2E + Demo Script)       <-- after S08-01 + S08-02
  |        |
  |        +----> S08-06 (NFR Verification)
  |                 |
  |                 +----> S08-07 (Accessibility Audit)
  |
  +----> S08-08 (Release Checklist)       <-- after ALL prior stories
```

**Ordering rationale.** S08-01 is first because backend test infrastructure (Testcontainers, test data seeding) establishes patterns reused by integration and E2E tests. S08-02 and S08-03 run in parallel because they are independent workstreams (frontend tests vs. security configuration). S08-04 follows S08-03 because the log audit validates that security-related logging changes from hardening are correct. S08-05 depends on both S08-01 and S08-02 because E2E tests exercise the full stack and assume unit/integration coverage is already in place. S08-06 follows S08-05 because NFR measurement requires a stable, tested system. S08-07 follows S08-06 because accessibility is a subset of NFR verification that benefits from a stable deployment. S08-08 is strictly last — it is the final gate that walks through every item on the MVP Definition of Done checklist and cannot be completed until all other stories have passed.

---

## 7  User Stories

---

### S08-01 — Complete Backend Test Suite

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-01                                                                     |
| Type           | Quality Assurance                                                          |
| Effort         | ~1.5 days                                                                  |
| Dependencies   | Epics 03, 04 (backend code must exist)                                     |

**Statement**

As the engineer maintaining delivery quality, I want a complete backend test suite with unit and integration coverage, so that every backend behavior is verified against its specification and regressions are caught automatically.

**Why**

The backend contains the core business logic: geography validation, result state determination, exposure assessment pipeline orchestration, and geocoding integration. These components have defined contracts and edge cases documented across the architecture. Without automated test coverage, correctness depends on manual verification, which is slow, error-prone, and non-repeatable. The backend test suite is the foundation that all higher-level testing (E2E, NFR) builds on.

**Scope Notes**

- Unit tests for `ResultStateDeterminator`: 100% branch coverage across all 5 result states (`ModeledExposureDetected`, `NoExposureModeled`, `OutOfScope`, `UnsupportedGeography`, `ServiceError`).
- Unit tests for geography validation: Europe bounds check, coastal zone check, edge cases (boundary coordinates, null island, antimeridian).
- Unit tests for assessment pipeline: each pipeline step in isolation.
- Unit tests for input validation: FluentValidation rules, max 200 chars, coordinate bounds, empty input.
- Integration tests using Testcontainers (real PostgreSQL, not mocks): test all 5 result states against seeded data.
- Integration tests for API endpoints: `/geocode`, `/assess`, `/config`, `/health`.
- Geocoding client tests: response mapping, error handling, timeout behavior.
- Health endpoint test: returns accurate status reflecting downstream dependency state.

**Traceability**

- Requirements: BR-010, FR-039, NFR-011
- Architecture: `docs/architecture/10-testing-strategy.md` (backend unit and integration), `docs/architecture/06-api-and-contracts.md` (endpoint contracts), `docs/architecture/13-domain-model.md` (ResultState)

**Implementation Notes**

- Use Testcontainers for PostgreSQL in integration tests. Do not use in-memory database substitutes — the architecture explicitly requires real PostgreSQL with PostGIS.
- Seed the test database with known scenarios, horizons, geography boundaries, and layer registrations that produce deterministic result states.
- Structure tests by component: `ResultStateDeterminator`, `CoastalZoneValidator`, `GeographyValidator`, `GeocodingClient`, `AssessmentPipeline`, `ApiEndpoints`.
- Integration tests must cover all 5 result states: seed data for a known-coastal-exposed location, a known-coastal-unexposed location, a known-inland location, a non-European location, and a simulated service error.
- Run all tests in CI (GitHub Actions). All tests must pass on every PR.

**Acceptance Criteria**

1. `ResultStateDeterminator` has 100% branch coverage verified by coverage report.
2. Unit tests exist for all geography validation paths: Europe check pass, Europe check fail, coastal zone pass, coastal zone fail, boundary edge cases.
3. Unit tests exist for input validation: empty input rejected, input exceeding 200 chars rejected, valid input accepted.
4. Integration tests run against real PostgreSQL via Testcontainers (no mocks, no in-memory substitutes).
5. Integration tests cover all 5 result states with deterministic seeded data.
6. API endpoint integration tests cover `/geocode`, `/assess`, `/config`, and `/health`.
7. Geocoding client tests verify response mapping, HTTP error handling, and timeout handling.
8. Health endpoint test confirms status reflects downstream dependency availability.
9. All tests pass in CI (GitHub Actions).

**Definition of Done**

- All backend unit and integration tests pass locally and in CI.
- Coverage report shows 100% branch coverage on `ResultStateDeterminator`.
- Test database seeding produces all 5 result states deterministically.

**Testing Approach**

- xUnit (or NUnit) for .NET backend tests.
- Testcontainers for PostgreSQL integration tests.
- pytest for pipeline step tests.
- CI gate: all tests must pass on every PR.

**Evidence Required**

- CI run output showing all backend tests passing (green).
- Coverage report for `ResultStateDeterminator` showing 100% branch coverage.
- Test database seed script producing all 5 result states.

---

### S08-02 — Complete Frontend Test Suite

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-02                                                                     |
| Type           | Quality Assurance                                                          |
| Effort         | ~1 day                                                                     |
| Dependencies   | Epics 05, 06 (frontend code must exist); S08-01 (test patterns established) |

**Statement**

As the engineer maintaining delivery quality, I want a complete frontend test suite with unit and integration coverage, so that every UI component, phase transition, and result state rendering is verified automatically.

**Why**

The frontend implements a multi-phase application flow (Initial, Searching, Assessing, Result, Error) with 5 distinct result states, each rendering different copy, controls, and map content. The UI also contains methodology text, disclaimers, and scientific language subject to content guidelines. Without automated tests, copy integrity, phase transitions, and result state rendering depend on manual inspection, which does not scale and misses regressions.

**Scope Notes**

- Vitest + React Testing Library unit tests for all components.
- AppPhase transition tests: Initial to Searching, Searching to Assessing, Assessing to Result (for each result state), error transitions.
- Result state rendering tests: each of the 5 result states renders the correct heading, body copy, and controls.
- Prohibited language scan on `en.ts` (or equivalent locale file): verify no terms from `CONTENT_GUIDELINES` prohibited list appear in any UI string.
- MSW (Mock Service Worker) integration tests for full flows: geocoding request/response, assessment request/response, config fetch.
- Scenario and horizon control tests: switching scenario triggers map update, switching horizon triggers map update, no new geocoding request on control switch.

**Traceability**

- Requirements: AC-001 through AC-028, BR-010, SM-8
- Architecture: `docs/architecture/10-testing-strategy.md` (frontend unit and integration), `docs/architecture/03a-frontend-architecture.md` (AppPhase, component tree)

**Implementation Notes**

- Use MSW to intercept HTTP requests in integration tests. Do not use real API calls in frontend tests.
- Test each result state by mocking the assessment response to return the corresponding state payload.
- The prohibited language scan should be a dedicated test that reads the locale file and asserts no prohibited terms are present. This catches copy integrity regressions automatically.
- AppPhase transitions should be tested by simulating user actions (enter search, select candidate, wait for result) and asserting the rendered output at each phase.

**Acceptance Criteria**

1. Unit tests exist for every UI component (search bar, candidate list, result panel, map surface, methodology panel, disclaimer, scenario control, horizon control).
2. AppPhase transition tests cover all transitions: Initial to Searching, Searching to Assessing, Assessing to each of the 5 result states, any phase to Error.
3. Each of the 5 result states renders correct heading, body copy, and controls verified by assertion.
4. Prohibited language scan test reads `en.ts` (or equivalent) and asserts zero matches against the prohibited term list.
5. MSW integration tests cover: geocoding request and candidate rendering, assessment request and result rendering, config fetch and default population.
6. Scenario and horizon control switch tests verify map update without new geocoding request.
7. All tests pass in CI.

**Definition of Done**

- All frontend unit and integration tests pass locally and in CI.
- Prohibited language scan passes with zero findings.
- MSW integration tests cover geocoding, assessment, and config flows.

**Testing Approach**

- Vitest as test runner.
- React Testing Library for component rendering and interaction.
- MSW for HTTP mocking in integration tests.
- CI gate: all tests must pass on every PR.

**Evidence Required**

- CI run output showing all frontend tests passing (green).
- Prohibited language scan test output showing zero findings.
- MSW integration test output showing full flow coverage.

---

### S08-03 — Security Hardening

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-03                                                                     |
| Type           | Security                                                                   |
| Effort         | ~1 day                                                                     |
| Dependencies   | Epics 02, 04, 05 (infrastructure, API, and frontend must exist)            |

**Statement**

As the system, I need all security controls from the security architecture applied and verified, so that the application meets its security requirements before release.

**Why**

The security architecture defines specific controls — CORS, CSP, rate limiting, input validation, SSRF prevention, Key Vault integration, HTTPS — but defining controls is not the same as verifying them. Until each control is tested against the running application, security is an assumption. This story converts every security specification into a verified, evidenced control.

**Scope Notes**

- CORS: verify API allows only the frontend domain; verify TiTiler also restricts origins; verify preflight requests return correct headers.
- CSP headers: verify `Content-Security-Policy` header on frontend responses includes `script-src 'self'`, `style-src 'self' 'unsafe-inline'` (TailwindCSS), `img-src 'self' blob: data: {tiler-domain}`.
- Rate limiting: verify 60 req/min per IP on `/geocode`, 120 req/min on `/assess`; verify 429 response when limit exceeded.
- Input validation: verify max 200 char limit, coordinate bounds validation, special character handling, empty input rejection; verify FluentValidation rules produce correct error responses.
- SSRF prevention: verify geocoding client validates response URLs against allowlist; verify no open redirect via geocoding response.
- Key Vault: verify all container apps reference secrets via `secretref`; verify no secrets in source code, Docker images, or environment variable literals.
- HTTPS: verify all endpoints (API, frontend, TiTiler) serve over HTTPS only; verify HTTP-to-HTTPS redirect or refusal.
- Security checklist: complete every item from `docs/architecture/07-security-architecture.md` section 8.

**Traceability**

- Requirements: NFR-005, NFR-006
- Architecture: `docs/architecture/07-security-architecture.md` (all sections)

**Implementation Notes**

- Use `curl` or a lightweight HTTP client to verify CORS headers, CSP headers, and HTTPS enforcement.
- Rate limit verification: send requests in a loop exceeding the configured limit and confirm 429 responses.
- Source code scan: `grep` or equivalent for connection strings, API keys, passwords, tokens in all source files and Dockerfiles.
- Key Vault verification: inspect Container Apps configuration for `secretref` references.
- Document each control check as pass/fail in a security verification report.

**Acceptance Criteria**

1. CORS: API returns `Access-Control-Allow-Origin` matching only the frontend domain; cross-origin requests from other origins are rejected.
2. CORS: TiTiler returns correct CORS headers.
3. CSP: Frontend responses include `Content-Security-Policy` header with `script-src 'self'`, `style-src 'self' 'unsafe-inline'`, `img-src 'self' blob: data: {tiler-domain}`.
4. Rate limiting: `/geocode` returns 429 after 60 requests within 1 minute from the same IP.
5. Rate limiting: `/assess` returns 429 after 120 requests within 1 minute from the same IP.
6. Input validation: requests exceeding 200 chars return 400 with structured error response.
7. Input validation: requests with out-of-bounds coordinates return 400.
8. SSRF: geocoding client rejects response URLs not on the provider allowlist.
9. Key Vault: all secrets are referenced via `secretref`; zero secrets found in source code or Docker images.
10. HTTPS: all public endpoints respond over HTTPS; HTTP requests are redirected or refused.
11. Security checklist from `docs/architecture/07-security-architecture.md` section 8 is complete with all items passing.

**Definition of Done**

- Security verification report committed with pass/fail for each control.
- All controls pass.
- Security checklist complete.

**Testing Approach**

- Manual and scripted verification using `curl`, HTTP client, and source code scanning tools.
- Rate limit tests via scripted request loops.
- Source code scan for secrets.

**Evidence Required**

- Security verification report (pass/fail per control).
- CORS header output from `curl`.
- CSP header output from `curl`.
- Rate limit test output (429 response after threshold).
- Source code scan output (zero secret findings).
- Completed security checklist.

---

### S08-04 — Log Audit and Privacy Verification

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-04                                                                     |
| Type           | Security / Privacy                                                         |
| Effort         | ~0.5 days                                                                  |
| Dependencies   | S08-03 (security hardening must be complete)                               |

**Statement**

As the engineer maintaining delivery quality, I want every log statement in the codebase audited for PII leakage, so that no raw addresses or personal data appear in application logs (NFR-007, BR-016).

**Why**

The application processes user-submitted addresses. If any log statement writes the raw address string, the system violates NFR-007 and creates a privacy liability. Structured logging with correlation IDs allows debugging without exposing user input. This audit must be performed after security hardening (S08-03) to verify that any logging changes introduced during hardening are also compliant.

**Scope Notes**

- Scan ALL log statements in backend source code (C#, Python) for: raw address strings, user input interpolation, precise latitude/longitude pairs logged unnecessarily.
- Verify that structured log fields do not include raw address text.
- Verify that correlation IDs are present in all log entries for request tracing.
- Verify that geocoding client logs do not include the user's query text.
- Verify that assessment pipeline logs do not include the user's address.
- Check frontend console logs (if any) for address leakage.
- Verify that Log Analytics queries cannot reconstruct user addresses from log data.

**Traceability**

- Requirements: NFR-007, BR-016
- Architecture: `docs/architecture/09-observability-and-operations.md` (structured logging), `docs/architecture/07-security-architecture.md` (PII in logs)

**Implementation Notes**

- Use `grep` or `rg` to find all log statements (`_logger.Log`, `logger.info`, `logger.warning`, `logger.error`, `console.log`, `console.warn`, `console.error`).
- For each log statement, verify the arguments do not include raw user input.
- Permitted log content: correlation ID, result state enum, latency measurements, error codes, country codes, boolean flags.
- Prohibited log content: raw address strings, full query text, precise user-submitted coordinates (rounded coordinates for debugging are acceptable if documented).

**Acceptance Criteria**

1. Every log statement in the backend codebase is reviewed and documented as compliant or remediated.
2. Zero log statements include raw address strings or full user query text.
3. Correlation IDs are present in all log entries.
4. Geocoding client logs do not expose the user's query.
5. Assessment pipeline logs do not expose the user's address.
6. Frontend source contains no `console.log` statements that output user input.
7. A sample Log Analytics query demonstrates that user addresses cannot be reconstructed from log data.

**Definition of Done**

- Log audit report committed with per-statement findings.
- All non-compliant log statements remediated.
- Sample Log Analytics query demonstrates no PII exposure.

**Testing Approach**

- Source code scan (automated `grep`/`rg`).
- Manual review of each log statement's arguments.
- Runtime verification: submit a test address, query Log Analytics, confirm the address does not appear.

**Evidence Required**

- Log audit report listing every log statement and its compliance status.
- Remediation diff for any non-compliant statements.
- Log Analytics query output showing a sample request trace without PII.

---

### S08-05 — E2E Test Suite and Demo Script Validation

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-05                                                                     |
| Type           | Quality Assurance                                                          |
| Effort         | ~1.5 days                                                                  |
| Dependencies   | S08-01 (backend tests), S08-02 (frontend tests) — E2E requires a stable, tested stack |

**Statement**

As the engineer maintaining delivery quality, I want a Playwright E2E test suite that validates all 28 acceptance criteria and all 10 demo scenarios against the running application, so that the system is proven correct end-to-end with screenshot evidence.

**Why**

Unit and integration tests verify components in isolation. They do not prove that the full system — frontend, API, database, TiTiler, geocoding provider — works together to deliver the user experience defined in the acceptance criteria. E2E tests are the only way to verify that a user can search for a location, see candidates, select one, view the exposure assessment, switch scenario and horizon controls, and see the methodology panel — all without error. The demo script scenarios additionally prove the system handles the representative inputs that will be used in stakeholder demonstrations.

**Scope Notes**

- Playwright tests for all 28 acceptance criteria (AC-001 through AC-028).
- Playwright tests for all 10 demo scenarios:

| #    | Input                        | Expected State              |
| ---- | ---------------------------- | --------------------------- |
| D-01 | Netherlands coastal          | ModeledExposureDetected     |
| D-02 | Portugal coastal             | ModeledExposureDetected or NoExposureModeled |
| D-03 | Italy coastal city           | ModeledExposureDetected or NoExposureModeled |
| D-04 | Prague (inland)              | OutOfScope                  |
| D-05 | Inland far from coast        | OutOfScope                  |
| D-06 | New York (non-Europe)        | UnsupportedGeography        |
| D-07 | Ambiguous query              | Up to 5 candidates          |
| D-08 | Empty search                 | Validation, no request      |
| D-09 | Change scenario after result | Map and summary update      |
| D-10 | Change horizon after result  | Map and summary update      |

- Full search-to-result flow coverage.
- Screenshot capture at each significant step for evidence.
- Accessibility assertions embedded in E2E tests (axe-core via Playwright where applicable).

**Traceability**

- Requirements: AC-001 through AC-028, BR-010, SM-1
- Architecture: `docs/architecture/10-testing-strategy.md` (E2E tests, demo script)

**Implementation Notes**

- Run Playwright against the staging deployment or Docker Compose local environment.
- Each AC should map to one or more Playwright test cases. Use descriptive test names that reference the AC ID (e.g., `test('AC-003: candidate list displays up to 5 results')`).
- Demo scenarios should be a separate test suite file for clear traceability.
- Capture screenshots at: initial state, search results, candidate selection, result display (for each result state), scenario switch, horizon switch, methodology panel, disclaimer.
- Configure Playwright to generate an HTML report with embedded screenshots.

**Acceptance Criteria**

1. Playwright test exists for each of the 28 acceptance criteria (AC-001 through AC-028), with test name referencing the AC ID.
2. Playwright test exists for each of the 10 demo scenarios (D-01 through D-10), with test name referencing the demo ID.
3. All 28 AC tests pass.
4. All 10 demo scenario tests pass.
5. Screenshots are captured at each significant step and included in the Playwright HTML report.
6. Full search-to-result flow (search, select candidate, view result, switch scenario, switch horizon, view methodology, view disclaimer, reset) is covered.
7. E2E tests run in CI.

**Definition of Done**

- All 28 AC tests pass.
- All 10 demo scenario tests pass.
- Playwright HTML report with screenshots committed or archived as CI artifact.
- Tests run in CI pipeline.

**Testing Approach**

- Playwright against staging or Docker Compose.
- HTML report generation with screenshots.

**Evidence Required**

- Playwright HTML report with all tests passing and embedded screenshots.
- CI run output showing E2E suite passing.
- Screenshot evidence for each demo scenario showing the correct result state.

---

### S08-06 — NFR Verification

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-06                                                                     |
| Type           | Quality Assurance                                                          |
| Effort         | ~0.5 days                                                                  |
| Dependencies   | S08-05 (E2E tests confirm functional correctness before measuring NFRs)    |

**Statement**

As the engineer maintaining delivery quality, I want every non-functional requirement measured and documented with evidence, so that the system's performance, security, and operational characteristics are proven to meet their targets.

**Why**

Non-functional requirements define the quality attributes that distinguish a working prototype from a releasable product. Each NFR has a specific, measurable target. Until those targets are measured against the actual running system, compliance is an assumption. This story produces the measurement evidence that the release checklist (S08-08) requires.

**Scope Notes**

- NFR-001: Measure shell cold load LCP using Playwright. Target: ≤4s.
- NFR-002: Measure geocoding p95 latency over 20+ requests. Target: ≤2.5s.
- NFR-003: Measure assessment p95 latency over 20+ requests. Target: ≤3.5s.
- NFR-004: Measure control switch latency (scenario or horizon change with cached data). Target: ≤1.5s.
- NFR-005: Verify HTTPS on all endpoints (API, frontend, TiTiler). Pass/fail.
- NFR-006: Verify no secrets in client-side source (view-source, network tab inspection). Pass/fail.
- NFR-007: Verify no raw addresses in logs (cross-reference S08-04 log audit). Pass/fail.
- NFR-011: Verify health endpoint returns accurate status reflecting downstream dependencies. Pass/fail.
- NFR-015: Verify WCAG 2.2 AA (cross-reference S08-07 accessibility audit). Pass/fail.
- NFR-019: Verify stateless containers — restart a container, confirm no data loss. Pass/fail.
- NFR-021: Verify methodology version is present in every assessment response.
- NFR-022: Verify same input produces same result (reproducibility).
- SM-7: Verify 100% of results include methodology version.
- Document all measurements in an NFR verification report.

**Traceability**

- Requirements: NFR-001 through NFR-023, SM-7
- Architecture: `docs/architecture/10-testing-strategy.md` (NFR testing), `docs/architecture/09-observability-and-operations.md` (health endpoints)

**Implementation Notes**

- Use Playwright's `page.evaluate(() => performance.getEntriesByType('navigation'))` or LCP observer for NFR-001.
- For NFR-002 and NFR-003, use a script that sends 20+ requests and computes p95 from response times.
- For NFR-004, measure time from control click to map tile update completion using Playwright network idle detection.
- For NFR-019, use `docker restart` on a container and verify the next request succeeds with correct data.
- For NFR-022, send the same assessment request 3 times and assert identical response payloads.
- Record each measurement in a structured table: NFR ID, target, measured value, pass/fail.

**Acceptance Criteria**

1. NFR-001: LCP measurement ≤4s on cold load (Playwright measurement recorded).
2. NFR-002: Geocoding p95 latency ≤2.5s over 20+ requests (measurements recorded).
3. NFR-003: Assessment p95 latency ≤3.5s over 20+ requests (measurements recorded).
4. NFR-004: Control switch latency ≤1.5s from cache (measurement recorded).
5. NFR-005: All endpoints verified HTTPS-only.
6. NFR-006: No secrets found in client-side source.
7. NFR-007: Log audit confirms no raw addresses (S08-04 cross-reference).
8. NFR-011: Health endpoint accurately reflects dependency status.
9. NFR-019: Container restart does not cause data loss or service failure.
10. NFR-021: Methodology version present in every assessment response.
11. NFR-022: Same input produces identical result across 3 repeated requests.
12. SM-7: 100% of sampled results include methodology version.
13. NFR verification report is committed with all measurements.

**Definition of Done**

- NFR verification report committed with measured values for every NFR.
- All NFRs pass their defined targets.

**Testing Approach**

- Playwright for frontend performance measurements (NFR-001, NFR-004).
- Scripted HTTP requests for backend latency measurements (NFR-002, NFR-003).
- Manual and scripted verification for pass/fail NFRs.

**Evidence Required**

- NFR verification report table: NFR ID, target, measured value, pass/fail.
- Playwright LCP measurement output.
- p95 latency calculation output for geocoding and assessment.
- Container restart test output.
- Reproducibility test output (3 identical responses).

---

### S08-07 — Accessibility Audit

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-07                                                                     |
| Type           | Quality Assurance                                                          |
| Effort         | ~0.5 days                                                                  |
| Dependencies   | S08-06 (NFR verification confirms system stability before accessibility audit) |

**Statement**

As the engineer maintaining delivery quality, I want an accessibility audit that proves WCAG 2.2 AA compliance, so that the application is usable by people with disabilities and meets NFR-015.

**Why**

Accessibility is a non-negotiable quality attribute, not a stretch goal. The application displays sea-level exposure data that may inform personal or financial decisions. Excluding users who rely on assistive technology from accessing this information is both an ethical failure and a compliance risk. Automated scanning catches the majority of accessibility violations, and manual walkthrough catches the interaction and navigation issues that automation misses.

**Scope Notes**

- axe-core automated scan via Playwright: run on every major view (initial state, search results, each of the 5 result states, methodology panel, error state).
- Zero critical or serious violations allowed (minor and moderate must be documented with remediation plan).
- Keyboard walkthrough: verify all interactive elements are reachable via Tab, activatable via Enter/Space, and have visible focus indicators.
- Screen reader test: verify search input, candidate list, result panel, and controls are announced correctly (test with VoiceOver on macOS or NVDA on Windows).
- Color contrast: verify all text meets WCAG 2.2 AA contrast ratios (4.5:1 for normal text, 3:1 for large text).
- Non-color-dependent communication: verify that exposure information is not conveyed by color alone (text labels, patterns, or icons must supplement color).

**Traceability**

- Requirements: NFR-015
- Architecture: `docs/architecture/10-testing-strategy.md` (accessibility tests)

**Implementation Notes**

- Use `@axe-core/playwright` to integrate axe scans into Playwright tests.
- Run axe on at least 8 distinct page states: initial, searching, candidate list, each of the 5 result states, methodology panel open.
- For keyboard walkthrough, document the tab order and verify it follows a logical reading sequence.
- For screen reader testing, document what each landmark and interactive element announces.
- If the map component (MapLibre GL) has known accessibility limitations, document them as known issues with mitigation plan.

**Acceptance Criteria**

1. axe-core scan runs on every major view (minimum 8 page states).
2. Zero critical accessibility violations.
3. Zero serious accessibility violations.
4. All minor and moderate violations are documented with remediation plan.
5. Keyboard walkthrough confirms all interactive elements are reachable via Tab and activatable via Enter/Space.
6. All interactive elements have visible focus indicators.
7. Screen reader test confirms search input, candidate list, result panel, and controls are announced with meaningful labels.
8. All text meets WCAG 2.2 AA contrast ratios.
9. Exposure information is not conveyed by color alone.

**Definition of Done**

- Accessibility audit report committed with axe-core output, keyboard walkthrough results, screen reader findings, and contrast check.
- Zero critical or serious violations.
- All remediation items (minor/moderate) documented with plan.

**Testing Approach**

- axe-core via Playwright (automated).
- Manual keyboard walkthrough.
- Manual screen reader test (VoiceOver or NVDA).
- Manual color contrast verification (browser DevTools or contrast checker tool).

**Evidence Required**

- axe-core scan results for each page state (JSON or HTML report).
- Keyboard walkthrough documentation (tab order, focus indicators, activation).
- Screen reader test documentation (announcements per element).
- Contrast ratio check results.
- List of any minor/moderate violations with remediation plan.

---

### S08-08 — Release Readiness Checklist and Staging Deployment

| Field          | Value                                                                      |
| -------------- | -------------------------------------------------------------------------- |
| ID             | S08-08                                                                     |
| Type           | Release Gate                                                               |
| Effort         | ~0.5 days                                                                  |
| Dependencies   | S08-01 through S08-07 (ALL prior stories must pass)                        |

**Statement**

As the engineer maintaining delivery quality, I want every item on the MVP Definition of Done checklist verified and evidenced in a single release readiness document, so that there is an unambiguous record that the MVP is complete and ready for release.

**Why**

The MVP Definition of Done is a 17-item checklist. Individual stories in this epic produce the evidence for subsets of these items, but no single artifact proves overall completeness. This story assembles the evidence, walks through every checklist item, and produces the final go/no-go determination. It is the last story in the last epic because it cannot be completed until everything else has passed.

**Scope Notes**

Walk through every item from the MVP Definition of Done and record status with evidence reference:

| # | Checklist Item                                             | Evidence Source       |
|---|------------------------------------------------------------|-----------------------|
| 1 | All 28 AC pass                                             | S08-05 (E2E report)  |
| 2 | All 5 result states render correctly                       | S08-05 (screenshots) |
| 3 | All 10 demo scenarios pass                                 | S08-05 (E2E report)  |
| 4 | Full search-to-assess flow works E2E                       | S08-05 (E2E report)  |
| 5 | Scenario/horizon controls update without new search        | S08-05 (D-09, D-10)  |
| 6 | Methodology panel displays all required elements           | S08-05 (AC tests)    |
| 7 | Disclaimer visible on every result                         | S08-05 (screenshots) |
| 8 | Reset returns to initial state                             | S08-05 (AC tests)    |
| 9 | All NFR targets met                                        | S08-06 (NFR report)  |
| 10| 0 copy integrity findings                                 | S08-02 (language scan)|
| 11| 100% results include methodology version                   | S08-06 (SM-7 check)  |
| 12| No prohibited language in any UI string                    | S08-02 (language scan)|
| 13| All containers deploy to staging via CI/CD                 | S08-08 (this story)  |
| 14| E2E test suite passes                                      | S08-05 (CI output)   |
| 15| Accessibility audit passes                                 | S08-07 (audit report) |
| 16| Log audit confirms no PII                                  | S08-04 (log audit)   |
| 17| Security checklist complete                                | S08-03 (sec report)  |

- Deploy all containers to staging via CI/CD pipeline.
- Run smoke tests against staging: `/health` returns 200, frontend loads, search returns results.
- Verify all containers are running and healthy in Container Apps.
- Draft release notes summarizing what the MVP includes.

**Traceability**

- Requirements: All — this story is the aggregate verification
- Architecture: `docs/architecture/08-deployment-topology.md` (staging deployment)

**Implementation Notes**

- Create a markdown file (`release-readiness-checklist.md`) with each checklist item, its status (pass/fail), and a link or reference to the evidence artifact.
- Trigger the full CI/CD pipeline to deploy all three containers (frontend, API, TiTiler) to staging.
- After deployment, run the full E2E suite against staging (not just local).
- If any item fails, it must be remediated before this story can be marked complete. There are no exceptions — this is the release gate.
- Draft release notes should list: key capabilities, known limitations, technology stack, and methodology version.

**Acceptance Criteria**

1. All 3 containers (frontend, API, TiTiler) are deployed to staging via CI/CD.
2. Staging smoke tests pass: `/health` returns 200, frontend loads, one search-to-result flow succeeds.
3. Release readiness checklist is complete with all 17 items marked as pass.
4. Every checklist item has a reference to its evidence artifact.
5. No checklist item is marked as pass without corresponding evidence.
6. Release notes are drafted.
7. The release readiness checklist document is committed to the repository.

**Definition of Done**

- All 3 containers deployed to staging.
- All 17 MVP Definition of Done items verified as pass with evidence references.
- Release readiness checklist committed.
- Release notes drafted and committed.
- Zero open items.

**Testing Approach**

- Staging deployment verification via CI/CD.
- Smoke tests via `curl` and Playwright.
- Checklist walkthrough with evidence cross-referencing.

**Evidence Required**

- CI/CD run output showing all 3 containers deployed to staging (green).
- Staging smoke test output (`/health` responses, frontend load, search flow).
- Release readiness checklist document with all 17 items pass and evidence references.
- Draft release notes.

---

## 8  Technical Deliverables

| Deliverable                                    | Format                              | Produced By |
| ---------------------------------------------- | ----------------------------------- | ----------- |
| Backend test suite                             | xUnit/pytest tests (committed)      | S08-01      |
| Backend coverage report                        | HTML/XML (CI artifact)              | S08-01      |
| Frontend test suite                            | Vitest/RTL tests (committed)        | S08-02      |
| Prohibited language scan test                  | Vitest test (committed)             | S08-02      |
| Security verification report                   | Markdown (committed)                | S08-03      |
| Completed security checklist                   | Markdown (committed)                | S08-03      |
| Log audit report                               | Markdown (committed)                | S08-04      |
| Playwright E2E test suite                      | Playwright tests (committed)        | S08-05      |
| Playwright HTML report with screenshots        | HTML (CI artifact)                  | S08-05      |
| NFR verification report                        | Markdown (committed)                | S08-06      |
| Accessibility audit report                     | Markdown + axe-core output (committed) | S08-07   |
| Release readiness checklist                    | Markdown (committed)                | S08-08      |
| Release notes                                  | Markdown (committed)                | S08-08      |

---

## 9  Data, API, and Infrastructure Impact

This epic does not introduce new data, API endpoints, or infrastructure resources. It verifies and hardens what already exists:

- **Database:** Test data seeding scripts are added for integration tests (Testcontainers). No schema changes.
- **API:** Rate limiting middleware is verified and tuned. CORS and input validation are verified. No new endpoints.
- **Frontend:** CSP headers are added or verified on the serving layer. No new UI components.
- **Infrastructure:** Staging deployment is verified end-to-end via CI/CD. No new Azure resources.

---

## 10  Security and Privacy

- **CORS enforcement (S08-03):** API and TiTiler restrict origins to the frontend domain only.
- **CSP headers (S08-03):** Frontend responses include restrictive Content-Security-Policy.
- **Rate limiting (S08-03):** Geocode and assess endpoints are rate-limited per IP.
- **Input validation (S08-03):** All user input is validated server-side with length and format constraints.
- **SSRF prevention (S08-03):** Geocoding client validates all response URLs.
- **Key Vault (S08-03):** All secrets accessed via `secretref`; zero secrets in source.
- **PII in logs (S08-04):** Zero raw addresses in any log statement. Correlation IDs enable request tracing without PII.
- **HTTPS (S08-03):** All public endpoints serve HTTPS only.

---

## 11  Observability

- Backend tests (S08-01) verify that the health endpoint accurately reflects downstream dependency status.
- Log audit (S08-04) verifies structured logging format, correlation ID presence, and PII absence.
- NFR verification (S08-06) confirms health endpoint behavior under normal and degraded conditions.
- No new observability infrastructure is introduced; existing Log Analytics and health endpoint configuration is verified.

---

## 12  Testing

| Story   | Testing Approach                                                                              |
| ------- | --------------------------------------------------------------------------------------------- |
| S08-01  | xUnit unit tests, Testcontainers integration tests, pytest pipeline tests, CI execution       |
| S08-02  | Vitest unit tests, RTL component tests, MSW integration tests, CI execution                   |
| S08-03  | Manual and scripted verification: `curl` headers, rate limit scripts, source code scan         |
| S08-04  | Source code scan, manual log statement review, runtime Log Analytics query                     |
| S08-05  | Playwright E2E tests against staging or Docker Compose, HTML report with screenshots           |
| S08-06  | Playwright performance measurement, scripted latency tests, manual pass/fail verification      |
| S08-07  | axe-core via Playwright, manual keyboard walkthrough, manual screen reader test                 |
| S08-08  | CI/CD deployment, staging smoke tests, checklist walkthrough with evidence cross-referencing    |

---

## 13  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| E2E tests are flaky due to external geocoding provider latency or rate limits | High | Medium | Use a known set of stable test inputs. Implement retry logic for network-dependent tests. Consider a geocoding response cache for CI. |
| NFR-001 (LCP ≤4s) fails on cold start due to container cold boot latency | Medium | Medium | Measure after container is warm. If cold boot is the issue, configure minimum replica count to 1 in staging. Document cold vs. warm measurement distinction. |
| Security hardening changes (CSP, CORS) break existing frontend functionality | Medium | Low | Apply changes incrementally. Run E2E suite after each change. CSP in report-only mode first, then enforce. |
| Log audit reveals extensive PII leakage requiring significant code changes | Medium | Low | Audit early in the story sequence. If remediation is extensive, prioritize high-risk log statements (geocoding, assessment) first. |
| Accessibility audit reveals critical violations requiring UI rework | High | Low | Run axe-core early in development (ideally during Epics 05/06). This story is a final verification, not the first check. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| All prior epics (01-07) are complete and their code is merged to main. | This epic cannot start until all prior work is done. Any incomplete epic blocks the entire release gate. |
| Staging environment is accessible and representative of production configuration. | NFR measurements on a non-representative environment produce misleading results. Verify staging configuration matches production before measuring. |
| The geocoding provider is available and responsive during E2E test execution. | E2E tests that depend on live geocoding will fail. Mitigation: have a fallback plan to use cached responses if the provider is down during testing. |
| axe-core catches the majority of accessibility violations. | Some violations (screen reader behavior, cognitive accessibility) require manual testing. Manual walkthrough is included in scope for this reason. |

---

## 14  Epic Acceptance Criteria

1. Backend test suite passes with 100% branch coverage on `ResultStateDeterminator` and integration tests covering all 5 result states.
2. Frontend test suite passes with component coverage for all views, AppPhase transitions, and zero prohibited language findings.
3. All security controls from `docs/architecture/07-security-architecture.md` are verified with evidence.
4. Log audit confirms zero PII in log statements with evidence.
5. All 28 acceptance criteria (AC-001 through AC-028) pass in Playwright E2E tests.
6. All 10 demo scenarios (D-01 through D-10) pass in Playwright E2E tests.
7. All NFR targets are met with measured evidence.
8. Accessibility audit shows zero critical/serious violations.
9. All 3 containers are deployed to staging via CI/CD.
10. MVP Definition of Done checklist (17 items) is complete with all items passing and all evidence referenced.

---

## 15  Definition of Done

- All 8 user stories completed with evidence committed to the repository.
- All 28 acceptance criteria verified by E2E tests.
- All 10 demo scenarios verified by E2E tests.
- All NFR targets met with measured evidence.
- Security verification report complete with all controls passing.
- Log audit report complete with zero PII findings.
- Accessibility audit report complete with zero critical/serious violations.
- All 3 containers deployed to staging and healthy.
- Release readiness checklist complete with all 17 items passing.
- Release notes drafted.
- No unresolved blocker remains within this epic's scope.

---

## 16  Demo and Evidence Required

| Evidence                                                    | Location (expected)                                         |
| ----------------------------------------------------------- | ----------------------------------------------------------- |
| Backend test suite CI output (green)                        | GitHub Actions run artifact                                 |
| ResultStateDeterminator coverage report                     | CI artifact or `docs/delivery/artifacts/coverage-report`    |
| Frontend test suite CI output (green)                       | GitHub Actions run artifact                                 |
| Prohibited language scan output (zero findings)             | CI test output                                              |
| Security verification report                                | `docs/delivery/artifacts/security-verification.md`          |
| Completed security checklist                                | `docs/delivery/artifacts/security-checklist.md`             |
| Log audit report                                            | `docs/delivery/artifacts/log-audit.md`                      |
| Playwright E2E HTML report with screenshots                 | CI artifact or `docs/delivery/artifacts/e2e-report/`        |
| NFR verification report                                     | `docs/delivery/artifacts/nfr-verification.md`               |
| Accessibility audit report (axe-core + manual)              | `docs/delivery/artifacts/accessibility-audit.md`            |
| Release readiness checklist (17 items, all pass)            | `docs/delivery/artifacts/release-readiness-checklist.md`    |
| Release notes                                               | `docs/delivery/artifacts/release-notes.md`                  |
| Staging deployment CI/CD output (green)                     | GitHub Actions run artifact                                 |
| Staging smoke test output                                   | GitHub Actions run artifact or terminal output              |
