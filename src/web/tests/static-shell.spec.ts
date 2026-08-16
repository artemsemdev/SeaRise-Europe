import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { isForbiddenApplicationApiPath } from "../src/test/application-api-boundary";

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
    const path = new URL(request.url()).pathname;
    if (isForbiddenApplicationApiPath(path)) forbiddenRequests.push(path);
  });

  await page.goto("/");
  await expectStaticDocumentSecurity(page);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Take me there.",
  );
  await expect(page.getByRole("button", { name: "Methodology and sources" })).toBeEnabled();
  await expect(page.getByRole("combobox", { name: /find a city, town, or village/i })).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "SeaRise Europe home" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Methodology and sources" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("combobox", { name: /find a city, town, or village/i })).toBeFocused();
  await expect(page.locator(".flight-legend")).toHaveCount(0);
  const mapControls = page.locator(".maplibregl-control-container");
  await expect(mapControls).toHaveCount(1);
  await expect(mapControls).toHaveAttribute("aria-hidden", "true");
  await expect(mapControls).toHaveAttribute("inert", "");
  await expect(page.locator('[aria-live]:not([aria-live="off"]), [role="status"]')).toHaveCount(1);
  await expect(page.getByText(/Synthetic fixture · illustrative only/i)).toBeVisible();
  await expect(page.getByText(/Release contract ready · 9 exact combinations/i)).toBeAttached();

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

test("API inspection exposes the production-like HEAD, CORS-header, and byte-range contract", async ({ page }) => {
  // APIRequestContext can inspect the configured headers, but it does not
  // enforce browser CORS. Public cross-origin enforcement remains a #65 gate.
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
    contentLength: "216928",
    etag: '"sha256-595338f5d3f439497b3bb0992c54f57c7b3514a01806286baa684cf570d21721"',
  });
  expect(observed.ranged).toMatchObject({
    status: 206,
    acceptRanges: "bytes",
    contentLength: "32",
    contentRange: "bytes 16-47/216928",
    etag: observed.head.etag,
  });
  expect(observed.ranged.bytes).toHaveLength(32);
  expect(malformed.status()).toBe(416);
  expect(malformed.headers()["content-range"]).toBe("bytes */216928");

  expect(head.headers()["access-control-allow-origin"]).toBe("http://127.0.0.1:4173");
  expect(head.headers()["access-control-allow-methods"]).toBe("GET, HEAD");
  expect(head.headers()["access-control-expose-headers"]).toBe(
    "Accept-Ranges, Content-Length, Content-Range, ETag",
  );
  expect(head.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");
});

