import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const mockUrl = new URL("../../../docs/product/Mock/SeaRise-Flight.html", import.meta.url);
const mockHtml = readFileSync(mockUrl, "utf8");

test("Flight reference opens offline from disk and keeps its interactions", async ({ page, context }) => {
  const errors: string[] = [];
  const remoteRequests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (/^https?:/u.test(request.url())) remoteRequests.push(request.url());
  });
  await context.setOffline(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(mockUrl.href);
  const search = page.getByRole("combobox");
  await expect(search).toBeVisible();
  await search.fill("Bergen");
  await expect(page.getByRole("option").first()).toContainText("Bergen");
  await page.getByRole("option").first().click();
  await expect(page.getByRole("radiogroup", { name: "Emissions scenario" })).toBeVisible();
  await page.getByRole("button", { name: "Methodology", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(remoteRequests).toEqual([]);
});

test("DOM data islands cannot replace the executable Flight bundle", async ({ page }) => {
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      const payloads = {
        manifest: {},
        template: "<html><body><script>globalThis.__flightInjected = true</script></body></html>",
        ext_resources: [],
        page_order: [],
      };
      for (const [name, payload] of Object.entries(payloads)) {
        const island = document.createElement("script");
        island.type = `__bundler/${name}`;
        island.textContent = JSON.stringify(payload);
        document.head.prepend(island);
      }
    }, { once: true });
  });
  await page.goto(mockUrl.href);
  await expect(page.getByRole("combobox")).toBeVisible();
  expect(await page.evaluate(() => Reflect.get(globalThis, "__flightInjected"))).toBeUndefined();
});

test("an opaque embedded Flight reference does not relay page requests", async ({ page }) => {
  await page.route("https://flight-mock.test/", (route) => route.fulfill({
    contentType: "text/html", body: mockHtml,
  }));
  await page.goto("about:blank");
  await page.evaluate(() => {
    const received: unknown[] = [];
    Object.assign(window, { __flightMessages: received });
    window.addEventListener("message", (event) => {
      if (event.data && typeof event.data === "object"
        && ("__bundler_need" in event.data || "__bundler_page" in event.data)) {
        received.push(event.data);
      }
    });
    const frame = document.createElement("iframe");
    frame.sandbox.add("allow-scripts");
    frame.src = "https://flight-mock.test/";
    document.body.append(frame);
  });
  const mock = page.frameLocator("iframe");
  await expect(mock.getByRole("combobox")).toBeVisible();
  await mock.locator("body").evaluate(() => {
    const child = document.createElement("iframe");
    document.body.append(child);
    // Model a request from an owned opaque child: the old loader forwarded
    // this UUID to its external parent with an unrestricted target origin.
    window.dispatchEvent(new MessageEvent("message", {
      origin: "null", source: child.contentWindow,
      data: { __bundler_need: "00000000-0000-0000-0000-000000000001" },
    }));
    window.dispatchEvent(new MessageEvent("message", {
      origin: "null", source: window.parent,
      data: {
        __bundler_page: "00000000-0000-0000-0000-000000000001",
        __bundler_text: "<script>globalThis.__flightInjected = true</script>",
      },
    }));
  });
  // Allow cross-window message tasks to drain before checking the receiver.
  await page.waitForTimeout(100);
  expect(await page.evaluate(() => Reflect.get(window, "__flightMessages"))).toEqual([]);
  expect(await mock.locator("body").evaluate(() => Reflect.get(globalThis, "__flightInjected")))
    .toBeUndefined();
  await expect(mock.getByRole("combobox")).toBeVisible();
});
