import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const baseURL = process.env.SEARISE_ATLAS_URL ?? "http://127.0.0.1:4181";
const screenshotDir = resolve(import.meta.dirname, "../../../../.cache/atlas-qa/screenshots");
const evidenceByPage = new WeakMap<Page, BrowserEvidence>();

type Year = 2030 | 2050 | 2100;
type Protection = "unprotected" | "protected";

interface RasterCounts {
  readonly validPixels: number;
  readonly floodPixels: number;
}

interface BrowserEvidence {
  readonly externalRequests: string[];
  readonly pageErrors: string[];
  readonly consoleErrors: string[];
  readonly pendingConsoleErrors: Promise<void>[];
  readonly tileRequests: string[];
  readonly pmtilesRequests: string[];
  readonly expectedNetworkErrorPaths: string[];
}

function isLoopbackRequest(rawUrl: string): boolean {
  const url = new URL(rawUrl);
  return url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
}

async function installDisconnectedInternetBoundary(context: BrowserContext, page: Page): Promise<BrowserEvidence> {
  const evidence: BrowserEvidence = {
    externalRequests: [], pageErrors: [], consoleErrors: [], pendingConsoleErrors: [],
    tileRequests: [], pmtilesRequests: [], expectedNetworkErrorPaths: [],
  };
  page.on("pageerror", (error) => evidence.pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    evidence.pendingConsoleErrors.push((async () => {
      const details = await Promise.all(message.args().map(async (argument) => argument.evaluate((value) => {
        if (value instanceof Error) return `${value.name}: ${value.message}`;
        if (value && typeof value === "object") {
          const fields = Object.fromEntries(Object.getOwnPropertyNames(value).map((key) => [key, Reflect.get(value, key)]));
          return JSON.stringify(fields);
        }
        return String(value);
      }).catch(() => message.text())));
      const location = message.location();
      evidence.consoleErrors.push(`${details.join(" ")} (${location.url}:${location.lineNumber}:${location.columnNumber})`);
    })());
  });
  page.on("request", (request) => {
    if (/\/atlas-data\/tiles\/(?:2030|2050|2100)\/(?:unprotected|protected)\/\d+\/\d+\/\d+\.png(?:\?|$)/u.test(request.url())) {
      evidence.tileRequests.push(request.url());
    }
    if (/\/atlas-data\/basemap\/protomaps-europe\.pmtiles(?:\?|$)/u.test(request.url())) {
      evidence.pmtilesRequests.push(request.url());
    }
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

async function expectAccessiblePage(page: Page): Promise<void> {
  const scan = await new AxeBuilder({ page }).analyze();
  const serious = scan.violations.filter((violation) =>
    violation.impact === "critical" || violation.impact === "serious"
  );
  expect(serious).toEqual([]);
}

function mapRoot(page: Page) {
  return page.locator(".atlas-map");
}

async function expectHeading(page: Page, place: string): Promise<void> {
  if (place === "Europe") {
    await expect(page.locator("#city-title")).toHaveText(place);
  } else {
    await expect(page.getByRole("heading", { level: 1, name: place, exact: true })).toBeVisible();
  }
}

async function waitForStableCanvas(page: Page): Promise<void> {
  const canvas = page.locator("canvas.maplibregl-canvas");
  let previous: Uint8Array | null = null;
  let stableSamples = 0;
  await expect.poll(async () => {
    const current = await canvas.screenshot();
    stableSamples = previous && current.equals(previous) ? stableSamples + 1 : 0;
    previous = current;
    return stableSamples;
  }, {
    timeout: 10_000,
    intervals: [100, 150, 250, 400],
    message: "the map camera and raster did not become visually stable",
  }).toBeGreaterThanOrEqual(2);
}

async function waitForRaster(
  page: Page,
  year: Year,
  protection: Protection,
  place = "Europe",
): Promise<RasterCounts> {
  await expectHeading(page, place);
  await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 30_000 });
  await expect(mapRoot(page)).toHaveAttribute("data-layer", `ssp585-${year}-${protection}`);
  await expect(page.locator("[data-testid='atlas-map']")).toHaveAttribute("data-year", String(year));
  await expect.poll(async () => {
    const [valid, flood] = await Promise.all([
      mapRoot(page).getAttribute("data-valid-pixels"),
      mapRoot(page).getAttribute("data-flood-pixels"),
    ]);
    return valid !== null && valid !== "" && flood !== null && flood !== "";
  }, { timeout: 30_000, message: "the current Europe raster did not publish settled viewport counts" }).toBe(true);
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  await waitForStableCanvas(page);
  await expect(page.getByRole("alert")).toHaveCount(0);
  const validPixels = Number(await mapRoot(page).getAttribute("data-valid-pixels"));
  const floodPixels = Number(await mapRoot(page).getAttribute("data-flood-pixels"));
  expect(Number.isSafeInteger(validPixels)).toBe(true);
  expect(Number.isSafeInteger(floodPixels)).toBe(true);
  expect(validPixels, "the viewport must contain real source values").toBeGreaterThan(0);
  expect(floodPixels).toBeGreaterThanOrEqual(0);
  expect(floodPixels).toBeLessThanOrEqual(validPixels);
  const evidence = evidenceByPage.get(page);
  await expect.poll(() => evidence?.tileRequests.some((url) =>
    url.includes(`/atlas-data/tiles/${year}/${protection}/`)
  ) ?? false, { timeout: 30_000, message: `no ${year} ${protection} raster tile was requested` }).toBe(true);
  return { validPixels, floodPixels };
}