test("page context verifies a later COG chunk and measures cold versus cached lookup", async ({ page }, testInfo) => {
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
    const reader = new runtime.CogAnalysisArtifactReader();
    const lookup = () => reader.lookup(
      context,
      "ssp2-45",
      2050,
      { latitude: 51.9244, longitude: 4.4777 },
      new AbortController().signal,
    );
    const coldStarted = performance.now();
    const result = await lookup();
    const coldMilliseconds = performance.now() - coldStarted;
    const cachedMilliseconds: number[] = [];
    const cachedResults: unknown[] = [];
    for (let sample = 0; sample < 5; sample += 1) {
      const cachedStarted = performance.now();
      cachedResults.push(await lookup());
      cachedMilliseconds.push(performance.now() - cachedStarted);
    }
    const rangeIndex = await originalFetch(
      `/releases/${releaseId}/analysis/cog-range-integrity.json`,
    ).then((response) => response.json());
    const malformedRange = await originalFetch(artifactSuffix, {
      headers: { Range: "bytes=0-1,4-5" },
    });
    return {
      calls,
      result,
      cachedResultsMatch: cachedResults.every(
        (cached) => JSON.stringify(cached) === JSON.stringify(result),
      ),
      timing: { coldMilliseconds, cachedMilliseconds },
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
  expect(identity.byteSize).toBe(216928);
  expect(identity.chunks).toHaveLength(4);
  expect(observed.malformedRange).toEqual({
    status: 416,
    contentRange: "bytes */216928",
  });
  const head = observed.calls.find((call) => call.method === "HEAD");
  expect(head).toMatchObject({
    status: 200,
    contentLength: identity.byteSize,
    acceptRanges: "bytes",
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
  const laterChunk = identity.chunks.at(-1) as {
    start: number;
    endExclusive: number;
    sha256: string;
  };
  expect(laterChunk.start).toBeGreaterThan(65_536);
  const laterCall = ranged.find((call) => {
    const match = /^bytes=(\d+)-(\d+)$/.exec(call.range ?? "");
    return match !== null
      && Number(match[1]) <= laterChunk.start
      && Number(match[2]) + 1 >= laterChunk.endExclusive;
  });
  const laterChunkVerified = laterCall?.chunkHashes.includes(laterChunk.sha256) ?? false;
  expect(laterChunkVerified).toBe(true);
  expect(observed.cachedResultsMatch).toBe(true);

  const cached = [...observed.timing.cachedMilliseconds].sort((left, right) => left - right);
  const cachedP95 = cached[Math.ceil(cached.length * 0.95) - 1];
  const budgets = {
    coldMaximumMilliseconds: 2_500,
    cachedP95MaximumMilliseconds: 100,
  };
  const performanceEvidence = {
    schemaVersion: "1.0.0",
    dataReleaseId: releaseId,
    dataProvenanceClass: "synthetic-fixture",
    artifact: {
      path: multichunkArtifactPath,
      byteSize: identity.byteSize,
      sha256: identity.sha256,
    },
    profile: `${testInfo.project.name}: production-built page context on loopback`,
    scope: "cold reader lookup after manifest load versus same-reader in-memory cache",
    budgets,
    cold: { samples: 1, milliseconds: observed.timing.coldMilliseconds },
    cached: { samples: cached.length, p95Milliseconds: cachedP95 },
    delivery: {
      rangeRequests: ranged.length,
      transferredBytes: ranged.reduce((total, call) => total + call.contentLength, 0),
      artifactBytes: identity.byteSize,
      laterChunk: {
        start: laterChunk.start,
        endExclusive: laterChunk.endExclusive,
        sha256: laterChunk.sha256,
        verified: laterChunkVerified,
      },
    },
    candidatePerformanceClaim: false,
    publicHostingPerformanceClaim: false,
  };
  await testInfo.attach("cog-lookup-performance.json", {
    body: Buffer.from(JSON.stringify(performanceEvidence)),
    contentType: "application/json",
  });
  console.log(`[cog-lookup-performance] ${JSON.stringify(performanceEvidence)}`);
  expect(observed.timing.coldMilliseconds).toBeLessThan(budgets.coldMaximumMilliseconds);
  expect(cachedP95).toBeLessThan(budgets.cachedP95MaximumMilliseconds);
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
  const searchStatus = page.locator(".search-shell .status[data-search-readiness]");
  const input = page.getByRole("combobox", { name: /find a city/i });
  await input.focus();
  await input.fill("Athens");
  await expect(page.getByRole("option", { name: /Αθήνα.*Attica, GR/i })).toBeVisible();
  await expect(searchStatus).toContainText(/coastal settlements are still loading/i);
  const initialization = Number(await searchStatus.getAttribute("data-init-duration-ms"));
  expect(initialization).toBeGreaterThanOrEqual(0);
  expect(initialization).toBeLessThan(1_000);

  releaseCoastal();
  await expect(searchStatus).toHaveAttribute("data-search-readiness", "all-ready");
  const observations: number[] = [];
  for (const query of ["Málaga", "Athens", "Spring", "Border City", "Islet Village", "malagx", "Athina", "Springfield AA", "Springfield South", "missing", "Málaga", "Athens", "Spring", "Border City", "Islet Village", "malagx", "Athina", "Springfield AA", "Springfield South", "missing"]) {
    await input.fill(query);
    await expect(searchStatus).not.toContainText(/Searching settlements/i);
    observations.push(Number(await searchStatus.getAttribute("data-query-duration-ms")));
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
  await expect(page.locator(".selection-status")).toContainText(/accepted projection is shown in the result panel/i);
  await expect(page.locator(".projection-panel__location")).toContainText(/50\.10000°, 10\.10000°/i);
  await expect(input).toHaveCount(0);

  await page.getByRole("button", { name: /reset selection and choose another place/i }).click();
  await expect(input).toBeVisible();
  await input.focus();

  await input.fill("PrivateSearchTokenXYZ");
  await expect(searchStatus).toContainText(/No matching places found in the loaded index/i);
  await expect(page.locator(".search-shell .search-empty")).toContainText(
    /Check the spelling or try a nearby city, town, or village/i,
  );
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
  await expect(page.locator(".projection-panel")).toHaveAttribute("data-phase", "integrity-error", { timeout: 10_000 });
  await expect(page.locator('.projection-panel [role="alert"]')).toContainText(
    /technical failure.*not a DataUnavailable scientific outcome/i,
  );
  await expect(page.locator("[data-outcome]")).toHaveCount(0);
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
  const searchStatus = page.locator(".search-shell .status[data-search-readiness]");
  const input = page.getByRole("combobox", { name: /find a city/i });
  await input.fill("Athens");
  await expect(page.getByRole("option", { name: /Αθήνα.*Attica, GR/i })).toBeVisible();
  await expect(searchStatus).not.toContainText(/technical failure/i);
});
