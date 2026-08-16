import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { isForbiddenApplicationApiPath } from "../src/test/application-api-boundary";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";

async function acceptMapPoint(page: Page): Promise<void> {
  await expect(page.locator("[data-flight-phase='idle'] .flight-search")).toBeVisible();
  await expect(page.getByRole("button", { name: /select coordinate at source extent centre/i })).toHaveCount(0);
  const search = page.getByRole("combobox", { name: /find a city, town, or village/i });
  await search.fill("Málaga");
  await page.getByRole("option", { name: /Málaga.*Andalucía, ES/i }).click();
  await page.getByRole("button", { name: /select coordinate at source extent centre/i }).click();
  await expect(page.locator("[data-flight-phase='result'] .flight-result")).toBeVisible();
  await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(/accepted result visualization/i);
  await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(/selected coordinate:/i);
}

test("map is the static-first scene, loads bounded PMTiles ranges, and keeps one atomic active overlay", async ({ page }) => {
  const pmtilesRequests: { url: string; range?: string }[] = [];
  const forbiddenRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith(".pmtiles")) {
      pmtilesRequests.push({ url: url.href, range: request.headers().range });
    }
    if (isForbiddenApplicationApiPath(url.pathname)) forbiddenRequests.push(url.pathname);
  });

  await page.goto("/");
  await expect(page.getByRole("region", { name: /visual release map preview/i })).toBeVisible();
  await expect(page.locator(".map-status")).toBeHidden();
  await expect(page.locator(".maplibregl-control-container")).toBeHidden();
  await expect.poll(() => pmtilesRequests.length).toBeGreaterThan(0);

  for (const request of pmtilesRequests) {
    expect(new URL(request.url).pathname).toBe(`/releases/${releaseId}/layers/ssp2-45/2050.pmtiles`);
    expect(request.range).toMatch(/^bytes=\d+-\d+$/);
    const [start, end] = request.range!.slice(6).split("-").map(Number);
    expect(end - start + 1).toBeLessThanOrEqual(512 * 1024);
  }

  await acceptMapPoint(page);
  await expect(page.locator(".map-status")).toContainText(/central visual band ready/i);
  await expect(page.locator(".map-status")).toBeVisible();
  const mapControls = page.locator(".maplibregl-control-container");
  await expect(mapControls).not.toHaveAttribute("aria-hidden", "true");
  expect(await mapControls.evaluate((element) => getComputedStyle(element).display)).not.toBe("none");
  await expect(page.locator(".maplibregl-ctrl-attrib")).toBeVisible();
  await expect(page.getByRole("region", { name: /visual release map preview/i })).toHaveCount(0);
  await page.getByRole("radio", { name: /higher-emissions scenario.*ssp5-85/i }).check();
  await page.getByRole("radio", { name: "2100" }).check();
  await page.locator(".flight-legend").getByLabel(/Upper · q0.833/).check();
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp5-85-2100-pmtiles");
  await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(
    "ssp5-85 · 2100 · Upper · q0.833",
  );
  expect(forbiddenRequests).toEqual([]);
});

test("all nine release selections resolve without mixing visual artifact identity", async ({ page }) => {
  const requests: string[] = [];
  const responsePolicies: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith(".pmtiles")) requests.push(request.url());
  });
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.endsWith(".pmtiles")) {
      responsePolicies.push(response.headers()["cache-control"] ?? "");
    }
  });
  await page.goto("/");
  await expect(page.getByRole("region", { name: /visual release map preview/i })).toBeVisible();
  await expect(page.locator(".map-status")).toContainText(/central visual band ready/i);
  await acceptMapPoint(page);
  const map = page.getByRole("region", { name: /interactive visual map/i });
  const scenarios = ["ssp1-26", "ssp2-45", "ssp5-85"];
  const horizons = ["2030", "2050", "2100"];

  for (const scenario of scenarios) {
    for (const horizon of horizons) {
      await page.locator(`input[name="projection-scenario"][value="${scenario}"]`).check();
      await page.locator(`input[name="projection-horizon"][value="${horizon}"]`).check();
      await expect(map).toHaveAttribute("data-artifact-id", `projection-${scenario}-${horizon}-pmtiles`);
      await expect(page.locator(".map-status")).toContainText(
        new RegExp(`${scenario} · ${horizon} · central visual band ready`, "i"),
      );
      await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(`${scenario} · ${horizon}`);
      await expect(page.getByLabel("Map text alternative", { exact: true })).toContainText(/accepted result visualization/i);
    }
  }

  await expect.poll(() => new Set(requests.map((url) => new URL(url).pathname)).size).toBe(9);
  expect(new Set(requests.map((url) => new URL(url).pathname))).toEqual(new Set(
    scenarios.flatMap((scenario) => horizons.map(
      (horizon) => `/releases/${releaseId}/layers/${scenario}/${horizon}.pmtiles`,
    )),
  ));
  expect(responsePolicies.length).toBeGreaterThanOrEqual(9);
  expect(responsePolicies.every((policy) => policy.toLowerCase().split(",").map((value) => value.trim()).includes("no-store"))).toBe(true);

  const persistence = await page.evaluate(async () => {
    const cacheUrls = (await Promise.all((await caches.keys()).map(async (name) =>
      (await (await caches.open(name)).keys()).map((request) => request.url)))).flat();
    const storedValues: unknown[] = [];
    for (const database of await indexedDB.databases()) {
      if (!database.name) continue;
      const opened = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open(database.name!);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      for (const storeName of opened.objectStoreNames) {
        const values = await new Promise<unknown[]>((resolve, reject) => {
          const request = opened.transaction(storeName, "readonly").objectStore(storeName).getAll();
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
        storedValues.push(...values);
      }
      opened.close();
    }
    return {
      cacheUrls,
      durableRecords: JSON.stringify(storedValues),
      local: Object.values(localStorage),
      session: Object.values(sessionStorage),
    };
  });
  expect(persistence.cacheUrls.filter((url) => url.includes(".pmtiles"))).toEqual([]);
  expect(persistence.durableRecords).not.toContain(".pmtiles");
  expect(persistence.durableRecords).not.toContain("-pmtiles");
  expect([...persistence.local, ...persistence.session].join("\n")).not.toContain(".pmtiles");
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
  await acceptMapPoint(page);
  const map = page.getByRole("region", { name: /interactive visual map/i });
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp2-45-2050-pmtiles");

  await page.getByRole("button", { name: /load optional basemap/i }).click();
  await expect(page.locator(".map-status")).toContainText(/optional basemap unavailable/i);
  expect(openFreeMapRequestObserved).toBe(true);
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp2-45-2050-pmtiles");
  await expect(page.getByRole("link", { name: "OpenFreeMap" })).toBeVisible();
  await expect(page.getByRole("link", { name: /OpenStreetMap contributors/i })).toBeVisible();

  expect(pageErrors).toEqual([]);

  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
});
