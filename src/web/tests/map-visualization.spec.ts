import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { isForbiddenApplicationApiPath } from "../src/test/application-api-boundary";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";

async function acceptMapPoint(page: Page): Promise<void> {
  const mapExplorer = page.locator(".map-explorer");
  const scenario = mapExplorer.getByRole("combobox", { name: "Scenario" });
  const horizon = mapExplorer.getByRole("combobox", { name: "Horizon" });
  await expect(scenario).toBeDisabled();
  await expect(horizon).toBeDisabled();
  await page.locator(".maplibregl-canvas").click({ position: { x: 180, y: 160 } });
  await expect(page.getByLabel("Map text alternative")).toContainText(/accepted result visualization/i);
  await expect(page.getByLabel("Map text alternative")).toContainText(/selected coordinate:/i);
  await expect(scenario).toBeEnabled();
  await expect(horizon).toBeEnabled();
}

test("map stays lazy, loads bounded PMTiles ranges, and keeps one atomic active overlay", async ({ page }) => {
  const pmtilesRequests: { url: string; range?: string }[] = [];
  const forbiddenRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith(".pmtiles")) {
      pmtilesRequests.push({ url: url.href, range: request.headers().range });
    }
    if (isForbiddenApplicationApiPath(url.pathname)) {
      forbiddenRequests.push(url.pathname);
    }
  });

  await page.goto("/");
  await expect(page.getByText(/release contract ready · 9 exact combinations/i)).toBeVisible();
  expect(pmtilesRequests).toEqual([]);
  expect(await page.locator('script[src*="MapExplorer"], script[src*="map-runtime"]').count()).toBe(0);

  await page.getByRole("button", { name: /open static visualization/i }).click();
  await expect(page.getByRole("region", { name: /interactive visual map/i })).toBeVisible();
  await expect(page.locator(".map-status")).toContainText(/central visual band ready/i);
  await expect.poll(() => pmtilesRequests.length).toBeGreaterThan(0);

  for (const request of pmtilesRequests) {
    expect(new URL(request.url).pathname).toBe(
      `/releases/${releaseId}/layers/ssp2-45/2050.pmtiles`,
    );
    expect(request.range).toMatch(/^bytes=\d+-\d+$/);
    const [start, end] = request.range!.slice(6).split("-").map(Number);
    expect(end - start + 1).toBeLessThanOrEqual(512 * 1024);
  }

  await acceptMapPoint(page);
  const mapExplorer = page.locator(".map-explorer");
  await mapExplorer.getByRole("combobox", { name: "Scenario" }).selectOption("ssp5-85");
  await mapExplorer.getByRole("combobox", { name: "Horizon" }).selectOption("2100");
  await mapExplorer.getByLabel(/Upper · q0.833/).check();
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp5-85-2100-pmtiles");
  await expect(page.getByLabel("Map text alternative")).toContainText(
    "ssp5-85 · 2100 · Upper · q0.833",
  );
  expect(forbiddenRequests).toEqual([]);
});

test("all nine release selections resolve without mixing visual artifact identity", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /open static visualization/i }).click();
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(page.locator(".map-status")).toContainText(/central visual band ready/i);
  await acceptMapPoint(page);
  const mapExplorer = page.locator(".map-explorer");
  const scenarioControl = mapExplorer.getByRole("combobox", { name: "Scenario" });
  const horizonControl = mapExplorer.getByRole("combobox", { name: "Horizon" });
  const scenarios = ["ssp1-26", "ssp2-45", "ssp5-85"];
  const horizons = ["2030", "2050", "2100"];

  for (const scenario of scenarios) {
    for (const horizon of horizons) {
      await scenarioControl.selectOption(scenario);
      await expect(map).toHaveAttribute(
        "data-artifact-id",
        `projection-${scenario}-${await horizonControl.inputValue()}-pmtiles`,
      );
      await horizonControl.selectOption(horizon);
      await expect(map).toHaveAttribute(
        "data-artifact-id",
        `projection-${scenario}-${horizon}-pmtiles`,
      );
      await expect(page.getByLabel("Map text alternative")).toContainText(`${scenario} · ${horizon}`);
      await expect(page.getByLabel("Map text alternative")).toContainText(/accepted result visualization/i);
    }
  }
});

test("basemap failure preserves release overlay, attribution, text, and coordinate selection", async ({ page }) => {
  const pageErrors: string[] = [];
  let openFreeMapRequestObserved = false;
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("https://tiles.openfreemap.org/**", async (route) => {
    openFreeMapRequestObserved = true;
    await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: /open static visualization/i }).click();
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp2-45-2050-pmtiles");

  await page.getByRole("button", { name: /load optional basemap/i }).click();
  await expect(page.locator(".map-status")).toContainText(/optional basemap unavailable/i);
  expect(openFreeMapRequestObserved).toBe(true);
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp2-45-2050-pmtiles");
  await expect(page.getByRole("link", { name: "OpenFreeMap" })).toBeVisible();
  await expect(page.getByRole("link", { name: /OpenStreetMap contributors/i })).toBeVisible();

  await acceptMapPoint(page);
  expect(pageErrors).toEqual([]);

  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
});
