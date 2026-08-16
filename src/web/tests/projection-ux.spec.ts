import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { isForbiddenApplicationApiPath } from "../src/test/application-api-boundary";

const RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const RELEASE_ROOT = `/releases/${RELEASE_ID}`;

type Scenario = "ssp1-26" | "ssp2-45" | "ssp5-85";
type Horizon = 2030 | 2050 | 2100;

interface ProjectionExpectation {
  readonly scenario: Scenario;
  readonly horizon: Horizon;
  readonly lower: string;
  readonly median: string;
  readonly upper: string;
}

const PROJECTION_MATRIX: readonly ProjectionExpectation[] = Object.freeze([
  { scenario: "ssp1-26", horizon: 2030, lower: "0.046", median: "0.101", upper: "0.160" },
  { scenario: "ssp1-26", horizon: 2050, lower: "0.104", median: "0.194", upper: "0.297" },
  { scenario: "ssp1-26", horizon: 2100, lower: "0.219", median: "0.412", upper: "0.645" },
  { scenario: "ssp2-45", horizon: 2030, lower: "0.030", median: "0.098", upper: "0.169" },
  { scenario: "ssp2-45", horizon: 2050, lower: "0.055", median: "0.194", upper: "0.343" },
  { scenario: "ssp2-45", horizon: 2100, lower: "0.093", median: "0.497", upper: "0.934" },
  { scenario: "ssp5-85", horizon: 2030, lower: "0.056", median: "0.104", upper: "0.157" },
  { scenario: "ssp5-85", horizon: 2050, lower: "0.142", median: "0.230", upper: "0.334" },
  { scenario: "ssp5-85", horizon: 2100, lower: "0.509", median: "0.730", upper: "1.039" },
]);

const outcome = (page: Page) => page.locator(".projection-panel__outcome");
const panel = (page: Page) => page.locator(".projection-panel");
const RESULT_CAVEAT = "This result does not determine flooding, inundation, terrain exposure, flood probability, or property risk.";

async function ready(page: Page): Promise<void> {
  await expect(page.getByText(/release contract ready · 9 exact combinations/i)).toBeVisible();
  await expect(panel(page)).toHaveAttribute("data-phase", "ready");
}

async function selectSettlement(page: Page, query: string, option: RegExp): Promise<void> {
  let search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  if (await search.count() === 0) {
    await page.getByRole("button", { name: /reset selection and choose another place/i }).click();
    await expect(panel(page)).toHaveAttribute("data-phase", "ready");
    search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  }
  await search.fill(query);
  await page.getByRole("option", { name: option }).click();
  await expect(panel(page)).toHaveAttribute("data-phase", "result");
}

async function expectAvailable(
  page: Page,
  expected: ProjectionExpectation,
): Promise<void> {
  await expect(panel(page)).toHaveAttribute("data-phase", "result");
  await expect(outcome(page)).toHaveAttribute("data-outcome", "ProjectionAvailable");
  await expect(outcome(page).getByText(RESULT_CAVEAT)).toBeVisible();
  await expect(outcome(page).getByRole("heading", {
    name: "Projected regional sea-level change available",
  })).toBeVisible();
  await expect(outcome(page)).toContainText(`${expected.median} m`);
  await expect(outcome(page)).toContainText(`${expected.lower}–${expected.upper} m`);
  await expect(outcome(page)).toContainText(expected.scenario);
  await expect(outcome(page)).toContainText(String(expected.horizon));
  await expect(page.getByRole("radio", { name: new RegExp(expected.scenario) })).toBeChecked();
  await expect(page.getByRole("radio", { name: String(expected.horizon), exact: true })).toBeChecked();
}

async function expectNoSeriousAxeFindings(page: Page): Promise<void> {
  const scan = await new AxeBuilder({ page }).analyze();
  expect(
    scan.violations.filter((finding) => finding.impact === "critical" || finding.impact === "serious"),
  ).toEqual([]);
}