async function chooseSearchResult(page: Page, query: string, optionName: RegExp, choose = false): Promise<void> {
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill(query);
  const option = page.getByRole("option", { name: optionName });
  await expect(option).toBeVisible({ timeout: 15_000 });
  if (choose) await option.click();
}

test.beforeEach(async ({ context, page }) => {
  mkdirSync(screenshotDir, { recursive: true });
  evidenceByPage.set(page, await installDisconnectedInternetBoundary(context, page));
});

test.afterEach(async ({ page }) => {
  const evidence = evidenceByPage.get(page);
  await Promise.all(evidence?.pendingConsoleErrors ?? []);
  const unexpectedConsoleErrors = evidence?.consoleErrors.filter((message) =>
    !evidence.expectedNetworkErrorPaths.some((path) => message.includes(path))
  );
  expect(evidence?.externalRequests, "the atlas attempted a non-loopback request").toEqual([]);
  expect(evidence?.pageErrors, "the atlas raised an uncaught JavaScript error").toEqual([]);
  expect(unexpectedConsoleErrors, "the atlas logged an unexpected console error").toEqual([]);
});

test("Europe journey uses real local rasters, canonical places, settings, and share state", async ({ context, page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const overviewCounts = await waitForRaster(page, 2050, "unprotected");
  expect(overviewCounts.validPixels).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: "Start with a coast", exact: true })).toBeVisible();
  await expect.poll(() => (evidenceByPage.get(page)?.pmtilesRequests.length ?? 0) > 0, {
    timeout: 30_000,
    message: "the authentic local Europe Protomaps archive was not requested",
  }).toBe(true);
  await page.screenshot({ path: resolve(screenshotDir, "desktop-europe-overview-2050.png") });

  await chooseSearchResult(page, "London", /^London\s+United Kingdom$/iu);
  await chooseSearchResult(page, "Gdansk", /^Gda(?:ń|n)sk\s+Poland$/iu);
  await chooseSearchResult(page, "Venice", /^Venice\s+Italy$/iu, true);
  await expectHeading(page, "Venice");
  await expect(page.locator(".atlas-country")).toContainText("Italy");
  await expect(page).toHaveURL(/city=geonames%3A3164603/u);
  const counts2050 = await waitForRaster(page, 2050, "unprotected", "Venice");
  const canvas2050 = await page.locator("canvas.maplibregl-canvas").screenshot();

  const slider = page.getByRole("slider", { name: "Projection year" });
  await slider.focus();
  await slider.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuetext", "2030");
  const counts2030 = await waitForRaster(page, 2030, "unprotected", "Venice");
  const canvas2030 = await page.locator("canvas.maplibregl-canvas").screenshot();

  await page.getByRole("button", { name: "2100", exact: true }).click();
  const counts2100 = await waitForRaster(page, 2100, "unprotected", "Venice");
  const canvas2100 = await page.locator("canvas.maplibregl-canvas").screenshot();
  expect(new Set([counts2030.floodPixels, counts2050.floodPixels, counts2100.floodPixels]).size,
    "each published horizon should expose a distinct real flood-pixel count").toBe(3);
  expect(canvas2030.equals(canvas2050), "the raster canvas did not change from 2030 to 2050").toBe(false);
  expect(canvas2050.equals(canvas2100), "the raster canvas did not change from 2050 to 2100").toBe(false);

  const sliderBox = await slider.boundingBox();
  expect(sliderBox).not.toBeNull();
  if (sliderBox) {
    await page.mouse.move(sliderBox.x + sliderBox.width - 2, sliderBox.y + sliderBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(sliderBox.x + sliderBox.width / 2, sliderBox.y + sliderBox.height / 2, { steps: 8 });
    await page.mouse.up();
  }
  await expect(slider).toHaveAttribute("aria-valuetext", "2050");
  await waitForRaster(page, 2050, "unprotected", "Venice");

  const defense = page.getByRole("group", { name: "Coastal defenses" });
  await defense.getByRole("button", { name: "High protection" }).click();
  await expect(defense.getByRole("button", { name: "High protection" })).toHaveAttribute("aria-pressed", "true");
  const protectedCounts = await waitForRaster(page, 2050, "protected", "Venice");
  expect(protectedCounts.validPixels).toBeGreaterThan(0);
  await expect(page.getByText("No mapped values in this area.")).toHaveCount(0);
  await expect(page).toHaveURL(/defenses=protected/u);
  expect(protectedCounts).not.toEqual(counts2050);

  const floodCanvas = await page.locator("canvas.maplibregl-canvas").screenshot();
  await page.getByRole("button", { name: "Hide flood layer" }).click();
  await expect(page.getByRole("button", { name: "Show flood layer" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".time-heading .map-loading")).toHaveText("");
  await expect(mapRoot(page)).toHaveAttribute("data-valid-pixels", "");
  await expect(mapRoot(page)).toHaveAttribute("data-flood-pixels", "");
  await expect(page).toHaveURL(/flooding=off/u);
  const basemapCanvas = await page.locator("canvas.maplibregl-canvas").screenshot();
  expect(basemapCanvas.equals(floodCanvas), "basemap comparison did not hide the raster layer").toBe(false);
  await page.getByRole("button", { name: "Show flood layer" }).click();
  await waitForRaster(page, 2050, "protected", "Venice");

  await page.getByRole("button", { name: "2100", exact: true }).click();
  await waitForRaster(page, 2100, "protected", "Venice");
  await page.getByRole("button", { name: "Play timeline" }).click();
  await expect(page.getByRole("button", { name: "Pause timeline" })).toBeVisible();
  await expect.poll(() => slider.getAttribute("aria-valuetext"), { timeout: 5_000 }).toBe("2030");
  await waitForRaster(page, 2030, "protected", "Venice");
  await page.getByRole("button", { name: "Pause timeline" }).click();

  const about = page.getByRole("button", { name: "About the map" });
  await about.click();
  const dialog = page.getByRole("dialog", { name: "About the data" });
  const close = dialog.getByRole("button", { name: "Close map information" });
  const methodology = dialog.getByRole("link", { name: /Read the CoCliCo methodology/i });
  await expect(dialog).toBeVisible();
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(methodology).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(about).toBeFocused();

  await page.getByRole("button", { name: "Copy link to this view" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Link copied" })).toBeVisible();
  const shareUrl = page.url();
  expect(shareUrl).toMatch(/city=geonames%3A3164603/u);
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForRaster(page, 2030, "protected", "Venice");
  expect(page.url()).toBe(shareUrl);
  await expectAccessiblePage(page);
  expect(await page.locator("body").innerText()).not.toMatch(/[\u0400-\u04ff]/u);
  await page.screenshot({ path: resolve(screenshotDir, "desktop-venice-shared.png"), fullPage: true });

  await page.goto("/?city=geonames%3A2747891&year=2050&defenses=unprotected&flooding=on", {
    waitUntil: "domcontentloaded",
  });
  await waitForRaster(page, 2050, "unprotected", "Rotterdam");
  await page.screenshot({ path: resolve(screenshotDir, "desktop-rotterdam-2050.png") });
});

test("catalog, unknown-place, and search failures have explicit local recovery", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  const failCatalog = async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", json: {} });
  };
  await page.route("**/atlas-data/manifest.json", failCatalog);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("alert")).toContainText("The real-local atlas catalog is invalid.");
  await page.unroute("**/atlas-data/manifest.json", failCatalog);
  await page.getByRole("button", { name: "Retry" }).click();
  await waitForRaster(page, 2050, "unprotected");

  evidenceByPage.get(page)?.expectedNetworkErrorPaths.push("/atlas-data/europe/place");
  await page.goto("/?city=geonames%3A999999999&year=2050&defenses=unprotected&flooding=on", {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByRole("alert")).toContainText("This place could not be found. Search for a city to continue.");
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await waitForRaster(page, 2050, "unprotected");
  await page.route("**/atlas-data/europe/search**", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", json: { error: "unavailable" } });
  }, { times: 1 });
  evidenceByPage.get(page)?.expectedNetworkErrorPaths.push("/atlas-data/europe/search");
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Venice");
  await expect(page.getByRole("alert")).toHaveText("Search could not load. Try typing your city again.");
  await search.fill("London");
  await expect(page.getByRole("option", { name: /^London\s+United Kingdom$/iu })).toBeVisible();
});

