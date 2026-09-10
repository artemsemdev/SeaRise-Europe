import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const baseURL = process.env.SEARISE_ATLAS_URL ?? "http://127.0.0.1:4181";
const screenshotDir = resolve(import.meta.dirname, "../../../../.cache/atlas-qa/experience");
const evidenceByPage = new WeakMap<Page, BrowserEvidence>();

type Protection = "unprotected" | "protected";
type Year = 2030 | 2050 | 2100;
type PointStatus = "flooded" | "zero" | "unknown";

interface InspectionResult {
  readonly year: Year;
  readonly status: PointStatus;
  readonly depthMeters: number | null;
}

interface Inspection {
  readonly coordinates: [number, number];
  readonly protection: Protection;
  readonly cellSizeMeters: number;
  readonly results: InspectionResult[];
}

interface InspectionRequest {
  readonly url: string;
  readonly point: [number, number];
  readonly protection: string | null;
}

interface CameraSnapshot {
  readonly center: [number, number];
  readonly zoom: number;
  readonly pitch: number;
  readonly bearing: number;
  readonly moving: boolean;
  readonly styleLoaded: boolean;
  readonly tilesLoaded: boolean;
}

interface BrowserEvidence {
  readonly externalRequests: string[];
  readonly pageErrors: string[];
  readonly consoleErrors: string[];
  readonly pendingConsoleErrors: Promise<void>[];
  readonly inspectionRequests: InspectionRequest[];
  readonly inspections: Inspection[];
  readonly pendingInspections: Promise<void>[];
  readonly tileRequests: string[];
  readonly expectedNetworkErrorPaths: string[];
}

function isLoopbackRequest(rawUrl: string): boolean {
  const url = new URL(rawUrl);
  return url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
}

async function installDisconnectedInternetBoundary(context: BrowserContext, page: Page): Promise<BrowserEvidence> {
  const evidence: BrowserEvidence = {
    externalRequests: [], pageErrors: [], consoleErrors: [], pendingConsoleErrors: [],
    inspectionRequests: [], inspections: [], pendingInspections: [], tileRequests: [], expectedNetworkErrorPaths: [],
  };
  page.on("pageerror", (error) => evidence.pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    evidence.pendingConsoleErrors.push((async () => {
      const details = await Promise.all(message.args().map(async (argument) =>
        argument.evaluate((value) => value instanceof Error ? `${value.name}: ${value.message}` : String(value))
          .catch(() => message.text())
      ));
      const location = message.location();
      evidence.consoleErrors.push(`${details.join(" ")} (${location.url}:${location.lineNumber}:${location.columnNumber})`);
    })());
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/atlas-data/inspect") {
      evidence.inspectionRequests.push({
        url: url.href,
        point: [Number(url.searchParams.get("lon")), Number(url.searchParams.get("lat"))],
        protection: url.searchParams.get("defenses"),
      });
    }
    if (/\/atlas-data\/tiles\/(?:2030|2050|2100)\/(?:unprotected|protected)\/\d+\/\d+\/\d+\.png$/u.test(url.pathname)) {
      evidence.tileRequests.push(url.href);
    }
  });
  page.on("response", (response) => {
    if (new URL(response.url()).pathname !== "/atlas-data/inspect" || !response.ok()) return;
    evidence.pendingInspections.push((async () => {
      const value = await response.json() as Inspection;
      evidence.inspections.push(value);
    })());
  });
  await context.route("**/*", async (route) => {
    if (isLoopbackRequest(route.request().url())) {
      await route.continue();
      return;
    }
    evidence.externalRequests.push(route.request().url());
    await route.abort("internetdisconnected");
  });
  return evidence;
}

async function cameraSnapshot(page: Page): Promise<CameraSnapshot> {
  return page.evaluate(() => {
    type MapHook = {
      getCenter(): { lng: number; lat: number };
      getZoom(): number;
      getPitch(): number;
      getBearing(): number;
      isMoving(): boolean;
      isStyleLoaded(): boolean;
      areTilesLoaded(): boolean;
    };
    const map = (window as typeof window & { __SEARISE_ATLAS_MAP__?: MapHook }).__SEARISE_ATLAS_MAP__;
    if (!map) throw new Error("The opt-in MapLibre QA hook is unavailable.");
    const center = map.getCenter();
    return {
      center: [center.lng, center.lat], zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing(),
      moving: map.isMoving(), styleLoaded: map.isStyleLoaded(),
      tilesLoaded: map.areTilesLoaded(),
    };
  });
}