async function expectThreeOptionSegmentedRow(page: Page, name: RegExp): Promise<void> {
  const positions = await page.getByRole("group", { name }).locator("label").evaluateAll((labels) =>
    labels.map((label) => {
      const bounds = label.getBoundingClientRect();
      return { left: bounds.left, top: bounds.top, width: bounds.width };
    }));
  expect(positions).toHaveLength(3);
  expect(Math.max(...positions.map(({ top }) => top)) - Math.min(...positions.map(({ top }) => top)))
    .toBeLessThan(2);
  expect(positions[0].left).toBeLessThan(positions[1].left);
  expect(positions[1].left).toBeLessThan(positions[2].left);
  expect(positions.every(({ width }) => width > 0)).toBe(true);
}

async function attachStableState(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const path = testInfo.outputPath(`${name}-${testInfo.project.name}.png`);
  await page.screenshot({ path, fullPage: true, animations: "disabled" });
  await testInfo.attach(`${name}-${testInfo.project.name}.png`, {
    path,
    contentType: "image/png",
  });
}

function monitorApplicationBoundary(page: Page) {
  const forbidden: string[] = [];
  const releaseConfig: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (isForbiddenApplicationApiPath(pathname)) forbidden.push(pathname);
    if (pathname.startsWith(`${RELEASE_ROOT}/`) && pathname.endsWith(".json")) {
      releaseConfig.push(pathname);
    }
  });
  return { forbidden, releaseConfig };
}

test("real browser chain renders the four exact scientific outcomes", async ({ page }, testInfo) => {
  const boundary = monitorApplicationBoundary(page);
  await page.goto("/");
  await ready(page);

  await selectSettlement(page, "Málaga", /Málaga.*Andalucía, ES/i);
  await expectAvailable(page, PROJECTION_MATRIX[4]);
  await expect(outcome(page)).toContainText("37.0000°, -4.0000°");
  await expect(outcome(page)).toContainText("48.641 km");
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "projection-available");

  await selectSettlement(page, "Springfield", /Springfield North.*AA/i);
  await expect(outcome(page)).toHaveAttribute("data-outcome", "OutOfScope");
  await expect(outcome(page).getByText(RESULT_CAVEAT)).toBeVisible();
  await expect(outcome(page).getByRole("heading", { name: "Outside the coastal analysis area" })).toBeVisible();
  await expect(outcome(page)).toContainText("50.00000°, 10.00000°");
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "out-of-scope");

  await selectSettlement(page, "Border City", /Border City.*Boundary, TR/i);
  await expect(outcome(page)).toHaveAttribute("data-outcome", "UnsupportedGeography");
  await expect(outcome(page).getByText(RESULT_CAVEAT)).toBeVisible();
  await expect(outcome(page).getByRole("heading", { name: "Outside the supported Europe area" })).toBeVisible();
  await expect(outcome(page)).toContainText("41.00000°, 29.00000°");
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "unsupported-geography");

  await page.goto(`/?release=${RELEASE_ID}&scenario=ssp2-45&horizon=2050&lat=62&lon=44`);
  await expect(panel(page)).toHaveAttribute("data-phase", "result");
  await expect(outcome(page)).toHaveAttribute("data-outcome", "DataUnavailable");
  await expect(outcome(page).getByText(RESULT_CAVEAT)).toBeVisible();
  await expect(outcome(page).getByRole("heading", { name: "Model data unavailable for this point" })).toBeVisible();
  await expect(outcome(page)).toContainText("q0.167, q0.5, or q0.833");
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "data-unavailable");

  expect(boundary.forbidden).toEqual([]);
  expect(boundary.releaseConfig).toContain(`${RELEASE_ROOT}/manifest.json`);
});

