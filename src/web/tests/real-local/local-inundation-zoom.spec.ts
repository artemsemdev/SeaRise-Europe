import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const screenshotDir = resolve(import.meta.dirname, "../../../../.cache/atlas-qa/screenshots");
const evidenceByPage = new WeakMap<Page, BrowserEvidence>();

interface FloodTileRequest {
  readonly year: number;
  readonly protection: string;
  readonly z: number;
  readonly url: string;
}

interface BrowserEvidence {
  readonly externalRequests: string[];
  readonly pageErrors: string[];
  readonly consoleErrors: string[];
  readonly pendingConsoleErrors: Promise<void>[];
  readonly floodTiles: FloodTileRequest[];
  readonly basemapRequests: string[];
  readonly basemapResponses: Array<{ readonly url: string; readonly qaOnly: boolean }>;
  readonly pendingBasemapResponses: Promise<void>[];
  readonly archiveRequests: string[];
}

interface MapSnapshot {
  readonly zoom: number;
  readonly minZoom: number;
  readonly moving: boolean;
  readonly styleLoaded: boolean;
  readonly pitch: number;
  readonly bearing: number;
  readonly roads: number;
  readonly buildings: number;
  readonly places: number;
  readonly overviewLand: number;
  readonly basemapFeatures: number;
  readonly basemapNonSymbols: number;
  readonly overviewLabels: Record<string, string[]>;
  readonly sourceLayerCounts: Record<string, number>;
  readonly layerIds: string[];
  readonly floodMaxZoom: number | null;
  readonly center: [number, number];
  readonly bounds: [number, number, number, number];
  readonly olbiaPixel: { readonly x: number; readonly y: number };
  readonly canvas: {
    readonly width: number;
    readonly height: number;
    readonly clientWidth: number;
    readonly clientHeight: number;
    readonly devicePixelRatio: number;
    readonly transform: string;
  };
}

function isLoopbackRequest(rawUrl: string): boolean {
  const url = new URL(rawUrl);
  return url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
}