async function waitForSettledMap(page: Page): Promise<CameraSnapshot> {
  await expect.poll(() => page.evaluate(() =>
    Boolean((window as typeof window & { __SEARISE_ATLAS_MAP__?: unknown }).__SEARISE_ATLAS_MAP__)
  ), { timeout: 30_000, message: "the opt-in MapLibre QA hook was not installed" }).toBe(true);
  await expect.poll(async () => {
    const snapshot = await cameraSnapshot(page);
    return snapshot.styleLoaded && snapshot.tilesLoaded && !snapshot.moving;
  }, { timeout: 30_000, message: "the map camera and its current tiles did not settle" }).toBe(true);
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  return cameraSnapshot(page);
}

function expectSameCamera(actual: CameraSnapshot, expected: CameraSnapshot): void {
  expect(actual.center[0]).toBeCloseTo(expected.center[0], 5);
  expect(actual.center[1]).toBeCloseTo(expected.center[1], 5);
  expect(actual.zoom).toBeCloseTo(expected.zoom, 5);
  expect(actual.pitch).toBeCloseTo(expected.pitch, 5);
  expect(actual.bearing).toBeCloseTo(expected.bearing, 5);
}

function expectSameMobileCamera(actual: CameraSnapshot, expected: CameraSnapshot): void {
  expect(actual.center[0]).toBeCloseTo(expected.center[0], 2);
  expect(actual.center[1]).toBeCloseTo(expected.center[1], 2);
  expect(actual.zoom).toBeCloseTo(expected.zoom, 2);
}

function assertInspectionContract(inspection: Inspection, protection: Protection): void {
  expect(inspection.protection).toBe(protection);
  expect(inspection.cellSizeMeters).toBe(25);
  expect(inspection.coordinates).toHaveLength(2);
  expect(inspection.coordinates.every(Number.isFinite)).toBe(true);
  expect(inspection.results.map((result) => result.year).sort()).toEqual([2030, 2050, 2100]);
  for (const result of inspection.results) {
    if (result.status === "flooded") {
      expect(result.depthMeters).toBeGreaterThan(0);
    } else if (result.status === "zero") {
      expect(result.depthMeters).toBe(0);
    } else {
      expect(result.status).toBe("unknown");
      expect(result.depthMeters).toBeNull();
    }
  }
}

function resultLabel(result: InspectionResult): RegExp {
  if (result.status === "unknown") return /No usable data/u;
  if (result.status === "zero") return /No flooding modeled/u;
  return result.depthMeters! < 0.1 ? /<0\.1 m depth/u : new RegExp(`${result.depthMeters!.toFixed(1)} m depth`, "u");
}

async function waitForInspection(page: Page, evidence: BrowserEvidence, afterCount = 0): Promise<Inspection> {
  await expect.poll(async () => {
    await Promise.all(evidence.pendingInspections);
    return evidence.inspections.length;
  }, { timeout: 30_000, message: "the selected point did not return a native inspection result" }).toBeGreaterThan(afterCount);
  const inspection = evidence.inspections.at(-1)!;
  const selectedYear = Number(await page.getByRole("slider", { name: "Projection year" }).getAttribute("aria-valuetext")) as Year;
  const result = inspection.results.find((item) => item.year === selectedYear)!;
  const card = page.getByTestId("point-inspection");
  await expect(card).toHaveAttribute("data-state", result.status);
  await expect(card).toContainText(resultLabel(result));
  if (result.status === "unknown") await expect(card).toContainText("Unknown does not mean dry.");
  if (result.status === "zero") await expect(card).toContainText("A valid zero in this scenario, not a safety assessment.");
  if (result.status === "flooded") await expect(card).toContainText("Modeled flooding at high tide");
  return inspection;
}

async function clickMap(page: Page, xRatio: number, yRatio: number): Promise<void> {
  const box = await page.locator("canvas.maplibregl-canvas").boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  await page.mouse.click(box.x + box.width * xRatio, box.y + box.height * yRatio);
}

test.beforeEach(async ({ context, page }) => {
  mkdirSync(screenshotDir, { recursive: true });
  evidenceByPage.set(page, await installDisconnectedInternetBoundary(context, page));
});