test("first selected-place technical failure receives focus after the transition", async ({ page }) => {
  let releaseFailure!: () => void;
  const failureGate = new Promise<void>((resolve) => { releaseFailure = resolve; });
  let held = false;
  await page.route(`**${RELEASE_ROOT}/analysis/ssp2-45/2050.tif`, async (route) => {
    if (!held && route.request().method() === "HEAD") {
      held = true;
      await failureGate;
      await route.fulfill({ status: 503, contentType: "text/plain", body: "temporary" });
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  await ready(page);
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.fill("Málaga");
  await page.getByRole("option", { name: /Málaga.*Andalucía, ES/i }).click();
  await expect(page.getByText(/selected place accepted.*lookup is in progress/i)).toBeFocused();

  releaseFailure();
  await expect(panel(page)).toHaveAttribute("data-phase", "technical-error");
  const alert = panel(page).getByRole("alert");
  await expect(alert).toContainText("Technical failure — not a DataUnavailable scientific outcome");
  await expect(alert).toBeFocused();
  expect(held).toBe(true);
});

test("first selected-place integrity failure receives focus after the transition", async ({ page }) => {
  let releaseCorruption!: () => void;
  const corruptionGate = new Promise<void>((resolve) => { releaseCorruption = resolve; });
  let mutated = false;
  await page.route(`**${RELEASE_ROOT}/analysis/ssp2-45/2050.tif`, async (route) => {
    if (route.request().method() !== "GET" || !route.request().headers().range || mutated) {
      await route.continue();
      return;
    }
    await corruptionGate;
    const response = await route.fetch();
    const bytes = await response.body();
    bytes[Math.min(32, bytes.length - 1)] ^= 0x01;
    mutated = true;
    await route.fulfill({ response, body: bytes });
  });

  await page.goto("/");
  await ready(page);
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.fill("Málaga");
  await page.getByRole("option", { name: /Málaga.*Andalucía, ES/i }).click();
  await expect(page.getByText(/selected place accepted.*lookup is in progress/i)).toBeFocused();

  releaseCorruption();
  await expect(panel(page)).toHaveAttribute("data-phase", "integrity-error");
  const alert = panel(page).getByRole("alert");
  await expect(alert).toContainText("Technical failure — not a DataUnavailable scientific outcome");
  await expect(alert).toBeFocused();
  expect(mutated).toBe(true);
});

test("all nine accepted projections keep exact COG values and PMTiles identity", async ({ page }, testInfo) => {
  const boundary = monitorApplicationBoundary(page);
  const pmtiles = new Set<string>();
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith(".pmtiles")) pmtiles.add(pathname);
  });

  await page.goto("/");
  await ready(page);
  await selectSettlement(page, "Málaga", /Málaga.*Andalucía, ES/i);
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(map).toBeVisible();

  const evidence: Array<ProjectionExpectation & { artifactId: string }> = [];
  for (const expected of PROJECTION_MATRIX) {
    const scenario = page.getByRole("radio", { name: new RegExp(expected.scenario) });
    if (!(await scenario.isChecked())) await scenario.check();
    await expect(panel(page)).toHaveAttribute("data-phase", "result");
    const horizon = page.getByRole("radio", { name: String(expected.horizon), exact: true });
    if (!(await horizon.isChecked())) await horizon.check();
    await expectAvailable(page, expected);

    const artifactId = `projection-${expected.scenario}-${expected.horizon}-pmtiles`;
    await expect(map).toHaveAttribute("data-artifact-id", artifactId);
    await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(
      `Accepted result visualization · ${expected.scenario} · ${expected.horizon}`,
    );
    await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText("geonames:900000001");
    await expectNoSeriousAxeFindings(page);
    evidence.push({ ...expected, artifactId });
  }

  const matrixPath = testInfo.outputPath(`projection-matrix-${testInfo.project.name}.json`);
  await writeFile(matrixPath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  await testInfo.attach(`projection-matrix-${testInfo.project.name}.json`, {
    path: matrixPath,
    contentType: "application/json",
  });
  await attachStableState(page, testInfo, "projection-matrix-final");
  expect([...pmtiles].sort()).toEqual(PROJECTION_MATRIX.map(
    ({ scenario, horizon }) => `${RELEASE_ROOT}/layers/${scenario}/${horizon}.pmtiles`,
  ).sort());
  expect(boundary.forbidden).toEqual([]);
});

test("corrupt real COG range is a technical integrity failure and preserves the accepted result", async ({ page }, testInfo) => {
  await page.goto("/");
  await ready(page);
  await selectSettlement(page, "Málaga", /Málaga.*Andalucía, ES/i);
  await page.getByRole("radio", { name: /ssp5-85/ }).check();
  await expectAvailable(page, PROJECTION_MATRIX[7]);

  let mutated = false;
  await page.route(`**${RELEASE_ROOT}/analysis/ssp5-85/2100.tif`, async (route) => {
    if (route.request().method() !== "GET" || !route.request().headers().range || mutated) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const bytes = await response.body();
    bytes[Math.min(32, bytes.length - 1)] ^= 0x01;
    mutated = true;
    await route.fulfill({ response, body: bytes });
  });

  await page.getByRole("radio", { name: "2100", exact: true }).check();
  await expect(panel(page)).toHaveAttribute("data-phase", "integrity-error");
  await expect(page.locator('[role="alert"][data-technical-error="IntegrityFailed"]')).toContainText(
    "Technical failure — not a DataUnavailable scientific outcome",
  );
  await expect(outcome(page)).toHaveAttribute("data-outcome", "ProjectionAvailable");
  await expect(outcome(page)).toContainText("Previous accepted result");
  await expect(outcome(page)).toContainText("0.230 m");
  await expect(page.getByRole("heading", { name: "Model data unavailable for this point" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: /interactive visual map/i })).toHaveAttribute(
    "data-artifact-id",
    "projection-ssp5-85-2050-pmtiles",
  );
  await expect(page.getByRole("button", { name: /retry exact selection/i })).toBeDisabled();
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "integrity-failure");
  expect(mutated).toBe(true);
});

