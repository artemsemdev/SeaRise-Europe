import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const forbiddenPaths = ["ass" + "ess", "geo" + "code", "con" + "fig"];
const expectedCsp = "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'";

async function expectStaticDocumentSecurity(page: import("@playwright/test").Page) {
  const csp = page.locator('meta[http-equiv="Content-Security-Policy"]');
  await expect(csp).toHaveAttribute("content", expectedCsp);
  expect((await csp.getAttribute("content"))?.split("; ")).toEqual(expectedCsp.split("; "));
  expect(await csp.getAttribute("content")).not.toContain("frame-ancestors");
  await expect(page.locator('meta[name="referrer"]')).toHaveAttribute("content", "no-referrer");
}

test("landing shell is static, keyboard reachable, and has no serious accessibility findings", async ({ page }) => {
  const forbiddenRequests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname.toLowerCase();
    if (forbiddenPaths.some((part) => path.includes(part))) forbiddenRequests.push(path);
  });

  await page.goto("/");
  await expectStaticDocumentSecurity(page);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Take me there");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await expect(page.getByText(/Synthetic fixture · illustrative only/i)).toBeVisible();
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();

  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
  expect(forbiddenRequests).toEqual([]);
});

test("document CSP blocks an unlisted network origin before a request leaves the page", async ({ page }) => {
  const blockedOriginRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith("https://csp-probe.invalid/")) {
      blockedOriginRequests.push(request.url());
    }
  });

  await page.goto("/");
  await expectStaticDocumentSecurity(page);
  const rejectedByCsp = await page.evaluate(async () => {
    try {
      await fetch("https://csp-probe.invalid/not-allowed");
      return false;
    } catch {
      return true;
    }
  });

  expect(rejectedByCsp).toBe(true);
  expect(blockedOriginRequests).toEqual([]);
});

test("manifest delivery failure has bounded same-release retry", async ({ page }) => {
  const manifestPaths = new Set<string>();
  await page.route("**/releases/**/manifest.json", async (route) => {
    manifestPaths.add(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /retry pinned release/i }).click();
  await page.getByRole("button", { name: /retry pinned release/i }).click();

  await expect(page.getByText(/retry limit reached/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /retry pinned release/i })).toHaveCount(0);
  expect([...manifestPaths]).toEqual([
    "/releases/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json",
  ]);
});

test("architecture direct navigation works from static output", async ({ page }) => {
  await page.goto("/about/architecture/");
  await expectStaticDocumentSecurity(page);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Static-first");
  await expect(page.getByText(/synthetic fixture/i).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /back to explorer/i })).toHaveAttribute("href", "/");
});

test("production-like release delivery exposes exact HEAD, CORS, and byte-range identity", async ({ page }) => {
  const artifactUrl =
    "http://127.0.0.1:8091/releases/searise-europe-v1.0.0-20260810-c096aeab4e09/analysis/ssp2-45/2050.tif";
  const head = await page.request.head(artifactUrl, {
    headers: { Origin: "http://127.0.0.1:4173" },
  });
  const ranged = await page.request.get(artifactUrl, {
    headers: { Origin: "http://127.0.0.1:4173", Range: "bytes=16-47" },
  });
  const observed = {
    head: {
      status: head.status(),
      acceptRanges: head.headers()["accept-ranges"],
      contentLength: head.headers()["content-length"],
      etag: head.headers().etag,
    },
    ranged: {
      status: ranged.status(),
      acceptRanges: ranged.headers()["accept-ranges"],
      contentLength: ranged.headers()["content-length"],
      contentRange: ranged.headers()["content-range"],
      etag: ranged.headers().etag,
      bytes: Array.from(await ranged.body()),
    },
  };

  expect(observed.head).toEqual({
    status: 200,
    acceptRanges: "bytes",
    contentLength: "20320",
    etag: '"sha256-d7998337ead737320cba98772284c7e7ee9372573f65e72f100071f38b90391f"',
  });
  expect(observed.ranged).toMatchObject({
    status: 206,
    acceptRanges: "bytes",
    contentLength: "32",
    contentRange: "bytes 16-47/20320",
    etag: observed.head.etag,
  });
  expect(observed.ranged.bytes).toHaveLength(32);

  expect(head.headers()["access-control-allow-origin"]).toBe("http://127.0.0.1:4173");
  expect(head.headers()["access-control-allow-methods"]).toBe("GET, HEAD");
  expect(head.headers()["access-control-expose-headers"]).toBe(
    "Accept-Ranges, Content-Length, Content-Range, ETag",
  );
  expect(head.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
});