async function installDisconnectedInternetBoundary(context: BrowserContext, page: Page): Promise<BrowserEvidence> {
  const evidence: BrowserEvidence = {
    externalRequests: [], pageErrors: [], consoleErrors: [], pendingConsoleErrors: [],
    floodTiles: [], basemapRequests: [], basemapResponses: [], pendingBasemapResponses: [], archiveRequests: [],
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
    const url = request.url();
    if (/\.pmtiles(?:\?|$)/u.test(url)) evidence.archiveRequests.push(url);
    const tile = /\/atlas-data\/tiles\/(2030|2050|2100)\/(unprotected|protected)\/(\d+)\/\d+\/\d+\.png(?:\?|$)/u.exec(url);
    if (tile) evidence.floodTiles.push({ year: Number(tile[1]), protection: tile[2], z: Number(tile[3]), url });
    if (/\/atlas-data\/basemap\/protomaps-europe\.pmtiles(?:\?|$)/u.test(url)) {
      evidence.basemapRequests.push(url);
    }
  });
  page.on("response", (response) => {
    if (!/\/atlas-data\/basemap\/protomaps-europe\.pmtiles(?:\?|$)/u.test(response.url())) return;
    evidence.pendingBasemapResponses.push((async () => {
      evidence.basemapResponses.push({
        url: response.url(),
        qaOnly: await response.headerValue("x-searise-qa-only") !== null,
      });
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

async function mapSnapshot(page: Page): Promise<MapSnapshot> {
  return page.evaluate(() => {
    type Feature = { source?: string; sourceLayer?: string; layer?: { id: string; type?: string }; properties?: Record<string, unknown> };
    type MapHook = {
      getZoom(): number;
      getMinZoom(): number;
      getPitch(): number;
      getBearing(): number;
      isMoving(): boolean;
      isStyleLoaded(): boolean;
      getCanvas(): HTMLCanvasElement;
      getCenter(): { lng: number; lat: number };
      getBounds(): { getWest(): number; getSouth(): number; getEast(): number; getNorth(): number };
      project(coordinates: [number, number]): { x: number; y: number };
      getStyle(): {
        layers?: Array<{ id: string; source?: string; "source-layer"?: string }>;
        sources?: Record<string, { type?: string; maxzoom?: number }>;
      };
      queryRenderedFeatures(): Feature[];
    };
    const map = (window as typeof window & { __SEARISE_ATLAS_MAP__?: MapHook }).__SEARISE_ATLAS_MAP__;
    if (!map) throw new Error("The opt-in MapLibre QA hook is unavailable.");
    const allFeatures = map.queryRenderedFeatures();
    const features = allFeatures.filter((feature) => feature.source === "atlas-basemap");
    const count = (sourceLayer: string) => features.filter((feature) => feature.sourceLayer === sourceLayer).length;
    const sourceLayerCounts: Record<string, number> = {};
    for (const feature of features) {
      const sourceLayer = feature.sourceLayer ?? "(missing)";
      sourceLayerCounts[sourceLayer] = (sourceLayerCounts[sourceLayer] ?? 0) + 1;
    }
    const style = map.getStyle();
    const canvas = map.getCanvas();
    const floodSource = Object.values(style.sources ?? {}).find((source) => source.type === "raster");
    const center = map.getCenter();
    const bounds = map.getBounds();
    const olbiaPixel = map.project([9.49802, 40.92337]);
    return {
      zoom: map.getZoom(), minZoom: map.getMinZoom(), moving: map.isMoving(), styleLoaded: map.isStyleLoaded(),
      pitch: map.getPitch(), bearing: map.getBearing(),
      roads: count("roads"), buildings: count("buildings"), places: count("places"),
      overviewLand: allFeatures.filter((feature) =>
        feature.source === "atlas-europe-overview" && feature.layer?.id === "atlas-europe-overview-land"
      ).length,
      basemapFeatures: features.length,
      basemapNonSymbols: features.filter((feature) => feature.layer?.type !== "symbol").length,
      overviewLabels: Object.fromEntries(["country", "city", "sea"].map((kind) => [kind,
        features.filter((feature) => feature.layer?.id === `atlas-europe-overview-${kind}`)
          .map((feature) => String(feature.properties?.["name:en"] ?? feature.properties?.name))])),
      sourceLayerCounts,
      layerIds: (style.layers ?? []).filter((layer) => layer.source === "atlas-basemap").map((layer) => layer.id),
      floodMaxZoom: floodSource?.maxzoom ?? null,
      center: [center.lng, center.lat],
      bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
      olbiaPixel: { x: olbiaPixel.x, y: olbiaPixel.y },
      canvas: {
        width: canvas.width, height: canvas.height,
        clientWidth: canvas.clientWidth, clientHeight: canvas.clientHeight,
        devicePixelRatio: window.devicePixelRatio,
        transform: getComputedStyle(canvas).transform,
      },
    };
  });
}

async function waitForMapHook(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() =>
    Boolean((window as typeof window & { __SEARISE_ATLAS_MAP__?: unknown }).__SEARISE_ATLAS_MAP__)
  ), { timeout: 30_000, message: "the opt-in MapLibre QA hook was not installed" }).toBe(true);
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
  }, { timeout: 12_000, intervals: [100, 150, 250, 400] }).toBeGreaterThanOrEqual(2);
}

async function waitForSettledMap(page: Page): Promise<MapSnapshot> {
  await expect.poll(async () => {
    const snapshot = await mapSnapshot(page);
    return snapshot.styleLoaded && !snapshot.moving;
  }, { timeout: 30_000, message: "the MapLibre camera did not settle" }).toBe(true);
  await waitForStableCanvas(page);
  return mapSnapshot(page);
}

async function zoomToAtLeast(page: Page, target: number): Promise<MapSnapshot> {
  const zoomIn = page.getByRole("button", { name: "Zoom in" });
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const before = await mapSnapshot(page);
    if (before.zoom >= target) return before;
    await zoomIn.click();
    await expect.poll(async () => {
      const current = await mapSnapshot(page);
      return !current.moving && current.zoom > before.zoom + 0.5;
    }, { timeout: 8_000, message: `zoom in did not advance from ${before.zoom}` }).toBe(true);
  }
  throw new Error(`The zoom-in control did not reach zoom ${target}.`);
}