test("one-time 503 recovers only after explicit same-selection retry", async ({ page }, testInfo) => {
  await page.goto("/");
  await ready(page);
  await selectSettlement(page, "Málaga", /Málaga.*Andalucía, ES/i);
  await page.getByRole("radio", { name: /ssp1-26/ }).check();
  await expectAvailable(page, PROJECTION_MATRIX[1]);

  let failedOnce = false;
  await page.route(`**${RELEASE_ROOT}/analysis/ssp1-26/2100.tif`, async (route) => {
    if (!failedOnce && route.request().method() === "HEAD") {
      failedOnce = true;
      await route.fulfill({ status: 503, contentType: "text/plain", body: "temporary" });
      return;
    }
    await route.continue();
  });
  await page.getByRole("radio", { name: "2100", exact: true }).check();
  await expect(panel(page)).toHaveAttribute("data-phase", "technical-error");
  await expect(page.locator('[role="alert"][data-technical-error="FetchFailed"]')).toContainText(
    "not a DataUnavailable scientific outcome",
  );
  await expect(outcome(page)).toContainText("Previous accepted result");
  await expect(outcome(page)).toContainText("0.194 m");
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "transient-delivery-failure");

  const retry = page.getByRole("button", { name: /retry exact selection/i });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expectAvailable(page, PROJECTION_MATRIX[2]);
  await expectNoSeriousAxeFindings(page);
  expect(failedOnce).toBe(true);
});

