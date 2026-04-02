# 10 — Testing Strategy

> **Status:** Proposed Architecture | **Last updated:** 2026-04-02
> **Philosophy:** Test the things that are genuinely risky. The domain layer (result state determination, geography validation logic) is high-risk and fully unit-testable. Infrastructure adapters are tested through integration tests. The UI is tested through component tests, a small authored end-to-end suite, and agent-driven exploratory validation with `playwright-cli`.
>
> **Local-first principle:** All tests run against the local Docker Compose environment during development. Staging and Azure are used only for the final release validation pass (Epic 08).

---

## 1. Testing Pyramid

```
           ┌──────────┐
           │  E2E /   │  5–10 tests
           │  Smoke   │  (Playwright — demo-critical paths)
           └────┬─────┘
          ┌─────┴──────┐
          │Integration │  ~30 tests
          │  Tests     │  (API against real Postgres, TiTiler mock)
          └─────┬──────┘
         ┌──────┴───────┐
         │  Unit Tests  │  ~80 tests
         │  (domain +   │  (fast, no I/O, in-process)
         │  components) │
         └──────────────┘
```

---

## 2. Backend Unit Tests

### 2.1 ResultStateDeterminator (Critical — BR-010)

The `ResultStateDeterminator` is a pure function. Every combination of `(GeographyClassification, ExposureLayer?, bool?)` maps to exactly one `ResultState`. This is the most safety-critical logic in the system — a wrong mapping would display misleading results.

**Test matrix (all 8 meaningful combinations):**

```csharp
[Theory]
[InlineData(OutsideEurope, LayerPresent, true, ResultState.UnsupportedGeography)]
[InlineData(OutsideEurope, LayerPresent, false, ResultState.UnsupportedGeography)]
[InlineData(OutsideEurope, null, null, ResultState.UnsupportedGeography)]
[InlineData(InEuropeOutsideCoastalZone, LayerPresent, true, ResultState.OutOfScope)]
[InlineData(InEuropeOutsideCoastalZone, null, null, ResultState.OutOfScope)]
[InlineData(InEuropeAndCoastalZone, null, null, ResultState.DataUnavailable)]
[InlineData(InEuropeAndCoastalZone, LayerPresent, true, ResultState.ModeledExposureDetected)]
[InlineData(InEuropeAndCoastalZone, LayerPresent, false, ResultState.NoModeledExposureDetected)]
public void Determine_AllCombinations_ReturnExpectedState(
    GeographyClassification geo,
    ExposureLayer? layer,
    bool? isExposed,
    ResultState expected)
{
    var result = ResultStateDeterminator.Determine(geo, layer, isExposed);
    Assert.Equal(expected, result);
}
```

**Coverage target:** 100% branch coverage on `ResultStateDeterminator`.

### 2.2 Geocoding Candidate Normalization

```csharp
[Fact]
public void GeocodeAdapter_TruncatesAt5Candidates_WhenProviderReturnsMore()
{
    // Arrange: provider returns 8 candidates
    // Act: normalize
    // Assert: result has exactly 5 (BR-007)
}

[Fact]
public void GeocodeAdapter_PreservesProviderRankOrder(...)
{
    // BR-006: rank order must be preserved
}
```

### 2.3 Input Validation

```csharp
[Theory]
[InlineData("", false)]           // empty — invalid (BR-008)
[InlineData("A", true)]           // min length
[InlineData("...200chars...", true)] // max length
[InlineData("...201chars...", false)] // over limit
public void GeocodeRequest_Validation_RejectsOutOfBounds(string query, bool isValid)

[Theory]
[InlineData(-91.0, 0.0, false)]  // lat out of range
[InlineData(91.0, 0.0, false)]
[InlineData(0.0, -181.0, false)] // lng out of range
[InlineData(0.0, 181.0, false)]
[InlineData(52.3, 4.9, true)]    // valid
public void AssessRequest_Validation_CoordinateBounds(double lat, double lng, bool isValid)

[Theory]
[InlineData(2030, true)]
[InlineData(2050, true)]
[InlineData(2100, true)]
[InlineData(2040, false)]   // not a valid horizon (FR-015)
[InlineData(1990, false)]
public void AssessRequest_Validation_HorizonYear(int year, bool isValid)
```

