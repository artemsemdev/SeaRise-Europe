import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function settledMap(page: Page) {
  await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  await expect(page.getByRole("alert")).toHaveCount(0);
}

test("reduced-motion city selection, zoom, and refocus preserve the visible map anchor", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?qa=map");
  await page.getByRole("combobox", { name: "Find a city in Europe" }).fill("Venice");
  await page.getByRole("option", { name: /^Venice\s+Italy$/ }).click();
  await settledMap(page);
  const position = () => page.evaluate(() => {
    const map = (window as unknown as { __SEARISE_ATLAS_MAP__: import("maplibre-gl").Map }).__SEARISE_ATLAS_MAP__;
    const point = map.project([12.3155, 45.4408]);
    const canvas = map.getCanvas();
    const offset = window.matchMedia("(max-width: 760px)").matches ? 0 : 120;
    return { x: point.x, y: point.y, zoom: map.getZoom(),
      error: Math.max(Math.abs(point.x - canvas.clientWidth / 2 - offset), Math.abs(point.y - canvas.clientHeight / 2)) };
  });
  await expect.poll(async () => (await position()).error).toBeLessThan(4);
  const selected = await position();
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(async () => (await position()).zoom).toBeGreaterThan(selected.zoom + 0.5);
  await expect.poll(async () => (await position()).error).toBeLessThan(4);
  await page.getByRole("button", { name: "Return to selected place", exact: true }).click();
  await expect.poll(async () => (await position()).zoom).toBeCloseTo(selected.zoom, 4);
  await expect.poll(async () => (await position()).error).toBeLessThan(4);
});

test("clean entry renders Europe with explicit fixture disclosure and no external or local-data requests", async ({ page }) => {
  const unexpected: string[] = [], errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== "http://127.0.0.1:4173" || url.pathname.startsWith("/atlas-data/")) unexpected.push(url.href);
  });
  await page.goto("/?qa=map");
  await settledMap(page);
  await expect(page.locator(".atlas-fixture-label strong")).toBeVisible();
  await expect(page.getByTestId("atlas-map")).toHaveAttribute("data-model", "illustrative-fixture");
  for (const city of ["Venice", "Rotterdam", "Hamburg", "Bordeaux"]) {
    await expect(page.locator(".atlas-map").getByRole("button", { name: `Open ${city}`, exact: true })).toBeVisible();
  }
  const geography = await page.evaluate(() => {
    const map = (window as unknown as { __SEARISE_ATLAS_MAP__: import("maplibre-gl").Map }).__SEARISE_ATLAS_MAP__;
    return { rendered: map.queryRenderedFeatures().length, worldCopies: map.getRenderWorldCopies(), zoom: map.getZoom() };
  });
  expect(geography.rendered).toBeGreaterThan(0);
  expect(geography.worldCopies).toBe(false);
  expect(geography.zoom).toBeGreaterThan(2);
  expect(errors).toEqual([]);
  expect(unexpected).toEqual([]);
  expect(await page.evaluate(() => navigator.serviceWorker.getRegistrations().then((items) => items.length))).toBe(0);
});