test("rapid control and map commands cannot publish stale mixed state", async ({ page }, testInfo) => {
  await page.goto("/?campaign=issue-59");
  await ready(page);
  await selectSettlement(page, "Málaga", /Málaga.*Andalucía, ES/i);
  await page.getByRole("radio", { name: /ssp5-85/ }).check();
  await expectAvailable(page, PROJECTION_MATRIX[7]);
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp5-85-2050-pmtiles");

  let releaseRange: (() => void) | undefined;
  const rangeGate = new Promise<void>((resolve) => { releaseRange = resolve; });
  let delayed = false;
  await page.route(`**${RELEASE_ROOT}/analysis/ssp5-85/2100.tif`, async (route) => {
    if (!delayed && route.request().method() === "GET" && route.request().headers().range) {
      delayed = true;
      await rangeGate;
    }
    await route.continue().catch(() => undefined);
  });
  await page.getByRole("radio", { name: "2100", exact: true }).check();
  await expect(panel(page)).toHaveAttribute("data-phase", "updating");
  await expect(page.locator("[data-flight-phase='result']")).toBeVisible();
  await expect(page.locator(".flight-progress")).toHaveCount(0);
  await expect(page.getByText(/flying to the selected point/i)).toHaveCount(0);
  await expect(page.getByRole("region", { name: /release-scoped source-grid visualization/i })).toHaveAttribute(
    "data-journey-active",
    "false",
  );

  await page.getByRole("button", { name: /select coordinate at source extent centre/i }).click();
  releaseRange?.();

  await expect(panel(page)).toHaveAttribute("data-phase", "result");
  await expect(outcome(page)).toHaveAttribute("data-outcome", "OutOfScope");
  await expect(outcome(page).getByRole("heading", { name: "Outside the coastal analysis area" })).toBeVisible();
  await expect(outcome(page)).toContainText("Selected point");
  await expect(page.getByRole("radio", { name: /ssp5-85/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: "2050", exact: true })).toBeChecked();
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp5-85-2050-pmtiles");
  await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(
    "Accepted result visualization · ssp5-85 · 2050 · Central · q0.5",
  );
  await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText("Selected coordinate:");

  await page.getByRole("button", { name: /share accepted result/i }).click();
  const shared = new URL(page.url());
  expect(shared.searchParams.get("scenario")).toBe("ssp5-85");
  expect(shared.searchParams.get("horizon")).toBe("2050");
  expect(shared.searchParams.get("place")).toBeNull();
  expect(shared.searchParams.get("campaign")).toBe("issue-59");
  await expectNoSeriousAxeFindings(page);
  await attachStableState(page, testInfo, "race-final-atomic-state");
  expect(delayed).toBe(true);
});

