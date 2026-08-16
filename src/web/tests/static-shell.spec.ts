import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const forbiddenPaths = ["ass" + "ess", "geo" + "code", "con" + "fig"];
const expectedCsp = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'";
const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const multichunkArtifactPath = "analysis/ssp2-45/2050.tif";
const viteManifest = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../dist/vite-manifest.json"), "utf8"),
) as Record<string, { readonly file: string }>;
const scientificRuntimeUrl = `/${viteManifest["src/scientific-runtime.ts"].file}`;

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
  const artifactUrl = `http://127.0.0.1:8091/releases/${releaseId}/${multichunkArtifactPath}`;
  const head = await page.request.head(artifactUrl, {
    headers: { Origin: "http://127.0.0.1:4173" },
  });
  const ranged = await page.request.get(artifactUrl, {
    headers: { Origin: "http://127.0.0.1:4173", Range: "bytes=16-47" },
  });
  const malformed = await page.request.get(artifactUrl, {
    headers: { Origin: "http://127.0.0.1:4173", Range: "bytes=0-1,4-5" },
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
    contentLength: "139264",
    etag: '"sha256-9630a20038a11e577a2203db0ba9ec03e79c295d4aaf945886ca4d9fe58411f7"',
  });
  expect(observed.ranged).toMatchObject({
    status: 206,
    acceptRanges: "bytes",
    contentLength: "32",
    contentRange: "bytes 16-47/139264",
    etag: observed.head.etag,
  });
  expect(observed.ranged.bytes).toHaveLength(32);
  expect(malformed.status()).toBe(416);
  expect(malformed.headers()["content-range"]).toBe("bytes */139264");

  expect(head.headers()["access-control-allow-origin"]).toBe("http://127.0.0.1:4173");
  expect(head.headers()["access-control-allow-methods"]).toBe("GET, HEAD");
  expect(head.headers()["access-control-expose-headers"]).toBe(
    "Accept-Ranges, Content-Length, Content-Range, ETag",
  );
  expect(head.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
});