test.afterEach(async ({ page }) => {
  const evidence = evidenceByPage.get(page);
  await Promise.all([...(evidence?.pendingConsoleErrors ?? []), ...(evidence?.pendingInspections ?? [])]);
  expect(evidence?.externalRequests, "the experience attempted a non-loopback request").toEqual([]);
  expect(evidence?.pageErrors, "the experience raised an uncaught JavaScript error").toEqual([]);
  const unexpectedConsoleErrors = evidence?.consoleErrors.filter((message) =>
    !evidence.expectedNetworkErrorPaths.some((path) => message.includes(path))
  );
  expect(unexpectedConsoleErrors, "the experience logged an unexpected console error").toEqual([]);
});

test("point inspection, comparison, camera, and share state remain coherent", async ({ context, page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL });
  await page.goto("/?qa=map&city=geonames%3A2747891&year=2050&defenses=unprotected&flooding=on", {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByRole("heading", { level: 1, name: "Rotterdam", exact: true })).toBeVisible();
  const evidence = evidenceByPage.get(page)!;
  const cityInspection = await waitForInspection(page, evidence);
  assertInspectionContract(cityInspection, "unprotected");
  await expect(page.getByRole("definition")).toHaveCount(3);
  await expect(page.getByText("One 25 m model cell, not the whole city or a property assessment.")).toBeVisible();

  await page.getByRole("button", { name: "Close point result" }).click();
  await expect(page.getByTestId("point-inspection")).toBeHidden();
  const inspectionsBeforeClick = evidence.inspections.length;
  await clickMap(page, 0.68, 0.55);
  const clickedInspection = await waitForInspection(page, evidence, inspectionsBeforeClick);
  assertInspectionContract(clickedInspection, "unprotected");
  const clickedRequest = evidence.inspectionRequests.at(-1)!;
  expect(clickedRequest.protection).toBe("unprotected");
  expect(clickedRequest.point.every(Number.isFinite)).toBe(true);
  expect(clickedInspection.coordinates[0]).toBeCloseTo(clickedRequest.point[0], 6);
  expect(clickedInspection.coordinates[1]).toBeCloseTo(clickedRequest.point[1], 6);
  await expect(page).toHaveURL(/point=-?\d+\.\d+%2C-?\d+\.\d+/u);

  const comparisonCamera = await waitForSettledMap(page);
  await page.getByRole("button", { name: "Compare 2030 & 2100" }).click();
  await expect(page.getByRole("button", { name: "Exit comparison" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".time-heading")).toContainText("Compare 2030 & 2100");
  await expect(page.getByRole("slider", { name: "Projection year" })).toHaveAttribute("aria-valuetext", "2100");
  await expect(page.locator(".atlas-map")).toHaveAttribute("data-layer", "ssp585-2100-unprotected");
  expectSameCamera(await waitForSettledMap(page), comparisonCamera);

  await page.getByRole("button", { name: "2030", exact: true }).click();
  await expect(page.locator(".atlas-map")).toHaveAttribute("data-layer", "ssp585-2030-unprotected");
  expectSameCamera(await waitForSettledMap(page), comparisonCamera);
  await page.getByRole("button", { name: "2100", exact: true }).click();
  await expect(page.locator(".atlas-map")).toHaveAttribute("data-layer", "ssp585-2100-unprotected");
  expectSameCamera(await waitForSettledMap(page), comparisonCamera);
  expect(evidence.tileRequests.some((url) => url.includes("/tiles/2030/unprotected/"))).toBe(true);
  expect(evidence.tileRequests.some((url) => url.includes("/tiles/2100/unprotected/"))).toBe(true);

  const inspectionsBeforeProtection = evidence.inspections.length;
  const defenses = page.getByRole("group", { name: "Coastal defenses" });
  await defenses.getByRole("button", { name: "High protection" }).click();
  await expect(defenses.getByRole("button", { name: "High protection" })).toHaveAttribute("aria-pressed", "true");
  const protectedInspection = await waitForInspection(page, evidence, inspectionsBeforeProtection);
  assertInspectionContract(protectedInspection, "protected");
  expect(protectedInspection.coordinates[0]).toBeCloseTo(clickedInspection.coordinates[0], 6);
  expect(protectedInspection.coordinates[1]).toBeCloseTo(clickedInspection.coordinates[1], 6);

  await page.getByRole("button", { name: "Zoom in" }).click();
  const sharedCamera = await waitForSettledMap(page);
  await page.getByRole("button", { name: "Copy link to this view" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Link copied" })).toBeVisible();
  const sharedUrl = page.url();
  const shared = new URL(sharedUrl);
  expect(shared.searchParams.get("city")).toBe("geonames:2747891");
  expect(shared.searchParams.get("year")).toBe("2100");
  expect(shared.searchParams.get("defenses")).toBe("protected");
  expect(shared.searchParams.get("compare")).toBe("on");
  expect(shared.searchParams.get("point")).not.toBeNull();
  expect(shared.searchParams.get("view")).not.toBeNull();
  const sharedView = shared.searchParams.get("view")!.split(",").map(Number);
  expect(sharedView[0]).toBeCloseTo(sharedCamera.center[0], 5);
  expect(sharedView[1]).toBeCloseTo(sharedCamera.center[1], 5);
  expect(sharedView[2]).toBeCloseTo(sharedCamera.zoom, 3);
  await page.screenshot({ path: resolve(screenshotDir, "desktop-rotterdam-point-compare.png") });

  const inspectionsBeforeReload = evidence.inspections.length;
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Rotterdam", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Exit comparison" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".time-heading")).toContainText("Compare 2030 & 2100");
  const restored = await waitForInspection(page, evidence, inspectionsBeforeReload);
  assertInspectionContract(restored, "protected");
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  expect(page.url()).toBe(sharedUrl);
  await expect(page).toHaveURL(/compare=on/u);

  await page.getByRole("button", { name: "Exit comparison" }).click();
  await expect(page).not.toHaveURL(/compare=on/u);
  await expect(page.getByRole("button", { name: "Compare 2030 & 2100" })).toHaveAttribute("aria-pressed", "false");
});

test("a failed point clears after inspecting elsewhere and returning", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  evidenceByPage.get(page)!.expectedNetworkErrorPaths.push("/atlas-data/inspect");
  const failInspection = async (route: Route) => {
    await route.fulfill({ status: 503, contentType: "application/json", json: { error: "unavailable" } });
  };
  await page.route("**/atlas-data/inspect**", failInspection);
  await page.goto("/?qa=map&city=geonames%3A2747891&year=2050&defenses=unprotected&flooding=on", {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByTestId("point-inspection")).toHaveAttribute("data-state", "error");
  await page.unroute("**/atlas-data/inspect**", failInspection);
  await expect(page.getByTestId("atlas-map")).toBeVisible();
  await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible();

  await page.getByRole("button", { name: "Close point result" }).click();
  const evidence = evidenceByPage.get(page)!;
  await clickMap(page, 0.68, 0.55);
  const otherPoint = await waitForInspection(page, evidence);
  assertInspectionContract(otherPoint, "unprotected");
  await expect(page.getByTestId("point-inspection")).not.toHaveAttribute("data-state", "error");

  const beforeReturn = evidence.inspections.length;
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Rotterdam");
  await page.getByRole("option", { name: /^Rotterdam\s+Netherlands$/iu }).click();
  const returned = await waitForInspection(page, evidence, beforeReturn);
  expect(returned.coordinates[0]).toBeCloseTo(4.47917, 5);
  expect(returned.coordinates[1]).toBeCloseTo(51.9225, 5);
  await expect(page.getByTestId("point-inspection")).not.toHaveAttribute("data-state", "error");
});

test("a point-only link restores its camera and can then navigate to a city", async ({ context, page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL });
  const olbia: [number, number] = [9.502876, 40.921280];
  const point = olbia.join(",");
  const view = `${point},12.0000`;
  await page.goto(`/?qa=map&year=2030&defenses=unprotected&flooding=on&point=${point}&view=${view}`, {
    waitUntil: "domcontentloaded",
  });
  const evidence = evidenceByPage.get(page)!;
  const initial = await waitForInspection(page, evidence);
  assertInspectionContract(initial, "unprotected");
  expect(initial.results.map((result) => result.status)).toEqual(["flooded", "flooded", "flooded"]);
  expect(initial.results.map((result) => result.depthMeters)).toEqual([...initial.results.map((result) => result.depthMeters)].sort((a, b) => a! - b!));
  const camera = await waitForSettledMap(page);
  expect(camera.center[0]).toBeCloseTo(olbia[0], 5);
  expect(camera.center[1]).toBeCloseTo(olbia[1], 5);
  expect(camera.zoom).toBeCloseTo(12, 3);
  await page.screenshot({ path: resolve(screenshotDir, "desktop-olbia-native-point.png") });
  await page.getByRole("button", { name: "Copy link to this view" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Link copied" })).toBeVisible();
  const sharedUrl = page.url();
  expect(new URL(sharedUrl).searchParams.get("city")).toBeNull();

  const beforeReload = evidence.inspections.length;
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForInspection(page, evidence, beforeReload);
  expect(page.url()).toBe(sharedUrl);
  const qaUrl = new URL(sharedUrl);
  qaUrl.searchParams.set("qa", "map");
  const beforeQaNavigation = evidence.inspections.length;
  await page.goto(qaUrl.href, { waitUntil: "domcontentloaded" });
  await waitForInspection(page, evidence, beforeQaNavigation);
  expectSameCamera(await waitForSettledMap(page), camera);

  await page.getByRole("button", { name: "European overview" }).click();
  await expect(page).not.toHaveURL(/point=/u);
  await expect(page.locator("#city-title")).toHaveText("Europe");
  const overviewCamera = await waitForSettledMap(page);
  const minimumZoom = await page.evaluate(() => {
    const map = (window as typeof window & { __SEARISE_ATLAS_MAP__: { getMinZoom(): number } }).__SEARISE_ATLAS_MAP__;
    return map.getMinZoom();
  });
  expect(overviewCamera.zoom).toBeCloseTo(minimumZoom, 3);

  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Venice");
  await page.getByRole("option", { name: /^Venice\s+Italy$/iu }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Venice", exact: true })).toBeFocused();
  const cityCamera = await waitForSettledMap(page);
  expect(Math.abs(cityCamera.center[0] - camera.center[0])).toBeGreaterThan(0.5);
  await expect(page).toHaveURL(/city=geonames%3A3164603/u);
  await expect(page).not.toHaveURL(/point=/u);
});

test("keyboard search communicates its active match and selects without losing focus", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Ven");
  const venice = page.getByRole("option", { name: /^Venice\s+Italy$/iu });
  await expect(venice).toBeVisible({ timeout: 15_000 });
  await expect(venice.locator("mark")).toHaveText(/Ven/iu);
  const firstActive = await search.getAttribute("aria-activedescendant");
  expect(firstActive).toBeTruthy();
  await search.press("ArrowDown");
  expect(await search.getAttribute("aria-activedescendant")).not.toBe(firstActive);
  await search.press("ArrowUp");
  const activeId = await search.getAttribute("aria-activedescendant");
  expect(activeId).toBeTruthy();
  const selectedName = await page.locator('[role="option"][aria-selected="true"] .search-name').innerText();
  await search.press("Enter");
  const title = page.getByRole("heading", { level: 1, name: selectedName, exact: true });
  await expect(title).toBeFocused();

  await search.focus();
  await search.fill("Rot");
  await expect(page.getByRole("option", { name: /^Rotterdam\s+Netherlands$/iu })).toBeVisible();
  await search.press("Escape");
  await expect(search).toBeFocused();
  await expect(search).toHaveAttribute("aria-expanded", "false");

  const inspectCenter = page.getByRole("button", { name: "Inspect map center" });
  await inspectCenter.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/point=/u);
  await expect(page.getByTestId("point-inspection")).not.toHaveAttribute("data-state", "loading", { timeout: 30_000 });
});

test("mobile point summary survives expanding and collapsing its detail panel", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-mobile");
  await page.goto("/?qa=map&city=geonames%3A2747891&year=2100&defenses=unprotected&flooding=on", {
    waitUntil: "domcontentloaded",
  });
  const evidence = evidenceByPage.get(page)!;
  const inspection = await waitForInspection(page, evidence);
  assertInspectionContract(inspection, "unprotected");
  const panel = page.getByTestId("exploration-panel");
  const more = page.getByRole("button", { name: "More detail" });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("point-inspection")).toBeVisible();
  await expect(page.getByRole("definition")).toHaveCount(0);
  const mapBox = await page.getByTestId("atlas-map").boundingBox();
  expect(mapBox?.height).toBeGreaterThan(360);
  const pointBox = await page.getByRole("region", { name: "Selected point", exact: true }).boundingBox();
  expect(pointBox?.y, "mobile results belong below the map, not on top of it").toBeGreaterThanOrEqual(mapBox!.y + mapBox!.height);
  const collapsedCamera = await waitForSettledMap(page);

  await more.click();
  const less = page.getByRole("button", { name: "Less detail" });
  await expect(less).toHaveAttribute("aria-expanded", "true");
  await expect(panel).toHaveClass(/is-expanded/u);
  await expect(page.getByRole("definition")).toHaveCount(3);
  await expect(page.getByRole("group", { name: "Coastal defenses" })).toBeVisible();
  await expect(page.getByLabel("Map legend")).toBeVisible();
  expectSameMobileCamera(await waitForSettledMap(page), collapsedCamera);
  await page.screenshot({ path: resolve(screenshotDir, "mobile-rotterdam-point-expanded.png") });

  const state = await page.getByTestId("point-inspection").getAttribute("data-state");
  await less.click();
  await expect(more).toBeFocused();
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("point-inspection")).toHaveAttribute("data-state", state!);
  expectSameMobileCamera(await waitForSettledMap(page), collapsedCamera);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: resolve(screenshotDir, "mobile-rotterdam-point-collapsed.png") });
});