async function zoomToAtMost(page: Page, target: number): Promise<MapSnapshot> {
  const zoomOut = page.getByRole("button", { name: "Zoom out" });
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const before = await mapSnapshot(page);
    if (before.zoom <= target) return before;
    await zoomOut.click();
    await expect.poll(async () => {
      const current = await mapSnapshot(page);
      return !current.moving && current.zoom < before.zoom - 0.5;
    }, { timeout: 8_000, message: `zoom out did not advance from ${before.zoom}` }).toBe(true);
  }
  throw new Error(`The zoom-out control did not reach zoom ${target}.`);
}

function maxFloodZoom(evidence: BrowserEvidence): number {
  return Math.max(...evidence.floodTiles.map((tile) => tile.z));
}

async function expectCityAnchor(page: Page, original: MapSnapshot): Promise<void> {
  let current = await mapSnapshot(page);
  await expect.poll(async () => {
    current = await mapSnapshot(page);
    return Math.max(
      Math.abs(current.olbiaPixel.x - original.olbiaPixel.x),
      Math.abs(current.olbiaPixel.y - original.olbiaPixel.y),
    );
  }, { timeout: 10_000, message: "the selected city did not settle at its map anchor" }).toBeLessThan(4);
  expect(current.olbiaPixel.x).toBeGreaterThan(0);
  expect(current.olbiaPixel.x).toBeLessThan(current.canvas.clientWidth);
  expect(current.olbiaPixel.y).toBeGreaterThan(0);
  expect(current.olbiaPixel.y).toBeLessThan(current.canvas.clientHeight);
  expect(Math.abs(current.olbiaPixel.x - original.olbiaPixel.x), "zoom should retain the selected city's horizontal anchor")
    .toBeLessThan(4);
  expect(Math.abs(current.olbiaPixel.y - original.olbiaPixel.y), "zoom should retain the selected city's vertical anchor")
    .toBeLessThan(4);
}

function expectCenterInsideEurope(snapshot: MapSnapshot): void {
  expect(snapshot.center[0]).toBeGreaterThanOrEqual(-31);
  expect(snapshot.center[0]).toBeLessThanOrEqual(46);
  expect(snapshot.center[1]).toBeGreaterThanOrEqual(28);
  expect(snapshot.center[1]).toBeLessThanOrEqual(77);
}

async function dragMap(page: Page, from: [number, number], to: [number, number]): Promise<void> {
  const box = await page.locator("canvas.maplibregl-canvas").boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps: 8 });
  await page.mouse.up();
}

test.beforeEach(async ({ context, page }) => {
  mkdirSync(screenshotDir, { recursive: true });
  evidenceByPage.set(page, await installDisconnectedInternetBoundary(context, page));
});

test.afterEach(async ({ page }) => {
  const evidence = evidenceByPage.get(page);
  await Promise.all([...(evidence?.pendingConsoleErrors ?? []), ...(evidence?.pendingBasemapResponses ?? [])]);
  expect(evidence?.externalRequests, "the detailed map attempted a non-loopback request").toEqual([]);
  expect(evidence?.pageErrors, "the detailed map raised an uncaught JavaScript error").toEqual([]);
  expect(evidence?.consoleErrors, "the detailed map logged a console error").toEqual([]);
});