test("share, reload, popstate, reset, and release scope preserve one URL selection", async ({ page }) => {
  await page.goto("/?campaign=issue-59");
  await ready(page);
  await selectSettlement(page, "Málaga", /Málaga.*Andalucía, ES/i);
  await page.getByRole("button", { name: /share accepted result/i }).click();
  const sharedUrl = page.url();
  const shared = new URL(sharedUrl);
  expect(Object.fromEntries(shared.searchParams)).toMatchObject({
    campaign: "issue-59",
    release: RELEASE_ID,
    scenario: "ssp2-45",
    horizon: "2050",
    place: "geonames:900000001",
    lat: "36.7213",
    lon: "-4.4214",
  });

  await page.reload();
  await expectAvailable(page, PROJECTION_MATRIX[4]);
  await expect(outcome(page)).toContainText("geonames:900000001");

  await page.evaluate(() => {
    history.pushState({}, "", "/?campaign=issue-59");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(panel(page)).toHaveAttribute("data-phase", "ready");
  await page.goBack();
  await expectAvailable(page, PROJECTION_MATRIX[4]);

  await page.getByRole("button", { name: /reset selection/i }).click();
  await expect(panel(page)).toHaveAttribute("data-phase", "ready");
  const resetUrl = new URL(page.url());
  expect(resetUrl.searchParams.get("campaign")).toBe("issue-59");
  for (const key of ["release", "scenario", "horizon", "place", "lat", "lon"]) {
    expect(resetUrl.searchParams.has(key)).toBe(false);
  }

  await page.goto(sharedUrl.replace(RELEASE_ID, "wrong-release"));
  await expect(page.getByRole("alert")).toContainText("Share or navigation failed");
  await expect(page.getByRole("alert")).toContainText("technical failure, not a scientific outcome");
  await expect(outcome(page)).toHaveCount(0);
  await expectNoSeriousAxeFindings(page);
});

test("camera motion can be skipped without cancelling or fabricating the assessment", async ({ page }, testInfo) => {
  let releaseLookup: (() => void) | undefined;
  const lookupGate = new Promise<void>((resolve) => { releaseLookup = resolve; });
  let lookupHeld = false;
  await page.route(`**${RELEASE_ROOT}/analysis/ssp2-45/2050.tif`, async (route) => {
    if (lookupHeld) {
      await route.continue();
      return;
    }
    lookupHeld = true;
    await lookupGate;
    await route.continue();
  });

  await page.goto("/");
  await ready(page);
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.fill("Málaga");
  await page.getByRole("option", { name: /Málaga.*Andalucía, ES/i }).click();
  await expect(page.locator("[data-flight-phase='transition']")).toBeVisible();
  await expect(page.getByText(/selected place accepted.*lookup is in progress/i)).toBeFocused();
  await expect(outcome(page)).toHaveCount(0);

  const skipMotion = page.getByRole("button", { name: "Skip motion" });
  if (testInfo.project.name === "reduced-motion-chromium") {
    await expect(skipMotion).toHaveCount(0);
    await expect(page.getByText(/camera motion reduced/i)).toBeVisible();
  } else {
    await expect(skipMotion).toBeVisible();
    await skipMotion.click();
    await expect(page.locator("[data-flight-phase='transition']")).toBeVisible();
    await expect(page.getByText(/camera motion skipped/i)).toBeVisible();
    await expect(outcome(page)).toHaveCount(0);
  }

  releaseLookup?.();
  await expectAvailable(page, PROJECTION_MATRIX[4]);
  await expect(outcome(page).getByRole("heading", {
    name: "Projected regional sea-level change available",
  })).toBeFocused();
  await page.getByRole("button", { name: /reset selection and choose another place/i }).click();
  await expect(page.getByRole("combobox", { name: /find a city, town, or village/i })).toBeFocused();
});

test("a superseded search response cannot replace the newest Worker query", async ({ page }) => {
  await page.addInitScript(() => {
    const NativeWorker = window.Worker;
    class DelayedQueryWorker extends NativeWorker {
      postMessage(message: unknown, transfer?: Transferable[]): void {
        const send = (): void => {
          if (transfer) super.postMessage(message, transfer);
          else super.postMessage(message);
        };
        const request = message as { readonly kind?: string; readonly query?: string };
        if (request.kind === "query" && request.query === "Málaga") {
          (window as unknown as { __delayedSearchQuerySeen: boolean }).__delayedSearchQuerySeen = true;
          window.setTimeout(send, 180);
          return;
        }
        send();
      }
    }
    Object.defineProperty(window, "Worker", { configurable: true, value: DelayedQueryWorker });
  });

  await page.goto("/");
  await ready(page);
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.fill("Málaga");
  await page.waitForFunction(() =>
    Boolean((window as unknown as { __delayedSearchQuerySeen?: boolean }).__delayedSearchQuerySeen));
  await search.fill("Springfield");
  await expect(page.getByRole("option", { name: /Springfield North.*AA/i })).toBeVisible();
  await page.waitForTimeout(250);
  await expect(search).toHaveValue("Springfield");
  await expect(page.getByRole("option", { name: /Málaga.*Andalucía, ES/i })).toHaveCount(0);

  await page.getByRole("option", { name: /Springfield North.*AA/i }).click();
  await expect(panel(page)).toHaveAttribute("data-phase", "result");
  await expect(outcome(page)).toHaveAttribute("data-outcome", "OutOfScope");
  await expect(outcome(page)).toContainText("Selected settlement: geonames:900000003");
});

test("keyboard-only search, radios, dialog focus, and reduced motion remain operable", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.focus();
  await page.keyboard.type("Málaga");
  await expect(search).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Enter");
  await expectAvailable(page, PROJECTION_MATRIX[4]);
  await expectThreeOptionSegmentedRow(page, /emissions scenario/i);
  await expectThreeOptionSegmentedRow(page, /absolute horizon/i);

  const currentScenario = page.getByRole("radio", { name: /ssp2-45/ });
  await currentScenario.focus();
  await page.keyboard.press("ArrowRight");
  await expectAvailable(page, PROJECTION_MATRIX[7]);

  const disclosure = page.locator("summary", { hasText: "Limitations, method and release identity" });
  await disclosure.focus();
  await page.keyboard.press("Enter");
  await expect(disclosure.locator("xpath=..")).toHaveAttribute("open", "");

  const methodology = page.getByRole("button", { name: /methodology and sources/i });
  await methodology.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Methodology and data" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: /close methodology/i })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(methodology).toBeFocused();

  await expectNoSeriousAxeFindings(page);
});