test("fixture city, timeline, defenses, comparison, and selected point survive sharing and reload", async ({ page }, info) => {
  await page.goto("/");
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Venice");
  await page.getByRole("option", { name: /^Venice\s+Italy$/ }).click();
  await expect(page.locator("#city-title")).toHaveText("Venice");
  await settledMap(page);
  const inspector = page.getByTestId("point-inspection");
  await expect(inspector).toHaveAttribute("data-state", "flooded");
  await expect(inspector).toContainText("0.4 m depth");
  if (info.project.name === "mobile-chromium") await page.getByRole("button", { name: "More detail" }).click();
  const slider = page.getByRole("slider", { name: "Projection year" });
  await slider.focus();
  await slider.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuetext", "2030");
  await expect(inspector).toHaveAttribute("data-state", "zero");
  await page.getByRole("button", { name: "2100", exact: true }).click();
  await expect(inspector).toContainText("1.2 m depth");
  await page.getByRole("button", { name: "High protection", exact: true }).click();
  await expect(inspector).toContainText("0.6 m depth");
  await page.getByRole("button", { name: "Compare 2030 & 2100" }).click();
  await expect(page.getByRole("button", { name: "2050", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "2030", exact: true }).click();
  await expect(inspector).toHaveAttribute("data-state", "unknown");
  await page.getByRole("button", { name: "Hide flood layer" }).click();
  const shared = page.url();
  expect(shared).toMatch(/city=fixture%3Avenice/);
  expect(shared).toMatch(/defenses=protected/);
  expect(shared).toMatch(/compare=on/);
  await page.reload();
  await settledMap(page);
  await expect(page.getByTestId("point-inspection")).toHaveAttribute("data-state", "unknown");
  await expect(page.getByRole("button", { name: "Show flood layer" })).toBeVisible();
  expect(page.url()).toBe(shared);
  await page.screenshot({ path: info.outputPath("atlas-fixture-selected.png") });
});

test("search menu stays anchored and mobile controls remain reachable", async ({ page }, info) => {
  await page.goto("/");
  await settledMap(page);
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("a");
  await expect(page.getByRole("option").first()).toBeVisible();
  const box = await page.locator(".atlas-search").boundingBox();
  const menu = await page.locator(".search-results").boundingBox();
  expect(menu!.x).toBeCloseTo(box!.x, 1);
  expect(menu!.width).toBeCloseTo(box!.width, 1);
  expect(menu!.y).toBeCloseTo(box!.y + box!.height + 8, 1);
  await search.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(page.viewportSize()!.width);
  await expect(page.getByRole("slider", { name: "Projection year" })).toBeInViewport();
  if (info.project.name === "mobile-chromium") {
    await page.getByRole("button", { name: "More detail" }).click();
    await expect(page.getByRole("group", { name: "Coastal defenses" })).toBeVisible();
    await page.getByRole("button", { name: "Less detail" }).click();
  }
  await page.getByRole("button", { name: "About the map", exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Illustrative fixture");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const audit = await new AxeBuilder({ page }).analyze();
  expect(audit.violations.filter(({ impact }) => impact === "serious" || impact === "critical")).toEqual([]);
});

test("retained projection worker does not replace the Atlas entry or cache local data", async ({ page }, info) => {
  test.skip(info.project.name !== "chromium");
  await page.goto("/projections/");
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.goto("/");
  await settledMap(page);
  await expect(page.locator(".atlas-fixture-label strong")).toBeVisible();
  const cached = await page.evaluate(async () => {
    const names = await caches.keys();
    return (await Promise.all(names.map(async (name) => (await (await caches.open(name)).keys()).map((request) => new URL(request.url).pathname)))).flat();
  });
  expect(cached).toContain("/projections/index.html");
  expect(cached).not.toContain("/");
  expect(cached.some((path) => path.startsWith("/atlas-data/"))).toBe(false);
});


test("failed map chunk keeps controls usable and Retry reloads the same view", async ({ page }) => {
  const mapChunk = /\/assets\/EuropeMap-[^/]+\.js(?:\?|$)/;
  let blocked = 0;
  await page.route(mapChunk, (route) => {
    blocked += 1;
    return route.abort("failed");
  });
  await page.goto("/?year=2100&defenses=protected&compare=on&view=12.33,45.44,7");
  await expect(page.getByRole("alert")).toContainText("The map application could not load.");
  expect(blocked).toBeGreaterThan(0);
  await expect(page.locator(".coast-examples")).toHaveCount(0);
  await expect(page.locator(".atlas-fixture-label strong")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Find a city in Europe" })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Projection year" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Exit comparison" })).toBeVisible();
  const sharedView = page.url();
  await page.unroute(mapChunk);
  await Promise.all([
    page.waitForEvent("framenavigated", (frame) => frame === page.mainFrame()),
    page.getByRole("button", { name: "Retry", exact: true }).click(),
  ]);
  await settledMap(page);
  expect(page.url()).toBe(sharedView);
  await expect(page.getByRole("slider", { name: "Projection year" })).toHaveAttribute("aria-valuetext", "2100");
  await expect(page.getByRole("button", { name: "Exit comparison" })).toBeVisible();
});