### 2.4 AssessmentService Orchestration

Tested with mocked dependencies (`IGeographyRepository`, `ILayerResolver`, `IExposureEvaluator`):

```csharp
[Fact]
public async Task AssessAsync_WhenOutsideEurope_ReturnsUnsupportedGeography_WithoutLayerLookup()
{
    // geography repo returns IsWithinEurope=false
    // Assert: layerResolver never called (early exit)
    // Assert: resultState == UnsupportedGeography
}

[Fact]
public async Task AssessAsync_WhenNoLayerExists_ReturnsDataUnavailable_WithoutTilerCall()
{
    // geography repo returns InEuropeAndCoastalZone
    // layer resolver returns null
    // Assert: exposure evaluator never called (BR-014)
    // Assert: resultState == DataUnavailable
}

[Fact]
public async Task AssessAsync_AlwaysIncludesMethodologyVersion()
{
    // FR-035: methodologyVersion must be in every result
}

[Fact]
public async Task AssessAsync_AlwaysIncludesScenarioAndHorizon()
{
    // FR-020
}
```

---

## 3. Backend Integration Tests

Integration tests run against a **real PostgreSQL+PostGIS** database (via Testcontainers or a local Docker instance). No mocked databases — the project was explicit about not mocking DB access after prior incidents with mock/prod divergence.

### 3.1 Geography Repository

```csharp
// Requires: geography_boundaries table seeded with 'europe' and 'coastal_analysis_zone' geometries

[Fact]
public async Task IsWithinEurope_Amsterdam_ReturnsTrue()
{
    // lat: 52.37, lng: 4.90 (Amsterdam — confirmed European coastal city)
    var result = await repo.IsWithinEuropeAsync(52.37, 4.90, ct);
    Assert.True(result);
}

[Fact]
public async Task IsWithinEurope_NewYork_ReturnsFalse()
{
    var result = await repo.IsWithinEuropeAsync(40.71, -74.00, ct);
    Assert.False(result);
}

[Fact]
public async Task IsWithinCoastalZone_InlandEuropeanCity_ReturnsFalse()
{
    // OQ-04 dependent: requires coastal_analysis_zone seeded
    // Prague: lat 50.07, lng 14.43
}
```

### 3.2 Layer Repository

```csharp
[Fact]
public async Task LayerResolver_ReturnsActiveVersionLayer_WhenValidLayerExists()
{
    // Insert methodology_version (is_active=true) and layer (layer_valid=true)
    // Assert: resolves correct layer for scenario+horizon
}

[Fact]
public async Task LayerResolver_ReturnsNull_WhenLayerValidIsFalse()
{
    // layer_valid=false should not be served (BR-014)
}

[Fact]
public async Task LayerResolver_ReturnsNull_WhenNoLayerForCombination()
{
    // Missing scenario+horizon combination → DataUnavailable
}
```

### 3.3 API Endpoint Integration (ASP.NET Core WebApplicationFactory)

```csharp
// Full in-process API test with real DB and mocked TiTiler

[Fact]
public async Task PostGeocode_ValidQuery_Returns200WithCandidates()

[Fact]
public async Task PostGeocode_EmptyQuery_Returns400ValidationError()

[Fact]
public async Task PostAssess_OutsideEurope_Returns200UnsupportedGeography()

[Fact]
public async Task PostAssess_UnknownScenario_Returns400UnknownScenario()

[Fact]
public async Task PostAssess_ResponseAlwaysIncludesRequestId()

[Fact]
public async Task GetHealth_WhenDbHealthy_Returns200Healthy()

[Fact]
public async Task GetConfigScenarios_ReturnsConfirmedHorizons()
{
    // Must contain 2030, 2050, 2100 (FR-015)
}
```

---

## 4. Frontend Unit/Component Tests

**Framework:** Vitest + React Testing Library

### 4.1 AppPhase State Machine

The AppPhase state transitions are the frontend's equivalent of `ResultStateDeterminator` — they control all visible UI states.