test("page context performs an exact multichunk COG lookup under the shipped CSP", async ({ page }) => {
  await page.goto("/");
  await expectStaticDocumentSecurity(page);

  const observed = await page.evaluate(async ({ releaseId, runtimeUrl, artifactPath }) => {
    const artifactSuffix = `/releases/${releaseId}/${artifactPath}`;
    const calls: Array<{
      method: string;
      range: string | null;
      status: number;
      contentLength: number;
      contentRange: string | null;
      acceptRanges: string | null;
      allowOrigin: string | null;
      chunkHashes: string[];
    }> = [];
    const originalFetch = window.fetch.bind(window);
    const hex = (bytes: ArrayBuffer) =>
      Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init);
      const url = new URL(input instanceof Request ? input.url : input.toString(), location.href);
      if (url.pathname.endsWith(artifactSuffix)) {
        const method = init?.method ?? (input instanceof Request ? input.method : "GET");
        const range = new Headers(init?.headers).get("range");
        const body = method === "HEAD" ? new Uint8Array() : new Uint8Array(await response.clone().arrayBuffer());
        const chunkHashes: string[] = [];
        for (let offset = 0; offset < body.byteLength; offset += 65_536) {
          chunkHashes.push(hex(await crypto.subtle.digest("SHA-256", body.slice(offset, offset + 65_536))));
        }
        calls.push({
          method,
          range,
          status: response.status,
          contentLength: Number(response.headers.get("content-length") ?? "0"),
          contentRange: response.headers.get("content-range"),
          acceptRanges: response.headers.get("accept-ranges"),
          allowOrigin: response.headers.get("access-control-allow-origin"),
          chunkHashes,
        });
      }
      return response;
    };

    const runtime = await import(runtimeUrl) as {
      ManifestRepository: new (options: {
        manifestUrl: string;
        allowedOrigins: string[];
        expectedDisposition: "synthetic-fixture";
      }) => { load(id: string, signal: AbortSignal): Promise<unknown> };
      CogAnalysisArtifactReader: new () => {
        lookup(
          context: unknown,
          scenario: "ssp2-45",
          horizon: 2050,
          coordinates: { latitude: number; longitude: number },
          signal: AbortSignal,
        ): Promise<unknown>;
      };
    };
    const repository = new runtime.ManifestRepository({
      manifestUrl: `${location.origin}/releases/${releaseId}/manifest.json`,
      allowedOrigins: [location.origin],
      expectedDisposition: "synthetic-fixture",
    });
    const context = await repository.load(releaseId, new AbortController().signal);
    const result = await new runtime.CogAnalysisArtifactReader().lookup(
      context,
      "ssp2-45",
      2050,
      { latitude: 51.9244, longitude: 4.4777 },
      new AbortController().signal,
    );
    const rangeIndex = await originalFetch(
      `/releases/${releaseId}/analysis/cog-range-integrity.json`,
    ).then((response) => response.json());
    const malformedRange = await originalFetch(artifactSuffix, {
      headers: { Range: "bytes=0-1,4-5" },
    });
    return {
      calls,
      result,
      rangeIndex,
      malformedRange: {
        status: malformedRange.status,
        contentRange: malformedRange.headers.get("content-range"),
      },
    };
  }, { releaseId, runtimeUrl: scientificRuntimeUrl, artifactPath: multichunkArtifactPath });

  expect(observed.result).toMatchObject({
    kind: "projection",
    source: {
      locationId: 1003800040,
      latitude: 52,
      longitude: 4,
      distanceKilometres: 33.792469,
    },
    lowerMillimetres: 156,
    medianMillimetres: 247,
    upperMillimetres: 351,
  });
  const identity = observed.rangeIndex.artifacts.find(
    (artifact: { artifactId: string }) => artifact.artifactId === "projection-ssp2-45-2050-cog",
  );
  expect(identity.byteSize).toBe(139264);
  expect(identity.chunks).toHaveLength(3);
  expect(observed.malformedRange).toEqual({
    status: 416,
    contentRange: "bytes */139264",
  });
  const head = observed.calls.find((call) => call.method === "HEAD");
  expect(head).toMatchObject({
    status: 200,
    contentLength: identity.byteSize,
    acceptRanges: "bytes",
    allowOrigin: "http://127.0.0.1:4173",
  });
  const ranged = observed.calls.filter((call) => call.method !== "HEAD");
  expect(ranged.length).toBeGreaterThan(0);
  expect(ranged.every((call) => call.status === 206 && call.acceptRanges === "bytes")).toBe(true);
  expect(ranged.reduce((total, call) => total + call.contentLength, 0)).toBeLessThan(identity.byteSize);
  for (const call of ranged) {
    const match = /^bytes=(\d+)-(\d+)$/.exec(call.range ?? "");
    expect(match).not.toBeNull();
    const start = Number(match![1]);
    const endExclusive = Number(match![2]) + 1;
    const expectedChunks = identity.chunks.filter(
      (chunk: { start: number; endExclusive: number }) =>
        chunk.start >= start && chunk.endExclusive <= endExclusive,
    );
    expect(call.contentRange).toBe(`bytes ${start}-${endExclusive - 1}/${identity.byteSize}`);
    expect(call.chunkHashes).toEqual(
      expectedChunks.map((chunk: { sha256: string }) => chunk.sha256),
    );
  }
});

test("local settlement worker is private, partial-ready, keyboard accessible, and fast on fixture", async ({ page }, testInfo) => {
  const network: string[] = [];
  page.on("request", (request) => network.push(`${request.method()} ${request.url()} ${request.postData() ?? ""}`));
  let releaseCoastal!: () => void;
  const coastalGate = new Promise<void>((resolve) => { releaseCoastal = resolve; });
  await page.route("**/search/europe-coastal.codepoint-trie.json.br", async (route) => {
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
  await page.route("**/search/europe-core.codepoint-trie.json.br", async (route) => {
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

test("exact CSP permits the real Brotli Worker while blocking JavaScript eval", async ({ page }) => {
  await page.route("**/csp-eval-probe.js", async (route) => {
    await route.fulfill({
      contentType: "text/javascript",
      body: `globalThis.__cspEvalProbe = {
        evalBlocked: (() => { try { globalThis.eval("1 + 1"); return false; } catch { return true; } })(),
        functionBlocked: (() => { try { return Function("return 2")() !== 2; } catch { return true; } })()
      };`,
    });
  });
  await page.goto("/");
  await expectStaticDocumentSecurity(page);
  await page.evaluate(() => {
    const probe = document.createElement("script");
    probe.src = "/csp-eval-probe.js";
    document.head.append(probe);
  });
  await expect.poll(() => page.evaluate(() => Reflect.get(globalThis, "__cspEvalProbe")))
    .toEqual({ evalBlocked: true, functionBlocked: true });
  const input = page.getByRole("combobox", { name: /find a city/i });
  await input.fill("Athens");
  await expect(page.getByRole("option", { name: /Αθήνα.*Attica, GR/i })).toBeVisible();
  await expect(page.getByRole("status")).not.toContainText(/technical failure/i);
});