test("local vector detail and native flood tiles refine through street zoom", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await page.goto("/?qa=map&year=2050&defenses=unprotected&flooding=on", { waitUntil: "domcontentloaded" });
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Olbia");
  const olbia = page.getByRole("option", { name: /^Olbia\s+Italy$/iu });
  await expect(olbia).toBeVisible({ timeout: 15_000 });
  await olbia.click();
  await expect(page.getByRole("heading", { level: 1, name: "Olbia", exact: true })).toBeVisible();
  await waitForMapHook(page);
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  const selectedCity = await waitForSettledMap(page);
  const evidence = evidenceByPage.get(page)!;
  await expect.poll(() => evidence.basemapRequests.length, {
    timeout: 30_000, message: "the local Protomaps archive was not requested",
  }).toBeGreaterThan(0);
  await expect.poll(() => evidence.basemapResponses.length, {
    timeout: 30_000, message: "the local Protomaps archive did not return a response",
  }).toBeGreaterThan(0);
  expect(evidence.basemapResponses.every((response) => !response.qaOnly),
    "production QA must use the complete Europe archive rather than the Olbia-only preview").toBe(true);

  await zoomToAtLeast(page, 9);
  const zoom9 = await waitForSettledMap(page);
  await expectCityAnchor(page, selectedCity);
  expect(zoom9.roads, "zoom 9 should render authentic basemap roads").toBeGreaterThan(0);
  expect(zoom9.places, "zoom 9 should render authentic place labels").toBeGreaterThan(0);
  const floodAt9 = maxFloodZoom(evidence);

  await zoomToAtLeast(page, 12);
  const zoom12 = await waitForSettledMap(page);
  await expectCityAnchor(page, selectedCity);
  expect(zoom12.roads).toBeGreaterThan(0);
  expect(zoom12.places).toBeGreaterThan(0);
  const floodAt12 = maxFloodZoom(evidence);
  expect(floodAt12, "flood requests should refine between regional and local zoom").toBeGreaterThan(floodAt9);

  await zoomToAtLeast(page, 15);
  const zoom15 = await waitForSettledMap(page);
  await expectCityAnchor(page, selectedCity);
  await page.screenshot({ path: resolve(screenshotDir, "desktop-olbia-street-z15.png") });
  const diagnostic = JSON.stringify({
    zoom: zoom15.zoom, center: zoom15.center, bounds: zoom15.bounds,
    sourceLayers: zoom15.sourceLayerCounts, layers: zoom15.layerIds,
  });
  expect(zoom15.roads, `street zoom should retain real roads: ${diagnostic}`).toBeGreaterThan(0);
  expect(zoom15.buildings, `street zoom should render real OSM buildings: ${diagnostic}`).toBeGreaterThan(0);
  expect(zoom15.places, `street zoom should retain real place labels: ${diagnostic}`).toBeGreaterThan(0);
  expect(zoom15.layerIds.length, "the style should contain local basemap layers").toBeGreaterThan(0);
  expect(zoom15.floodMaxZoom).toBe(13);
  expect(maxFloodZoom(evidence), "flood requests should reach their native cap").toBe(13);
  expect(evidence.floodTiles.every((tile) => tile.z <= 13), "flood tiles must never over-request beyond z13").toBe(true);
  const streetCanvas = await page.locator("canvas.maplibregl-canvas").screenshot();

  await zoomToAtMost(page, 9.5);
  const zoomedBack = await waitForSettledMap(page);
  const regionalCanvas = await page.locator("canvas.maplibregl-canvas").screenshot();
  expect(regionalCanvas.equals(streetCanvas), "zooming back out should redraw the vector map").toBe(false);
  expect(zoomedBack.roads).toBeGreaterThan(0);
  expect(zoomedBack.buildings).toBeLessThan(zoom15.buildings);
  expect(zoomedBack.canvas.width).toBe(Math.round(zoomedBack.canvas.clientWidth * zoomedBack.canvas.devicePixelRatio));
  expect(zoomedBack.canvas.height).toBe(Math.round(zoomedBack.canvas.clientHeight * zoomedBack.canvas.devicePixelRatio));
  expect(zoomedBack.canvas.transform).toBe("none");

  await page.getByRole("button", { name: "2030", exact: true }).click();
  await page.getByRole("button", { name: "2100", exact: true }).click();
  await page.getByRole("button", { name: "2050", exact: true }).click();
  const canvas = page.locator("canvas.maplibregl-canvas");
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.55);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.48, { steps: 8 });
    await page.mouse.up();
  }
  await expect(page.locator(".atlas-map")).toHaveAttribute("data-layer", "ssp585-2050-unprotected");
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  await waitForSettledMap(page);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(evidence.floodTiles.some((tile) => tile.year === 2050 && tile.protection === "unprotected")).toBe(true);
});