```typescript
// useAppStore state transitions
describe('AppPhase transitions', () => {
  it('transitions idle → geocoding on search submit')
  it('transitions geocoding → candidate_selection on multiple results')
  it('transitions geocoding → assessing on single result (auto-select)')
  it('transitions geocoding → no_geocoding_results on empty candidates')
  it('transitions candidate_selection → assessing on candidate click')
  it('transitions assessing → result on successful assess')
  it('transitions assessing → assessment_error on API 500')
  it('transitions result → result_updating on scenario change')
  it('transitions result → idle on reset (FR-041)')
  it('aborts in-flight request on rapid control change (FR-040)')
})
```

### 4.2 ResultPanel

```typescript
describe('ResultPanel', () => {
  it('renders ModeledExposureDetected state with correct copy (CONTENT_GUIDELINES §3)')
  it('renders NoModeledExposureDetected state with disclaimer (CONTENT_GUIDELINES §3)')
  it('renders OutOfScope state copy')
  it('renders UnsupportedGeography state copy')
  it('renders DataUnavailable state with try-different-scenario guidance')
  it('never renders prohibited language — "will flood", "is safe", "no risk" (CONTENT_GUIDELINES §2)')
  it('always displays scenario + horizon in result (FR-020)')
  it('always displays methodologyVersion (FR-035)')
  it('shows MethodologyEntryPoint button (FR-032)')
})
```

### 4.3 Accessibility Tests

```typescript
describe('Keyboard and ARIA', () => {
  it('SearchBar submit fires on Enter key (FR-005)')
  it('CandidateList items are focusable and activatable with Enter/Space')
  it('MethodologyPanel traps focus while open (WCAG 2.2 AA)')
  it('MethodologyPanel returns focus to trigger on close (FR-034)')
  it('ErrorBanner retry button is focusable (FR-039)')
  it('All interactive controls have visible focus indicator')
  it('Map has aria-label (decorative landmark, not interactive for screen readers)')
})
```

### 4.4 API Client

```typescript
describe('API client (useGeocode, useAssess)', () => {
  it('aborts previous request when a new one starts (FR-040)')
  it('applies requestSeq guard — ignores stale responses')
  it('retries on user-initiated retry click')
  it('never logs query string in console or error reporting')
})
```

---

## 5. Browser-Based UI Testing

This project uses two complementary Playwright-based tools for browser testing. They serve different purposes and are not interchangeable.

### 5.1 Playwright CLI — Exploratory and Agent-Driven Testing

