import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

test("retired Lab links open only the coastal atlas and preserve the selected view", async ({ page }, info) => {
  test.skip(!["atlas-desktop", "atlas-mobile"].includes(info.project.name));
  const requests: string[] = [], errors: string[] = [];
  page.on("request", (request) => requests.push(new URL(request.url()).pathname));
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?qa=map&model=searise&viewMode=baseline&year=2050&defenses=protected&compare=on&view=12.25,45.43,10&point=12.2486111,45.4511111");

  async function expectCoastalAtlas() {
    await expect(page.getByTestId("atlas-map")).toHaveAttribute("data-model", "coclico");
    await expect(page.locator(".time-heading .map-loading")).toHaveText("", { timeout: 90_000 });
    await expect(page.getByTestId("point-inspection")).not.toHaveAttribute("data-state", "loading");
    await expect(page.getByTestId("point-inspection")).toContainText("One 25 m model cell");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open Lab", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("own-model-notice")).toHaveCount(0);
    await expect(page.getByLabel("Calculation view")).toHaveCount(0);
    await expect(page.getByLabel("Projection year")).toBeEnabled();
    await expect.poll(() => page.evaluate(() => {
      const map = (window as unknown as { __SEARISE_ATLAS_MAP__?: import("maplibre-gl").Map }).__SEARISE_ATLAS_MAP__;
      return map ? Boolean(map.getLayer("study-area-outline") || map.getSource("study-areas")) : null;
    }), { timeout: 30_000 }).toBe(false);
    const query = new URL(page.url()).searchParams;
    expect(query.has("model")).toBe(false);
    expect(query.has("viewMode")).toBe(false);
    expect(query.get("defenses")).toBe("protected");
    expect(query.get("point")).toBe("12.2486111,45.4511111");
    expect(query.get("view")).toBe("12.250000,45.430000,10.0000");
  }

  await expectCoastalAtlas();
  await expect(page.getByTestId("atlas-map")).toHaveAttribute("data-year", "2100");
  await expect(page.getByRole("button", { name: "Exit comparison" })).toBeVisible();
  await page.getByRole("button", { name: "Exit comparison" }).click();
  for (const year of [2030, 2050, 2100]) {
    await page.getByRole("button", { name: String(year), exact: true }).click();
    await expect(page.getByTestId("atlas-map")).toHaveAttribute("data-year", String(year));
    await expectCoastalAtlas();
    expect(requests.some((path) => path.startsWith(`/atlas-data/tiles/${year}/protected/`))).toBe(true);
  }
  if (info.project.name === "atlas-mobile") await page.getByRole("button", { name: "More detail", exact: true }).click();
  await expect(page.getByRole("group", { name: "Coastal defenses" })).toBeVisible();
  const screenshotDir = resolve(import.meta.dirname, "../../../../.cache/atlas-qa/no-lab");
  mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, `${info.project.name}.png`) });
  await page.getByRole("button", { name: "About the map", exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole("dialog")).toContainText("CoCliCo");
  await expect(page.getByRole("dialog")).not.toContainText(/experimental|calculation lab|model baseline/i);
  await page.getByRole("button", { name: "Close map information" }).click();
  // Restoring browser history must not reactivate the retired source either.
  await page.evaluate(() => {
    history.pushState(null, "", `${location.href}&model=searise&viewMode=additional&qa=map`);
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expectCoastalAtlas();
  await page.goto(`${page.url()}&qa=map`);
  await expectCoastalAtlas();
  expect(requests.filter((path) => path.startsWith("/atlas-data/own"))).toEqual([]);
  expect(errors).toEqual([]);
});
