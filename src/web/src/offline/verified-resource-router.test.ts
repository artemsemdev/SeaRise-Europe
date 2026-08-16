// @vitest-environment node

import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fixtureArtifactPath, fixtureBytes, fixtureReleaseContext, responseBody, FIXTURE_ORIGIN, FIXTURE_RELEASE_ID } from "../test/release-fixture";
import { validateAppAuthority } from "./contracts/v1";
import { validateStorageBudget } from "./contracts/policy";
import { createRangeStore, type RangeStore } from "./range-store";
import {
  createAdmissionReceiptStore,
  type AdmissionLockPort,
  type AdmissionReceiptStore,
} from "./admission-receipt";
import { createVerifiedReleaseResourcePlan, type VerifiedReleaseResourcePlanV1 } from "./release-resource-plan";
import {
  MemoryWholeResourceCache,
  WholeResourceCache,
  type CachePort,
  type CacheStoragePort,
  type WholeResourceCacheDependencies,
  type WholeResourceStore,
} from "./whole-resource-cache";
import { TechnicalFailure, type ReleaseContext, type ResolvedArtifact } from "../domain/release";
import { CogAnalysisArtifactReader } from "../data/cog-analysis-reader";
import { verifiedArtifactBytes } from "../data/artifact-integrity";
import { VerifiedResourceRouter } from "./verified-resource-router";
import { NetworkOnlyPmtilesSource } from "../components/map/pmtiles-network-source";

const subtle = webcrypto.subtle as SubtleCrypto;

class MemoryCache implements CachePort {
  readonly entries = new Map<string, Response>();
  failPut = false;
  async match(key: string): Promise<Response | undefined> { return this.entries.get(key)?.clone(); }
  async put(key: string, response: Response): Promise<void> {
    if (this.failPut) throw new DOMException("quota", "QuotaExceededError");
    this.entries.set(key, response.clone());
  }
  async delete(key: string): Promise<boolean> { return this.entries.delete(key); }
}

class MemoryCaches implements CacheStoragePort {
  readonly stores = new Map<string, MemoryCache>();
  async open(name: string): Promise<MemoryCache> {
    let store = this.stores.get(name);
    if (!store) { store = new MemoryCache(); this.stores.set(name, store); }
    return store;
  }
  async delete(name: string): Promise<boolean> { return this.stores.delete(name); }
  entryCount(): number { return [...this.stores.values()].reduce((sum, store) => sum + store.entries.size, 0); }
}

class TestAdmissionLocks implements AdmissionLockPort {
  readonly #tails = new Map<string, Promise<void>>();

  async request<T>(
    name: string,
    options: Readonly<{ mode: "exclusive"; signal: AbortSignal }>,
    operation: () => Promise<T>,
  ): Promise<T> {
    expect(options.mode).toBe("exclusive");
    const previous = this.#tails.get(name) ?? Promise.resolve();
    let release!: () => void;
    const current = new Promise<void>((resolve) => { release = resolve; });
    this.#tails.set(name, previous.then(() => current));
    await previous;
    try {
      if (options.signal.aborted) throw new DOMException("aborted", "AbortError");
      return await operation();
    } finally {
      release();
    }
  }
}

function authority() {
  return validateAppAuthority({
    contractVersion: 1,
    appBuildId: "app-build-router",
    dataReleaseId: FIXTURE_RELEASE_ID,
    manifestUrl: `${FIXTURE_ORIGIN}/releases/${FIXTURE_RELEASE_ID}/manifest.json`,
    releaseDisposition: "synthetic-fixture",
    precacheSetSha256: "a".repeat(64),
  });
}

function wholeResponse(url: string): Response {
  const path = fixtureArtifactPath(new URL(url));
  const bytes = fixtureBytes(path);
  const artifact = fixtureManifestArtifact(path);
  const response = new Response(responseBody(bytes), {
    status: 200,
    headers: {
      "cache-control": "public, max-age=31536000, immutable",
      "content-length": String(bytes.byteLength),
      "content-type": artifact.mediaType,
      etag: `"sha256-${artifact.sha256}"`,
    },
  });
  Object.defineProperty(response, "url", { value: url });
  return response;
}

let manifestArtifacts: readonly Readonly<{ path: string; mediaType: string; sha256: string }>[] = [];
function fixtureManifestArtifact(path: string) {
  const artifact = manifestArtifacts.find((candidate) => candidate.path === path);
  if (!artifact) throw new Error(`missing fixture artifact ${path}`);
  return artifact;
}