test("mobile Europe atlas keeps map space while details remain reachable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-mobile");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await waitForRaster(page, 2050, "unprotected");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const slider = page.getByRole("slider", { name: "Projection year" });
  await expect(slider).toBeInViewport();
  for (const year of [2030, 2050, 2100]) {
    await expect(page.getByRole("button", { name: String(year), exact: true })).toBeInViewport();
  }
  const panel = page.getByTestId("exploration-panel");
  const panelToggle = page.getByRole("button", { name: "More detail" });
  await expect(panelToggle).toHaveAttribute("aria-expanded", "false");
  await expect(panelToggle).toBeInViewport();
  const mapBox = await page.getByTestId("atlas-map").boundingBox();
  expect(mapBox).not.toBeNull();
  expect(mapBox?.height, "the collapsed mobile experience should preserve meaningful map space").toBeGreaterThan(360);
  await expect(page.getByRole("group", { name: "Coastal defenses" })).toBeHidden();

  await panelToggle.click();
  const collapse = page.getByRole("button", { name: "Less detail" });
  await expect(collapse).toHaveAttribute("aria-expanded", "true");
  await expect(panel).toHaveClass(/is-expanded/u);
  await expect(page.getByRole("group", { name: "Coastal defenses" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Hide flood layer" })).toBeVisible();
  await collapse.click();
  await expect(panelToggle).toBeFocused();
  await expect(panelToggle).toHaveAttribute("aria-expanded", "false");
  expect(await page.locator("body").innerText()).not.toMatch(/[\u0400-\u04ff]/u);
  await page.screenshot({ path: resolve(screenshotDir, "mobile-europe-overview-2050-viewport.png") });
  await page.screenshot({ path: resolve(screenshotDir, "mobile-europe-overview-2050.png"), fullPage: true });
  await expectAccessiblePage(page);
});

test("responsive boundaries retain Europe controls without horizontal overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-boundaries");
  for (const viewport of [{ width: 768, height: 1024 }, { width: 360, height: 780 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/?city=geonames%3A3164603&year=2050&defenses=unprotected&flooding=on", {
      waitUntil: "domcontentloaded",
    });
    await waitForRaster(page, 2050, "unprotected", "Venice");
    expect(await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: window.innerWidth })))
      .toEqual({ document: viewport.width, viewport: viewport.width });
    await expect(page.getByRole("combobox", { name: "Find a city in Europe" })).toBeInViewport();
    await expect(page.getByRole("slider", { name: "Projection year" })).toBeInViewport();
    const moreDetail = page.getByRole("button", { name: "More detail" });
    if (viewport.width <= 760) {
      await expect(moreDetail).toHaveAttribute("aria-expanded", "false");
      await moreDetail.click();
    }
    await expect(page.getByRole("group", { name: "Coastal defenses" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(viewport.width);
    await page.screenshot({ path: resolve(screenshotDir, `boundary-europe-${viewport.width}x${viewport.height}.png`) });
  }
});