test("mobile zoom keeps the selected city at its visible focus", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-mobile");
  await page.goto("/?qa=map&year=2050&defenses=unprotected&flooding=on", { waitUntil: "domcontentloaded" });
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Olbia");
  const olbia = page.getByRole("option", { name: /^Olbia\s+Italy$/iu });
  await expect(olbia).toBeVisible({ timeout: 15_000 });
  await olbia.click();
  await expect(page.getByRole("heading", { level: 1, name: "Olbia", exact: true })).toBeVisible();
  await waitForMapHook(page);
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  const selectedCity = await waitForSettledMap(page);

  await zoomToAtLeast(page, 12);
  await waitForSettledMap(page);
  await expectCityAnchor(page, selectedCity);

  await zoomToAtLeast(page, 15);
  const zoom15 = await waitForSettledMap(page);
  await expectCityAnchor(page, selectedCity);
  expect(zoom15.roads).toBeGreaterThan(0);
  expect(zoom15.buildings).toBeGreaterThan(0);
  await page.screenshot({ path: resolve(screenshotDir, "mobile-olbia-street-z15.png") });
});

test("Europe-only overview and city camera cannot escape to the world", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "atlas-desktop");
  await page.goto("/?qa=map&year=2050&defenses=unprotected&flooding=on", { waitUntil: "domcontentloaded" });
  await waitForMapHook(page);
  await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 30_000 });
  const desktopOverview = await waitForSettledMap(page);
  expect(desktopOverview.zoom).toBeCloseTo(desktopOverview.minZoom, 3);
  expect(desktopOverview.overviewLand, "the overview must render the prepared Europe geometry").toBeGreaterThan(0);
  expect(desktopOverview.basemapNonSymbols, "coarse global land must stay hidden below zoom 6").toBe(0);
  expect(desktopOverview.pitch).toBe(0);
  expect(desktopOverview.bearing).toBe(0);
  await page.screenshot({ path: resolve(screenshotDir, "desktop-europe-only-overview.png") });

  const zoomOut = page.getByRole("button", { name: "Zoom out" });
  await expect(zoomOut, "the Europe overview should expose that it is already at minimum zoom").toBeDisabled();
  await dragMap(page, [0.8, 0.5], [0.15, 0.2]);
  const resistedOverview = await waitForSettledMap(page);
  await expect(page.locator(".time-heading .map-loading"), "no-op overview navigation must not leave loading feedback stuck")
    .toHaveText("", { timeout: 30_000 });
  expect(resistedOverview.zoom).toBeCloseTo(desktopOverview.minZoom, 3);
  expect(resistedOverview.center[0]).toBeCloseTo(desktopOverview.center[0], 3);
  expect(resistedOverview.center[1]).toBeCloseTo(desktopOverview.center[1], 3);

  await page.setViewportSize({ width: 3200, height: 1650 });
  await expect(page.locator("canvas.maplibregl-canvas")).toHaveJSProperty("clientWidth", 3200);
  const wideOverview = await waitForSettledMap(page);
  expect(wideOverview.zoom).toBeCloseTo(wideOverview.minZoom, 3);
  expect(wideOverview.overviewLand).toBeGreaterThan(0);
  expect(wideOverview.basemapNonSymbols).toBe(0);
  await page.screenshot({ path: resolve(screenshotDir, "wide-europe-only-overview.png") });

  await page.setViewportSize({ width: 1440, height: 1024 });
  await expect(page.locator("canvas.maplibregl-canvas")).toHaveJSProperty("clientWidth", 1440);
  await waitForSettledMap(page);
  const search = page.getByRole("combobox", { name: "Find a city in Europe" });
  await search.fill("Olbia");
  await page.getByRole("option", { name: /^Olbia\s+Italy$/iu }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Olbia", exact: true })).toBeVisible();
  await waitForSettledMap(page);
  await page.getByRole("button", { name: "Hide flood layer" }).click();
  for (const center of [[170, 0], [-170, 0], [170, 85], [-170, 85]] as const) {
    await page.evaluate((target) => {
      const map = (window as typeof window & {
        __SEARISE_ATLAS_MAP__: { jumpTo(options: { center: readonly [number, number]; zoom: number }): void };
      }).__SEARISE_ATLAS_MAP__;
      map.jumpTo({ center: target, zoom: 15 });
    }, center);
    expectCenterInsideEurope(await waitForSettledMap(page));
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("canvas.maplibregl-canvas")).toHaveJSProperty("clientWidth", 390);
  await page.getByRole("button", { name: "European overview" }).click();
  const mobileOverview = await waitForSettledMap(page);
  expect(mobileOverview.zoom).toBeCloseTo(mobileOverview.minZoom, 3);
  expect(mobileOverview.overviewLand).toBeGreaterThan(0);
  expect(mobileOverview.basemapNonSymbols).toBe(0);
  expect(mobileOverview.pitch).toBe(0);
  expect(mobileOverview.bearing).toBe(0);
  await page.screenshot({ path: resolve(screenshotDir, "mobile-europe-only-overview.png") });

  const evidence = evidenceByPage.get(page)!;
  expect(evidence.archiveRequests.length, "the detailed local Europe archive should be the only PMTiles source").toBeGreaterThan(0);
  expect(evidence.archiveRequests.every((request) =>
    new URL(request).pathname === "/atlas-data/basemap/protomaps-europe.pmtiles"
  ), "the Europe-only atlas must never request a world archive").toBe(true);
});