interface Harness {
  readonly context: ReleaseContext;
  readonly plan: VerifiedReleaseResourcePlanV1;
  readonly whole: WholeResourceStore;
  readonly ranges: RangeStore;
  readonly receipts: AdmissionReceiptStore;
  readonly caches: MemoryCaches;
  readonly rangeCalls: RequestInit[];
  readonly rangeUrls: string[];
  readonly router: VerifiedResourceRouter;
  readonly createPeerRouter: () => VerifiedResourceRouter;
  readonly wholeFailure: { enabled: boolean };
}

async function harness(options: Readonly<{
  maxRangeBytes?: number;
  rangeFetch?: typeof fetch;
  localCandidate?: boolean;
  mutateWholeResponse?: (response: Response) => Response | Promise<Response>;
  mutateRangeResponse?: (response: Response, init: RequestInit) => Response | Promise<Response>;
}> = {}): Promise<Harness> {
  const context = await fixtureReleaseContext();
  manifestArtifacts = context.manifest.artifacts;
  const app = authority();
  const rangeIndex = fixtureBytes("analysis/cog-range-integrity.json");
  const plan = await createVerifiedReleaseResourcePlan({
    context,
    appAuthority: app,
    rangeIntegrityBytes: responseBody(rangeIndex),
    localCandidate: options.localCandidate,
  });
  const rangeBytes = plan.rangeCatalog.identities.reduce((sum, identity) =>
    sum + identity.interval.endExclusive - identity.interval.start, 0);
  const budget = validateStorageBudget({
    contractVersion: 1,
    policyId: "verified-router-test",
    maxTotalBytes: (options.maxRangeBytes ?? rangeBytes) + 50_000_000,
    maxWholeResourceBytes: 50_000_000,
    maxRangeBytes: options.maxRangeBytes ?? rangeBytes,
    maxWholeEntries: 64,
    maxRangeEntries: 64,
    highWatermarkBytes: (options.maxRangeBytes ?? rangeBytes) + 40_000_000,
    lowWatermarkBytes: (options.maxRangeBytes ?? rangeBytes) + 30_000_000,
    minQuotaReserveBytes: 0,
    maxQuotaFraction: 0.9,
    leaseTtlMs: 120_000,
    heartbeatMs: 30_000,
    retainedCompletePairs: 2,
    eviction: "unleased-lru",
  });
  const idb = new IDBFactory();
  const locks = new TestAdmissionLocks();
  const ranges = createRangeStore(app, budget, {
    ...(options.localCandidate ? {} : { indexedDB: idb }),
    subtle,
  }, { catalog: plan.rangeCatalog, localCandidate: options.localCandidate });
  const receipts = createAdmissionReceiptStore(app, subtle, {
    ...(options.localCandidate ? {} : { indexedDB: idb }),
    ...(options.localCandidate ? {} : { locks }),
    localCandidate: options.localCandidate,
  });
  const caches = new MemoryCaches();
  let sequence = 0;
  const wholeDependencies: WholeResourceCacheDependencies = {
    applicationOrigin: FIXTURE_ORIGIN,
    cacheStorage: caches,
    digest: (algorithm, bytes) => subtle.digest(algorithm, bytes),
    fetchResource: async (url) => {
      const response = wholeResponse(url);
      return options.mutateWholeResponse?.(response) ?? response;
    },
    nextOperationId: () => `whole-${++sequence}`,
  };
  const whole: WholeResourceStore = options.localCandidate
    ? new MemoryWholeResourceCache(app, wholeDependencies, {
        localCandidate: true,
        maxBytes: 50_000_000,
        maxEntries: 64,
      })
    : new WholeResourceCache(app, wholeDependencies);
  const wholeFailure = { enabled: false };
  const controlledWhole: WholeResourceStore = {
    mode: whole.mode,
    storageProfile: whole.storageProfile,
    fetchAndAdmit: (resource, signal) => whole.fetchAndAdmit(resource, signal),
    fetchAndAdmitBatch: (resources, admissionOptions) => {
      if (wholeFailure.enabled) return Promise.reject(new DOMException("quota", "QuotaExceededError"));
      return whole.fetchAndAdmitBatch(resources, admissionOptions);
    },
    rollbackAdmission: (admission) => whole.rollbackAdmission(admission),
    read: (resource) => whole.read(resource),
    readAccepted: (resource, gate) => wholeFailure.enabled
      ? Promise.resolve(Object.freeze({ state: "miss" as const }))
      : whole.readAccepted(resource, gate),
    inventory: (resources) => whole.inventory(resources),
    close: () => whole.close(),
  };
  const rangeCalls: RequestInit[] = [];
  const rangeUrls: string[] = [];
  const strictRangeFetch: typeof fetch = options.rangeFetch ?? (async (input, init = {}) => {
    rangeCalls.push(init);
    const url = new URL(input instanceof Request ? input.url : input.toString());
    rangeUrls.push(url.href);
    const path = fixtureArtifactPath(url);
    const bytes = fixtureBytes(path);
    const artifact = fixtureManifestArtifact(path);
    const headers = new Headers({
      "accept-ranges": "bytes",
      "cache-control": options.localCandidate
        ? "private, no-store"
        : "public, max-age=31536000, immutable",
      "content-type": artifact.mediaType,
      etag: `"sha256-${artifact.sha256}"`,
    });
    if (init.method === "HEAD") {
      headers.set("content-length", String(bytes.byteLength));
      const response = new Response(null, { status: 200, headers });
      return options.mutateRangeResponse?.(response, init) ?? response;
    }
    const requestHeaders = new Headers(init.headers);
    expect(init.cache).toBe("no-store");
    expect(requestHeaders.get("if-match")).toBe(`"sha256-${artifact.sha256}"`);
    const match = /^bytes=(\d+)-(\d+)$/u.exec(requestHeaders.get("range") ?? "");
    if (!match) throw new Error("exact range required");
    const start = Number(match[1]);
    const end = Number(match[2]);
    const body = bytes.slice(start, end + 1);
    headers.set("content-length", String(body.byteLength));
    headers.set("content-range", `bytes ${start}-${end}/${bytes.byteLength}`);
    const response = new Response(responseBody(body), { status: 206, headers });
    return options.mutateRangeResponse?.(response, init) ?? response;
  });
  const router = new VerifiedResourceRouter({
    releasePlan: plan,
    wholeStore: controlledWhole,
    rangeStore: ranges,
    receiptStore: receipts,
    subtle,
    fetchRange: strictRangeFetch,
  });
  const createPeerRouter = (): VerifiedResourceRouter => new VerifiedResourceRouter({
    releasePlan: plan,
    wholeStore: options.localCandidate
      ? new MemoryWholeResourceCache(app, wholeDependencies, {
          localCandidate: true,
          maxBytes: 50_000_000,
          maxEntries: 64,
        })
      : new WholeResourceCache(app, wholeDependencies),
    rangeStore: createRangeStore(app, budget, {
      ...(options.localCandidate ? {} : { indexedDB: idb }),
      subtle,
    }, { catalog: plan.rangeCatalog, localCandidate: options.localCandidate }),
    receiptStore: createAdmissionReceiptStore(app, subtle, {
      ...(options.localCandidate ? {} : { indexedDB: idb, locks }),
      localCandidate: options.localCandidate,
    }),
    subtle,
    fetchRange: strictRangeFetch,
  });
  return {
    context, plan, whole: controlledWhole, ranges, receipts, caches, rangeCalls,
    rangeUrls, router, createPeerRouter, wholeFailure,
  };
}