test("selected point stays in the sidebar and leaves the map center interactive", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await page.setViewportSize({ width: 3039, height: 1647 });
  await page.goto("/?qa=map&year=2050&point=12.15966,45.40025&view=12.15966,45.40025,8.2");
  const evidence = evidenceByPage.get(page)!;
  await waitForInspection(page, evidence);
  const inspector = page.getByRole("region", { name: "Selected point", exact: true });
  const story = page.locator(".atlas-story");

  async function expectDocked(): Promise<void> {
    const layout = await page.evaluate(() => {
      const sidebar = document.querySelector(".atlas-story")!;
      const result = document.querySelector('[aria-label="Selected point"]')!;
      const sidebarBox = sidebar.getBoundingClientRect();
      const resultBox = result.getBoundingClientRect();
      const timeline = document.querySelector(".atlas-time")!.getBoundingClientRect();
      const center = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
      return {
        contained: sidebar.contains(result),
        left: resultBox.left, right: resultBox.right,
        sidebarLeft: sidebarBox.left, sidebarRight: sidebarBox.right,
        sidebarBottom: sidebarBox.bottom, timelineTop: timeline.top,
        sharesTimelineColumns: sidebarBox.right > timeline.left && sidebarBox.left < timeline.right,
        viewportWidth: innerWidth,
        centerIsMap: Boolean(center?.closest(".atlas-geography")),
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    expect(layout.contained, "point results belong to the place sidebar").toBe(true);
    expect(layout.left).toBeGreaterThanOrEqual(layout.sidebarLeft);
    expect(layout.right).toBeLessThanOrEqual(layout.sidebarRight);
    expect(layout.sidebarRight).toBeLessThan(layout.viewportWidth * 0.45);
    expect(layout.centerIsMap, "the geographic center must remain available for map interaction").toBe(true);
    if (layout.sharesTimelineColumns) expect(layout.sidebarBottom + 8, "the sidebar must leave space above the timeline").toBeLessThanOrEqual(layout.timelineTop);
    expect(layout.documentWidth).toBe(layout.viewportWidth);
    await expect(inspector.locator(".point-summary strong")).toBeInViewport();
    await expect(inspector.getByRole("button", { name: "Close point result" })).toBeInViewport();
  }

  for (const viewport of [
    { width: 3039, height: 1647 }, { width: 1440, height: 900 },
    { width: 1024, height: 768 }, { width: 768, height: 1024 },
    { width: 924, height: 540 },
  ]) {
    await page.setViewportSize(viewport);
    await waitForSettledMap(page);
    await expectDocked();
    await page.screenshot({ path: resolve(screenshotDir, `point-sidebar-${viewport.width}x${viewport.height}.png`) });
  }

  await page.getByRole("button", { name: "Compare 2030 & 2100" }).click();
  await expectDocked();
  await page.getByRole("button", { name: "Exit comparison" }).click();
  await page.getByRole("button", { name: "High protection", exact: true }).scrollIntoViewIfNeeded();
  expect(await story.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await page.locator("canvas.maplibregl-canvas").focus();
  await page.keyboard.press("ArrowRight");
  await waitForSettledMap(page);
  const beforeInspect = evidence.inspections.length;
  await page.getByRole("button", { name: "Inspect map center" }).click();
  await waitForInspection(page, evidence, beforeInspect);
  await expect.poll(() => story.evaluate((element) => element.scrollTop)).toBe(0);
  await expectDocked();

  await page.getByRole("button", { name: "Close point result" }).click();
  await expect(inspector).toHaveCount(0);
  const beforeClick = evidence.inspections.length;
  await clickMap(page, 0.65, 0.5);
  await waitForInspection(page, evidence, beforeClick);
  await expectDocked();
  const selectedPoint = new URL(page.url()).searchParams.get("point");
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await waitForSettledMap(page);
  await page.locator("canvas.maplibregl-canvas").focus();
  await page.keyboard.press("ArrowRight");
  await waitForSettledMap(page);
  expect(new URL(page.url()).searchParams.get("point")).toBe(selectedPoint);
  await expectDocked();
});