**Package:** `@playwright/cli` ([github.com/microsoft/playwright-cli](https://github.com/microsoft/playwright-cli))

**What it is:** A token-efficient command-line tool for agent-driven browser automation. It does not require authored test files. A developer or coding agent issues CLI commands to navigate, interact, inspect, and screenshot the running application.

**Install:**
```bash
# Preferred: local execution via npx (no global install)
npx playwright-cli --help

# Fallback: global install
npm install -g @playwright/cli@latest
playwright-cli --help
```

**When to use:**
- Ad-hoc local smoke checks during development (e.g., "does the search flow work after my last change?")
- Agent-driven exploratory validation — a coding agent can use `playwright-cli` to verify UI behavior without writing test files
- Capturing screenshots for visual inspection or documentation evidence
- Interactive debugging of UI states (loading, error, result rendering)
- Quick validation of accessibility behavior (focus order, visible focus indicators)

**Example workflow (local development):**
```bash
# Start the local stack
docker compose up -d

# Open the app and take a screenshot
npx playwright-cli goto http://localhost:3000
npx playwright-cli screenshot --full-page homepage.png

# Exercise the search flow
npx playwright-cli fill '[role="searchbox"]' 'Amsterdam'
npx playwright-cli press '[role="searchbox"]' Enter
npx playwright-cli snapshot   # inspect the DOM state
npx playwright-cli screenshot search-result.png

# Visual dashboard for monitoring
npx playwright-cli show
```

**What it does not replace:** `playwright-cli` does not produce repeatable, CI-integrated test suites. It is not a substitute for authored `@playwright/test` tests.

### 5.2 Playwright Test Runner — Authored E2E Test Suite

**Package:** `@playwright/test`

**What it is:** The standard Playwright testing framework. Tests are authored TypeScript files that run deterministically and produce structured reports. This is the tool used for CI gating and release verification.

**When to use:**
- Repeatable E2E coverage for all 28 acceptance criteria (AC-001 through AC-028) and 10 demo scenarios (D-01 through D-10)
- CI pipeline test gating (every PR must pass)
- Accessibility scanning with `@axe-core/playwright`
- NFR performance measurement (LCP, latency)
- Screenshot evidence for release readiness checklist

**Test target:**
- During development (Epics 05-07): tests run against the local Docker Compose environment (`baseURL = http://localhost:3000`)
- During release hardening (Epic 08): tests run against the Azure staging deployment

### 5.3 Authored E2E Tests (Demo Script Coverage)

A small smoke suite covering the demo script (ROADMAP.md D-01 to D-10). During development these run locally against Docker Compose; during release hardening they run against the staging deployment.

```typescript
// playwright.config.ts: baseURL = process.env.BASE_URL ?? 'http://localhost:3000'

test('D-01: App loads and shows EmptyState', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('main')).toContainText('Enter a location')
  // map renders, no errors in console
})

test('D-02+D-03: Search → single result auto-selects → assessment runs', async ({ page }) => {
  await page.getByRole('searchbox').fill('Amsterdam')
  await page.keyboard.press('Enter')
  // Wait for result panel
  await expect(page.getByTestId('result-panel')).toBeVisible({ timeout: 10000 })
})

test('D-04: Multiple candidates shown for ambiguous query', async ({ page }) => {
  await page.getByRole('searchbox').fill('Valencia')
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('candidate-list')).toBeVisible()
  await expect(page.getByRole('listitem')).toHaveCount.greaterThanOrEqual(2)
})

test('D-05: Scenario change triggers re-assessment', async ({ page }) => {
  // Start at result state
  // Change scenario control
  // Wait for result panel to update
})

test('D-06: Horizon change triggers re-assessment')

test('D-07: Inland European location returns OutOfScope', async ({ page }) => {
  // Search for Prague → assess → resultState == OutOfScope
  await expect(page.getByText('Outside MVP Coverage Area')).toBeVisible()
})

test('D-08: Non-European location returns UnsupportedGeography', async ({ page }) => {
  // New York → UnsupportedGeography copy
})

test('D-09: Methodology panel opens and closes (FR-032, FR-033)', async ({ page }) => {
  // Open panel → verify content visible
  // Press Escape → verify panel closed, focus returned
})

test('D-10: Reset returns to EmptyState (FR-041)', async ({ page }) => {
  // From result state → click Reset
  // Verify EmptyState shown, no marker, no result panel
})
```

---

## 6. Geospatial Pipeline Tests

The offline pipeline (see [16-geospatial-data-pipeline.md](16-geospatial-data-pipeline.md)) is tested separately with Python pytest:

```python
# test_cog_validation.py

def test_cog_is_valid_format(cog_path):
    """Output file passes rio-cogeo validate check"""
    from rio_cogeo.cogeo import cog_validate
    assert cog_validate(cog_path)[0] == True

def test_cog_crs_is_epsg4326(cog_path):
    """COG is projected in WGS84 (EPSG:4326) for TiTiler compatibility"""
    import rasterio
    with rasterio.open(cog_path) as src:
        assert src.crs.to_epsg() == 4326

def test_cog_pixel_values_binary(cog_path):
    """Pixel values are 0, 1, or NoData — not continuous (NFR-020 binary layer)"""
    import rasterio
    import numpy as np
    with rasterio.open(cog_path) as src:
        data = src.read(1, masked=True)
        unique_values = set(np.unique(data.compressed()))
        assert unique_values.issubset({0, 1})

def test_layer_registered_in_db(db, scenario_id, horizon_year, version):
    """After pipeline run, layer row exists in DB with layer_valid=False (awaiting QA)"""
    layer = db.execute(
        "SELECT layer_valid FROM layers WHERE scenario_id=%s AND horizon_year=%s AND methodology_version=%s",
        (scenario_id, horizon_year, version)
    ).fetchone()
    assert layer is not None
    assert layer['layer_valid'] == False  # QA not yet run
```

---

## 7. Acceptance Criteria Test Mapping

The PRD defines 28 acceptance criteria (AC-001 to AC-028). High-risk ACs and their primary test coverage:

| AC | Description | Primary Coverage |
|---|---|---|
| AC-001 | App loads in < 4s (NFR-001) | Playwright + Lighthouse CI |
| AC-002 | Geocoding returns results in < 2.5s (NFR-002) | Playwright network timing |
| AC-003 | Assessment returns in < 3.5s (NFR-003) | Playwright + API integration timing |
| AC-004 | Control switch re-assesses in < 1.5s (NFR-004) | Playwright |
| AC-009 | No more than 5 geocoding candidates (BR-007) | Unit test — geocoding adapter |
| AC-010 | Rank order preserved (BR-006) | Unit test — geocoding adapter |
| AC-012 | Result state one of 5 fixed values (BR-010) | Unit test — ResultStateDeterminator (100% branch coverage) |
| AC-013 | No substitution for DataUnavailable (BR-014) | Unit test — AssessmentService |
| AC-015 | WCAG 2.2 AA (NFR-015) | Accessibility component tests + axe-core in Playwright |
| AC-016 | Raw addresses never logged (NFR-007) | Log audit (manual) + code review |
| AC-020 | methodologyVersion always present (FR-035) | Integration test — assess endpoint |
| AC-024 | Geography validation server-side only (FR-009) | Integration test — API directly with non-EU coords |
| AC-026 | Reset returns to idle state (FR-041) | Playwright D-10 |
| AC-028 | Rapid control changes handled without stale results (FR-040) | Component test — useAssess hook |

---

## 8. Test Data Strategy

### Test Coordinates

| Location | Lat | Lng | Expected Result |
|---|---|---|---|
| Amsterdam | 52.3676 | 4.9041 | ModeledExposureDetected (coastal NL) |
| Prague | 50.0755 | 14.4378 | OutOfScope (inland) |
| New York | 40.7128 | -74.0060 | UnsupportedGeography |
| Ostend, Belgium | 51.2298 | 2.9186 | ModeledExposureDetected (coastal) |

**Note:** Exact results for `ModeledExposureDetected` vs `NoModeledExposureDetected` depend on OQ-04 (coastal zone definition) and OQ-05 (exposure threshold). Test coordinates above are illustrative; actual values require real COG data to be present.

### Database Seeding for Tests

Integration tests use a `TestDbFixture` that:
1. Spins up Testcontainers PostgreSQL with PostGIS
2. Runs `infra/db/init.sql` (schema creation)
3. Seeds test scenarios, horizons, methodology version, and geometry for Europe boundary
4. Tears down after test run

Coastal zone geometry is stubbed as a bounding box for Europe's coastline (simplified) until OQ-04 is resolved.

---

## 9. CI Gate

Tests must pass before merging to `main`:

```yaml
# .github/workflows/ci.yml (outline)
jobs:
  test-api:
    steps:
      - dotnet test --filter "Category!=Integration"  # unit tests: fast
      - dotnet test --filter "Category=Integration"   # integration: needs Testcontainers

  test-frontend:
    steps:
      - npx vitest run                                 # unit + component
      - npx tsc --noEmit                               # type check

  e2e-local:
    steps:
      - docker compose up -d                           # spin up local stack
      - npx playwright test                            # run against localhost
      - docker compose down
```

> **Note:** During Epics 05-07, all Playwright tests run against the local Docker Compose environment. The staging deployment is not required until Epic 08. During Epic 08 (release hardening), an additional `e2e-staging` job runs the same test suite against the Azure staging URL to confirm parity between local and cloud environments.

### 9.1 Local Exploratory Validation (Not CI-Gated)

`playwright-cli` is used during development for ad-hoc validation but is not part of the CI pipeline. It is an interactive tool, not an automated gate. Developers and coding agents use it to verify UI behavior before committing changes. Its output (screenshots, snapshots) may be attached as evidence artifacts but is not required to pass any CI check.