test("cold Europe overview has English labels across reload and detail zoom", async ({ page }, testInfo) => {
  // Playwright creates a fresh context; the route boundary also disables HTTP
  // caching and blocks non-loopback traffic. Check rendered glyph placements,
  // not just source features or the presence of label layers in the style.
  const expectOverviewLabels = (snapshot: MapSnapshot) => {
    expect(snapshot.zoom).toBeLessThan(6);
    expect(snapshot.overviewLabels.country.length).toBeGreaterThanOrEqual(8);
    expect(snapshot.overviewLabels.country).toEqual(expect.arrayContaining(["France", "Spain", "Sweden"]));
    expect(snapshot.overviewLabels.city).toContain("London");
    expect(snapshot.overviewLabels.country).not.toContain("Turkey");
    expect(snapshot.overviewLabels.country.join(" ")).not.toMatch(/Russia|Egypt|United States/u);
    expect(snapshot.overviewLabels.city.join(" ")).not.toMatch(/Istanbul|Moscow|Cairo/u);
    expect(snapshot.basemapNonSymbols).toBe(0);
  };
  await page.goto("/?qa=map", { waitUntil: "domcontentloaded" });
  await waitForMapHook(page);
  expectOverviewLabels(await waitForSettledMap(page));
  await page.screenshot({ path: resolve(screenshotDir, `${testInfo.project.name}-cold-overview-labels.png`) });
  // Share-link normalization intentionally omits the opt-in test hook.
  await page.evaluate(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("qa", "map");
    window.history.replaceState(null, "", url);
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForMapHook(page);
  expectOverviewLabels(await waitForSettledMap(page));

  if (testInfo.project.name === "atlas-desktop") {
    // Match the CSS-pixel dimensions of the owner's high-density screenshot.
    await page.setViewportSize({ width: 1644, height: 1561 });
    const tallOverview = await waitForSettledMap(page);
    expectOverviewLabels(tallOverview);
    expect(tallOverview.overviewLabels.country).toContain("Denmark");
    expect(tallOverview.overviewLabels.sea).toContain("North Sea");
    await page.screenshot({ path: resolve(screenshotDir, "tall-cold-overview-labels.png") });
  }

  for (const zoom of [5.9, 6.1, 5.9]) {
    await page.evaluate((targetZoom) => {
      const map = (window as typeof window & {
        __SEARISE_ATLAS_MAP__: { jumpTo(options: { center: [number, number]; zoom: number }): void };
      }).__SEARISE_ATLAS_MAP__;
      map.jumpTo({ center: [8, 51], zoom: targetZoom });
    }, zoom);
    const snapshot = await waitForSettledMap(page);
    expect(snapshot.places, `place names disappeared at zoom ${zoom}`).toBeGreaterThan(2);
    expect(snapshot.overviewLabels.city.length > 0).toBe(zoom < 6);
  }
  await page.getByRole("button", { name: "European overview" }).click();
  expectOverviewLabels(await waitForSettledMap(page));
});

test("Ukraine includes Crimea and eastern regions on entry and at detail zoom", async ({ page }, testInfo) => {
  await page.goto("/?qa=map", { waitUntil: "domcontentloaded" });
  await waitForMapHook(page);
  await waitForSettledMap(page);
  const controls = await page.evaluate(() => {
    const map = (window as typeof window & { __SEARISE_ATLAS_MAP__: {
      project(point: number[]): { x: number; y: number };
      getCanvas(): HTMLCanvasElement;
      queryRenderedFeatures(point: { x: number; y: number }, options: { layers: string[] }): unknown[];
    } }).__SEARISE_ATLAS_MAP__;
    const canvas = map.getCanvas();
    return Object.entries({ Sevastopol: [33.52, 44.60], Simferopol: [34.1, 44.95],
      Kerch: [36.47, 45.35], Donetsk: [37.8, 48.0], Luhansk: [39.3, 48.57],
      Mariupol: [37.55, 47.1], Kharkiv: [36.23, 49.99], "Eastern border": [40.15, 49.26],
    }).map(([name, point]) => {
      const pixel = map.project(point);
      return { name, insideCamera: pixel.x > 8 && pixel.x < canvas.clientWidth - 8
        && pixel.y > 8 && pixel.y < canvas.clientHeight - 8,
      land: map.queryRenderedFeatures(pixel, { layers: ["atlas-europe-overview-land"] }).length > 0 };
    });
  });
  for (const point of controls) {
    expect(point.insideCamera, `${point.name} was cropped from the initial camera`).toBe(true);
    if (point.name !== "Eastern border") expect(point.land, `${point.name} disappeared from Ukraine`).toBe(true);
  }
  await page.screenshot({ path: resolve(screenshotDir, `${testInfo.project.name}-ukraine-complete-overview.png`) });

  if (testInfo.project.name !== "atlas-desktop") return;
  const boundariesAt = async (center: [number, number]) => {
    await page.evaluate((coordinates) => {
      (window as typeof window & { __SEARISE_ATLAS_MAP__: {
        jumpTo(options: { center: [number, number]; zoom: number }): void;
      } }).__SEARISE_ATLAS_MAP__.jumpTo({ center: coordinates, zoom: 7.3 });
    }, center);
    await waitForSettledMap(page);
    return page.evaluate(() => {
      type Feature = { properties: { disputed?: boolean; kind_detail?: number } };
      const map = (window as typeof window & { __SEARISE_ATLAS_MAP__: {
        querySourceFeatures(source: string, options: { sourceLayer: string }): Feature[];
        queryRenderedFeatures(options: { layers: string[] }): Feature[];
      } }).__SEARISE_ATLAS_MAP__;
      const source = map.querySourceFeatures("atlas-basemap", { sourceLayer: "boundaries" });
      const rendered = map.queryRenderedFeatures({ layers: ["boundaries_country"] });
      return { disputedSource: source.filter((f) => f.properties.disputed === true && f.properties.kind_detail === 2).length,
        disputedRendered: rendered.filter((f) => f.properties.disputed === true).length,
        normalRendered: rendered.filter((f) => f.properties.disputed !== true).length };
    });
  };
  const crimea = await boundariesAt([34, 46]);
  expect(crimea.disputedSource, "the regression must exercise the actual upstream Crimea boundary").toBeGreaterThan(0);
  expect(crimea.disputedRendered, "occupation lines must not appear as Ukraine's country border").toBe(0);
  await page.screenshot({ path: resolve(screenshotDir, "ukraine-crimea-detail.png") });
  const east = await boundariesAt([39, 48.5]);
  expect(east.normalRendered, "recognized international borders must remain visible").toBeGreaterThan(0);
  for (const name of ["Sevastopol", "Simferopol", "Kerch", "Yalta", "Feodosiya"]) {
    const response = await page.request.get(`/atlas-data/europe/search?q=${name}`);
    expect(response.ok()).toBe(true);
    expect((await response.json()).results[0]).toMatchObject({ name, countryCode: "UA", countryName: "Ukraine" });
  }
  await page.getByRole("combobox", { name: "Find a city in Europe" }).fill("Sevastopol");
  await page.getByRole("option", { name: /^Sevastopol\s+Ukraine$/u }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Sevastopol", exact: true })).toBeVisible();
  await expect(page.locator(".atlas-country")).toContainText("Ukraine");
  await waitForSettledMap(page);
  await page.screenshot({ path: resolve(screenshotDir, "ukraine-sevastopol-search.png") });
});