test("search results stay anchored, scrollable, and unclipped after viewport changes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("a");
  const results = page.locator(".search-results");
  const listbox = page.getByRole("listbox", { name: "European places" });
  await expect(page.getByRole("option").first()).toBeVisible({ timeout: 15_000 });

  async function expectAnchored(): Promise<void> {
    await expect.poll(() => page.evaluate(() => {
      const wrapper = document.querySelector<HTMLElement>(".atlas-search")!.getBoundingClientRect();
      const menu = document.querySelector<HTMLElement>(".search-results")!.getBoundingClientRect();
      return menu.top - wrapper.bottom;
    }), { timeout: 10_000, message: "search results did not settle below the search field" }).toBeCloseTo(8, 1);
    const geometry = await page.evaluate(() => {
      const wrapper = document.querySelector<HTMLElement>(".atlas-search")!;
      const menu = document.querySelector<HTMLElement>(".search-results")!;
      const wrapperRect = wrapper.getBoundingClientRect();
      const menuRect = menu.getBoundingClientRect();
      return {
        parentIsBody: menu.parentElement === document.body,
        position: getComputedStyle(menu).position,
        wrapper: { left: wrapperRect.left, right: wrapperRect.right, bottom: wrapperRect.bottom, width: wrapperRect.width },
        menu: { left: menuRect.left, right: menuRect.right, top: menuRect.top, bottom: menuRect.bottom, width: menuRect.width },
        viewportHeight: window.innerHeight,
      };
    });
    expect(geometry.parentIsBody).toBe(true);
    expect(geometry.position).toBe("fixed");
    expect(geometry.menu.left).toBeCloseTo(geometry.wrapper.left, 1);
    expect(geometry.menu.right).toBeCloseTo(geometry.wrapper.right, 1);
    expect(geometry.menu.width).toBeCloseTo(geometry.wrapper.width, 1);
    expect(geometry.menu.top - geometry.wrapper.bottom).toBeCloseTo(8, 1);
    expect(geometry.menu.bottom).toBeLessThanOrEqual(geometry.viewportHeight - 11);
  }

  await expectAnchored();
  await page.setViewportSize({ width: 900, height: 360 });
  await expect(results).toBeVisible();
  await expectAnchored();
  const scroll = await listbox.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
    element.dispatchEvent(new Event("scroll"));
    return { top: element.scrollTop, clientHeight: element.clientHeight, scrollHeight: element.scrollHeight };
  });
  expect(scroll.scrollHeight).toBeGreaterThan(scroll.clientHeight);
  expect(scroll.top).toBeGreaterThan(0);
  await expect(search).toHaveAttribute("aria-expanded", "true");
  await expectAnchored();
});