beforeEach(() => { manifestArtifacts = []; });

function firstCog(test: Harness) {
  const route = test.plan.routes.find((candidate) => candidate.kind === "analysis-cog-ranges")!;
  if (route.kind !== "analysis-cog-ranges") throw new Error("missing COG route");
  const artifact = {
    artifactId: route.identity.artifactId,
    url: route.identity.canonicalUrl,
    path: route.identity.path,
    mediaType: route.identity.mediaType,
    byteSize: route.identity.byteSize,
    sha256: route.identity.sha256,
  } as ResolvedArtifact;
  const index = test.plan.rangeIndex.artifacts.find((item) => item.artifactId === artifact.artifactId)!;
  return { route, artifact, index, first: route.ranges[0] };
}

async function readFirstCog(
  test: Harness,
  router: VerifiedResourceRouter = test.router,
): Promise<ArrayBuffer> {
  const { artifact, index, first } = firstCog(test);
  await router.cogRangeTransport.validateDelivery(artifact, index, new AbortController().signal);
  return router.cogRangeTransport.readExpandedRange(
    artifact, index, first.interval.start, first.interval.endExclusive, new AbortController().signal,
  );
}

describe("verified resource router", () => {
  it("admits only assessment support without preloading nine COGs, then admits the requested range and serves its offline hit with zero network", async () => {
    const test = await harness();
    const snapshot = await test.router.prepareAssessmentSupport(new AbortController().signal);
    expect(snapshot.gate.resourcePlanSha256).toBe(snapshot.plan.resourcePlanSha256);
    expect(snapshot.plan.wholeResources).toHaveLength(2);
    expect(snapshot.plan.rangeResources).toEqual([]);
    expect(test.rangeCalls).toEqual([]);

    const { first } = firstCog(test);
    const bytes = await readFirstCog(test);
    expect(bytes.byteLength).toBe(first.interval.endExclusive - first.interval.start);
    expect(test.rangeCalls.filter((call) => call.method === "HEAD")).toHaveLength(1);
    expect(test.rangeCalls.filter((call) => call.method === "GET")).toHaveLength(1);
    expect((await test.ranges.inventory()).entryCount).toBe(1);

    test.rangeCalls.length = 0;
    await readFirstCog(test);
    expect(test.rangeCalls).toEqual([]);
  });

  it("wires the scientific COG reader to one selected artifact and preserves cached golden behavior", async () => {
    const test = await harness();
    const forbiddenDefaultFetch = vi.fn<typeof fetch>(() => Promise.reject(new Error("default fetch forbidden")));
    const reader = new CogAnalysisArtifactReader({
      fetch: forbiddenDefaultFetch,
      artifactTransport: test.router.artifactTransport,
      cogRangeTransport: test.router.cogRangeTransport,
    });
    const result = await reader.lookup(
      test.context,
      "ssp2-45",
      2050,
      { latitude: 52, longitude: 4 },
      new AbortController().signal,
    );
    expect(["projection", "unavailable"]).toContain(result.kind);
    expect(forbiddenDefaultFetch).not.toHaveBeenCalled();
    expect(new Set(test.rangeUrls.map((url) => fixtureArtifactPath(new URL(url))))).toEqual(
      new Set(["analysis/ssp2-45/2050.tif"]),
    );
    expect(test.rangeUrls.every((url) => !/ssp1-26|ssp5-85|2030|2100/u.test(url))).toBe(true);

    test.rangeCalls.length = 0;
    test.rangeUrls.length = 0;
    await reader.lookup(
      test.context,
      "ssp2-45",
      2050,
      { latitude: 52, longitude: 4 },
      new AbortController().signal,
    );
    expect(test.rangeCalls).toEqual([]);
    expect(test.rangeUrls).toEqual([]);
  });

  it("serializes concurrent admission for the same requested COG range without receipt conflicts", async () => {
    const test = await harness();
    await test.router.prepareAssessmentSupport(new AbortController().signal);
    const [first, second] = await Promise.all([readFirstCog(test), readFirstCog(test)]);
    expect(new Uint8Array(second)).toEqual(new Uint8Array(first));
    expect(test.rangeCalls.filter((call) => call.method === "HEAD")).toHaveLength(1);
    expect(test.rangeCalls.filter((call) => call.method === "GET")).toHaveLength(1);
  });

  it("serializes two router instances with one pair-scoped lock and cannot roll back the accepted peer", async () => {
    const test = await harness();
    const peer = test.createPeerRouter();
    await Promise.all([
      test.router.prepareAssessmentSupport(new AbortController().signal),
      peer.prepareAssessmentSupport(new AbortController().signal),
    ]);
    const [first, second] = await Promise.all([
      readFirstCog(test, test.router),
      readFirstCog(test, peer),
    ]);
    expect(new Uint8Array(second)).toEqual(new Uint8Array(first));
    expect(test.router.current()?.gate.receiptSha256).toBe(peer.current()?.gate.receiptSha256);
    expect((await test.ranges.inventory()).entryCount).toBe(1);
    test.rangeCalls.length = 0;
    await Promise.all([readFirstCog(test, test.router), readFirstCog(test, peer)]);
    expect(test.rangeCalls).toEqual([]);
    peer.close();
  });

  it("keeps the prior receipt and active result when a cancelled refresh cannot complete", async () => {
    const test = await harness();
    const prior = await test.router.prepareAssessmentSupport(new AbortController().signal);
    const cancelled = new AbortController();
    cancelled.abort();
    await expect(test.router.prepareAssessmentSupport(cancelled.signal)).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "Aborted" },
    });
    expect((await test.receipts.accepted(prior.plan))?.receiptSha256).toBe(prior.gate.receiptSha256);
    const whole = test.plan.routes.find((route) => route.kind === "complete-resource")!;
    if (whole.kind !== "complete-resource") throw new Error("missing whole route");
    const response = await test.router.artifactTransport(new URL(whole.authority.canonicalUrl), {
      signal: new AbortController().signal,
      headers: Object.freeze({ Accept: whole.authority.mediaType }),
    });
    expect(response.status).toBe(200);
  });

  it("keeps the prior receipt and active result when a later coordinated admission fails", async () => {
    const test = await harness();
    const prior = await test.router.prepareAssessmentSupport(new AbortController().signal);
    test.wholeFailure.enabled = true;
    await expect(readFirstCog(test)).rejects.toThrow("quota");
    expect((await test.receipts.accepted(prior.plan))?.receiptSha256).toBe(prior.gate.receiptSha256);
    test.wholeFailure.enabled = false;
    const whole = test.plan.routes.find((route) => route.kind === "complete-resource")!;
    if (whole.kind !== "complete-resource") throw new Error("missing whole route");
    const response = await test.router.artifactTransport(new URL(whole.authority.canonicalUrl), {
      signal: new AbortController().signal,
      headers: Object.freeze({ Accept: whole.authority.mediaType }),
    });
    expect(response.status).toBe(200);
  });

  it("does not expose partial unreceipted bytes after quota failure", async () => {
    const test = await harness({ maxRangeBytes: 1 });
    await test.router.prepareAssessmentSupport(new AbortController().signal);
    await expect(readFirstCog(test)).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "UnsupportedBrowser" },
    });
    expect((await test.ranges.inventory()).entryCount).toBe(0);
  });

  it("classifies an inexact whole-resource response as a non-recoverable integrity failure", async () => {
    const test = await harness({
      mutateWholeResponse: async (response) => new Response(await response.arrayBuffer(), {
        status: response.status,
        headers: { ...Object.fromEntries(response.headers), "content-type": "application/octet-stream" },
      }),
    });
    const whole = test.plan.routes.find((route) =>
      route.kind === "complete-resource" && route.authority.authorityKind === "release-artifact");
    if (!whole || whole.kind !== "complete-resource" ||
        whole.authority.authorityKind !== "release-artifact") throw new Error("missing whole route");

    await expect(test.router.artifactTransport(new URL(whole.authority.canonicalUrl), {
      signal: new AbortController().signal,
      headers: Object.freeze({ Accept: whole.authority.mediaType }),
    })).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "IntegrityFailed", recoverable: false },
    });
    const artifact = test.context.artifact(whole.authority.artifactId);
    await expect(verifiedArtifactBytes(
      artifact,
      new AbortController().signal,
      test.router.artifactTransport,
    )).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "IntegrityFailed", recoverable: false },
    });
  });

  it.each([
    ["HEAD MIME", "HEAD", "content-type"],
    ["HEAD ETag", "HEAD", "etag"],
    ["HEAD cache authority", "HEAD", "cache-control"],
    ["206 Content-Range", "GET", "content-range"],
    ["206 length", "GET", "content-length"],
    ["206 MIME", "GET", "content-type"],
    ["206 ETag", "GET", "etag"],
    ["206 cache authority", "GET", "cache-control"],
  ] as const)("fails technically when strict range delivery loses %s", async (_name, method, header) => {
    const test = await harness({
      mutateRangeResponse: async (response, init) => {
        if (init.method !== method) return response;
        const headers = new Headers(response.headers);
        headers.delete(header);
        return new Response(method === "HEAD" ? null : await response.arrayBuffer(), {
          status: response.status,
          headers,
        });
      },
    });
    await test.router.prepareAssessmentSupport(new AbortController().signal);
    await expect(readFirstCog(test)).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "RangeUnsupported" },
    });
    expect((await test.ranges.inventory()).entryCount).toBe(0);
  });

  it("treats forged plans and mixed COG identities as technical failures", async () => {
    const test = await harness();
    expect(() => new VerifiedResourceRouter({
      releasePlan: { ...test.plan },
      wholeStore: test.whole,
      rangeStore: test.ranges,
      receiptStore: test.receipts,
      subtle,
      fetchRange: vi.fn(),
    })).toThrow(TechnicalFailure);
    await test.router.prepareAssessmentSupport(new AbortController().signal);
    const route = test.plan.routes.find((candidate) => candidate.kind === "analysis-cog-ranges")!;
    if (route.kind !== "analysis-cog-ranges") throw new Error("missing COG route");
    const artifact = {
      artifactId: route.identity.artifactId,
      url: route.identity.canonicalUrl.replace(FIXTURE_RELEASE_ID, "mixed-release"),
      path: route.identity.path,
      mediaType: route.identity.mediaType,
      byteSize: route.identity.byteSize,
      sha256: route.identity.sha256,
    } as ResolvedArtifact;
    const index = test.plan.rangeIndex.artifacts.find((item) => item.artifactId === route.identity.artifactId)!;
    await expect(test.router.cogRangeTransport.validateDelivery(
      artifact, index, new AbortController().signal,
    )).rejects.toBeInstanceOf(TechnicalFailure);
  });

  it("keeps visual PMTiles network-only and out of every persistence store", async () => {
    const test = await harness();
    await test.router.prepareAssessmentSupport(new AbortController().signal);
    const beforeRanges = await test.ranges.inventory();
    const beforeCaches = test.caches.entryCount();
    const pmtiles = test.plan.routes.find((route) =>
      route.kind === "network-only" && route.reason === "visual-pmtiles")!;
    if (pmtiles.kind !== "network-only") throw new Error("missing PMTiles route");
    const payload = fixtureBytes(pmtiles.identity.path);
    const match = /^projection-(ssp1-26|ssp2-45|ssp5-85)-(2030|2050|2100)-pmtiles$/u
      .exec(pmtiles.identity.artifactId)!;
    const source = new NetworkOnlyPmtilesSource(Object.freeze({
      kind: "projection" as const,
      artifactId: pmtiles.identity.artifactId,
      scenario: match[1] as "ssp1-26" | "ssp2-45" | "ssp5-85",
      horizon: Number(match[2]) as 2030 | 2050 | 2100,
      byteSize: pmtiles.identity.byteSize,
      dataReleaseId: test.plan.pair.dataReleaseId,
      sha256: pmtiles.identity.sha256,
      url: pmtiles.identity.canonicalUrl,
      visualOnly: true as const,
    }), { fetch: async (request) => {
      expect(request.cache).toBe("no-store");
      const match = /^bytes=(\d+)-(\d+)$/u.exec(request.headers.get("range") ?? "")!;
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]), payload.byteLength - 1);
      const body = payload.slice(start, end + 1);
      return new Response(responseBody(body), { status: 206, headers: {
        "accept-ranges": "bytes",
        "cache-control": "no-store",
        "content-length": String(body.byteLength),
        "content-range": `bytes ${start}-${end}/${payload.byteLength}`,
        "content-type": "application/vnd.pmtiles",
        etag: `"sha256-${pmtiles.identity.sha256}"`,
      } });
    } });
    await source.getBytes(0, Math.min(16, payload.byteLength), new AbortController().signal);
    expect(await test.ranges.inventory()).toEqual(beforeRanges);
    expect(test.caches.entryCount()).toBe(beforeCaches);
  });

  it("routes an explicit local Candidate through memory-only stores with no Cache Storage or IndexedDB requirement", async () => {
    const test = await harness({ localCandidate: true });
    expect(test.plan.persistence.mode).toBe("memory-only");
    expect(test.whole.mode).toBe("memory-only");
    expect(test.ranges.mode).toBe("memory-only");
    expect(test.receipts.mode).toBe("memory-only");
    await test.router.prepareAssessmentSupport(new AbortController().signal);
    await readFirstCog(test);
    expect(test.caches.entryCount()).toBe(0);
    expect((await test.ranges.inventory()).entryCount).toBe(1);
  });

  it("stores only aggregate resource authority and no personal or scientific result state", async () => {
    const test = await harness();
    const snapshot = await test.router.prepareAssessmentSupport(new AbortController().signal);
    const serialized = JSON.stringify({ snapshot, ranges: await test.ranges.inventory() });
    expect(serialized).not.toMatch(/latitude|longitude|placeId|query|ProjectionAvailable|DataUnavailable|OutOfScope|UnsupportedGeography/u);
  });
});
