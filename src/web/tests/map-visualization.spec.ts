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
    const structuralTokens: string[] = [];
    let binaryValueCount = 0;
    const binaryRecords: Array<{
      database: string;
      store: string;
      artifactId: unknown;
      path: unknown;
      role: unknown;
      mediaType: unknown;
      binaryValueCount: number;
    }> = [];
    const inspect = (value: unknown, seen = new WeakSet<object>()): void => {
      if (typeof value === "string") {
        structuralTokens.push(value);
        return;
      }
      if (value instanceof Blob || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
        binaryValueCount += 1;
        structuralTokens.push(`binary:${value instanceof Blob ? value.size : value.byteLength}`);
        return;
      }
      if (value === null || typeof value !== "object" || seen.has(value)) return;
      seen.add(value);
      if (Array.isArray(value)) {
        for (const item of value) inspect(item, seen);
        return;
      }
      for (const [key, item] of Object.entries(value)) {
        structuralTokens.push(key);
        inspect(item, seen);
      }
    };
    for (const database of await indexedDB.databases()) {
      if (!database.name) continue;
      structuralTokens.push(`database:${database.name}`);
      const opened = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open(database.name!);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      for (const storeName of opened.objectStoreNames) {
        structuralTokens.push(`store:${storeName}`);
        const transaction = opened.transaction(storeName, "readonly");
        const store = transaction.objectStore(storeName);
        for (const indexName of store.indexNames) structuralTokens.push(`index:${indexName}`);
        const [keys, values] = await Promise.all([
          new Promise<IDBValidKey[]>((resolve, reject) => {
            const request = store.getAllKeys();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          }),
          new Promise<unknown[]>((resolve, reject) => {
            const request = store.getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          }),
        ]);
        for (const key of keys) inspect(key);
        for (const value of values) {
          const before = binaryValueCount;
          inspect(value);
          const recordBinaryValueCount = binaryValueCount - before;
          if (recordBinaryValueCount > 0) {
            const record = typeof value === "object" && value !== null
              ? value as Record<string, unknown>
              : {};
            binaryRecords.push({
              database: database.name,
              store: storeName,
              artifactId: record.artifactId,
              path: record.path,
              role: record.role,
              mediaType: record.mediaType,
              binaryValueCount: recordBinaryValueCount,
            });
          }
        }
      }
      opened.close();
    }
    return {
      cacheUrls,
      structuralTokens,
      binaryValueCount,
      binaryRecords,
      webStorageEntries: [localStorage, sessionStorage].flatMap((storage) =>
        Array.from({ length: storage.length }, (_, index) => {
          const key = storage.key(index) ?? "";
          return `${key}=${storage.getItem(key) ?? ""}`;
        })),
    };
  });
  expect(persistence.cacheUrls.filter((url) => url.includes(".pmtiles"))).toEqual([]);
  const persistentAuthority = [
    ...persistence.cacheUrls,
    ...persistence.structuralTokens,
    ...persistence.webStorageEntries,
  ].join("\n");
  expect(persistentAuthority).not.toContain(".pmtiles");
  expect(persistentAuthority).not.toContain("-pmtiles");
  for (const scenario of scenarios) {
    for (const horizon of horizons) {
      expect(persistentAuthority).not.toContain(`projection-${scenario}-${horizon}-pmtiles`);
    }
  }
  expect(persistence.binaryValueCount).toBeGreaterThan(0);
  expect(persistence.binaryRecords.reduce(
    (count, record) => count + record.binaryValueCount,
    0,
  )).toBe(persistence.binaryValueCount);
  for (const record of persistence.binaryRecords) {
    expect(record.database).toBe("searise-offline:v1");
    expect(record.store).toBe("ranges");
    const artifactMatch = /^projection-(ssp1-26|ssp2-45|ssp5-85)-(2030|2050|2100)-cog$/.exec(
      String(record.artifactId),
    );
    const pathMatch = /^analysis\/(ssp1-26|ssp2-45|ssp5-85)\/(2030|2050|2100)\.tif$/.exec(
      String(record.path),
    );
    expect(artifactMatch).not.toBeNull();
    expect(pathMatch).not.toBeNull();
    expect(pathMatch?.slice(1)).toEqual(artifactMatch?.slice(1));
    expect(record.role).toBe("projection-analysis-cog");
    expect(record.mediaType).toBe("image/tiff; application=geotiff; profile=cloud-optimized");
  }
});

test("basemap failure preserves release overlay, attribution, text, and coordinate selection", async ({ page }, testInfo) => {
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

  const basemapButton = page.getByRole("button", { name: /load optional basemap/i });
  if (testInfo.project.name === "mobile-chromium") {
    await page.locator(".flight-alerts").evaluate((slot) => {
      const alert = document.createElement("div");
      alert.className = "application-technical-alert";
      alert.setAttribute("role", "status");
      alert.setAttribute("aria-live", "polite");
      alert.dataset.updateState = "failed";
      alert.dataset.layoutProbe = "failed-update";
      alert.textContent = "Update check failed. The current version remains active.";
      slot.prepend(alert);
    });
    const alert = page.locator("[data-layout-probe='failed-update']");
    await expect(alert).toBeVisible();
    const [buttonBox, alertBox] = await Promise.all([basemapButton.boundingBox(), alert.boundingBox()]);
    if (!buttonBox || !alertBox) throw new Error("Mobile basemap/alert geometry was unavailable.");
    expect(alertBox.y).toBeGreaterThanOrEqual(buttonBox.y + buttonBox.height + 8);
  }

  await basemapButton.click();
  await expect(page.locator(".map-status")).toContainText(/optional basemap unavailable/i);
  expect(openFreeMapRequestObserved).toBe(true);
  await expect(map).toHaveAttribute("data-artifact-id", "projection-ssp2-45-2050-pmtiles");
  await expect(page.getByRole("link", { name: "OpenFreeMap" })).toBeVisible();
  await expect(page.getByRole("link", { name: /OpenStreetMap contributors/i })).toBeVisible();

  expect(pageErrors).toEqual([]);

  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
});
