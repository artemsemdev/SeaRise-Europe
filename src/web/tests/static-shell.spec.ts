import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { brotliCompressSync } from "node:zlib";

const manifestFixture = JSON.parse(readFileSync(resolve(
  process.cwd(),
  "../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json",
), "utf8")) as {
  dataReleaseId: string;
  artifacts: Array<{ artifactId: string; path: string; byteSize: number; sha256: string }>;
  [key: string]: unknown;
};

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

test("local settlement worker is private, partial-ready, keyboard accessible, and fast on fixture", async ({ page }, testInfo) => {
  const network: string[] = [];
  page.on("request", (request) => network.push(`${request.method()} ${request.url()} ${request.postData() ?? ""}`));
  let releaseCoastal!: () => void;
  const coastalGate = new Promise<void>((resolve) => { releaseCoastal = resolve; });
  await page.route("**/search/europe-coastal.fixture.json", async (route) => {
    await coastalGate;
    await route.continue();
  });

  await page.goto("/");
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  const input = page.getByRole("combobox", { name: /find a city/i });
  await input.focus();
  await input.fill("Athens");
  await expect(page.getByRole("option", { name: /Αθήνα.*Attica, GR/i })).toBeVisible();
  await expect(page.getByRole("status")).toContainText(/coastal settlements are still loading/i);
  const initialization = Number(await page.getByRole("status").getAttribute("data-init-duration-ms"));
  expect(initialization).toBeGreaterThanOrEqual(0);
  expect(initialization).toBeLessThan(1_000);

  releaseCoastal();
  await expect(page.getByRole("status")).toHaveAttribute("data-search-readiness", "all-ready");
  const observations: number[] = [];
  for (const query of ["Málaga", "Athens", "Spring", "Border City", "Islet Village", "malagx", "Athina", "Springfield AA", "Springfield South", "missing", "Málaga", "Athens", "Spring", "Border City", "Islet Village", "malagx", "Athina", "Springfield AA", "Springfield South", "missing"]) {
    await input.fill(query);
    await expect(page.getByRole("status")).not.toContainText(/Searching settlements/i);
    observations.push(Number(await page.getByRole("status").getAttribute("data-query-duration-ms")));
  }
  const ordered = [...observations].sort((left, right) => left - right);
  const percentile = (value: number) => ordered[Math.max(0, Math.ceil(ordered.length * value) - 1)];
  const performanceEvidence = {
    schemaVersion: "1.0.0",
    dataReleaseId: "searise-europe-v1.0.0-20260810-c096aeab4e09",
    dataProvenanceClass: "synthetic-fixture",
    profile: testInfo.project.name,
    initializationMilliseconds: initialization,
    queries: { samples: ordered.length, p50Milliseconds: percentile(0.5), p95Milliseconds: percentile(0.95) },
    workerMemoryBytes: { status: "not-measured" },
    productionClaim: false,
  };
  await testInfo.attach("settlement-search-performance.json", {
    body: Buffer.from(JSON.stringify(performanceEvidence)),
    contentType: "application/json",
  });
  console.log(`[settlement-search-performance] ${JSON.stringify(performanceEvidence)}`);
  expect(percentile(0.95)).toBeLessThan(50);

  await input.fill("Springfield");
  await expect(page.getByRole("option", { name: /Springfield.*North, AA/i })).toBeVisible();
  await expect(page.getByRole("option", { name: /Springfield.*South, BB/i })).toBeVisible();
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(page.getByText(/Springfield, South selected at 50.1, 10.1/i)).toBeVisible();
  await expect(input).toBeFocused();

  await input.fill("PrivateSearchTokenXYZ");
  await expect(page.getByRole("status")).toContainText(/No matching settlement/i);
  expect(network.join("\n")).not.toContain("PrivateSearchTokenXYZ");
  expect(network.filter((request) => request.includes("/search/")).length).toBe(2);

  const scan = await new AxeBuilder({ page }).analyze();
  expect(scan.violations.filter((item) => ["critical", "serious"].includes(item.impact ?? ""))).toEqual([]);
});

test("settlement shard delivery failure remains a technical state", async ({ page }) => {
  await page.route("**/search/europe-core.fixture.json", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/vnd.searise.search-index+json", body: "{}" });
  });
  await page.goto("/");
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeVisible();
  const input = page.getByRole("combobox", { name: /find a city/i });
  await input.focus();
  await input.fill("Athens");
  await expect(page.getByRole("status")).toContainText(/technical failure, not a no-match result/i, { timeout: 10_000 });
  await expect(page.getByText(/No scientific outcome was produced/i)).toBeVisible();
  await expect(page.getByText(/Try another spelling/i)).toHaveCount(0);
});

test("generic static delivery verifies compressed bytes before the pinned Worker decoder", async ({ page }) => {
  const releaseRoot = resolve(
    process.cwd(),
    "../../contracts/release/v1/fixtures/release",
    manifestFixture.dataReleaseId,
  );
  const document = JSON.parse(readFileSync(resolve(releaseRoot, "search/europe-core.fixture.json"), "utf8"));
  document.contentEncoding = "br";
  const compressed = brotliCompressSync(Buffer.from(`${JSON.stringify(document)}\n`));
  const manifest = structuredClone(manifestFixture);
  const core = manifest.artifacts.find(({ artifactId }) => artifactId === "settlements-europe-core")!;
  core.path = "search/europe-core.codepoint-trie.json.br";
  core.byteSize = compressed.length;
  core.sha256 = createHash("sha256").update(compressed).digest("hex");

  await page.route("**/manifest.json", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(manifest) });
  });
  await page.route("**/search/europe-core.codepoint-trie.json.br", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/octet-stream",
      body: compressed,
      headers: { "cache-control": "public, max-age=31536000, immutable" },
    });
  });

  await page.goto("/");
  const input = page.getByRole("combobox", { name: /find a city/i });
  await input.fill("Athens");
  await expect(page.getByRole("option", { name: /Αθήνα.*Attica, GR/i })).toBeVisible();
  await expect(page.getByRole("status")).not.toContainText(/technical failure/i);
});
