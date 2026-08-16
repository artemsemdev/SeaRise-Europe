import { describe, expect, it, vi } from "vitest";
import { OFFLINE_WORKER_PROTOCOL } from "./contracts/policy";
import { createServiceWorkerRuntime, type EmbeddedPrecacheV1 } from "./service-worker-runtime";

const A = "a".repeat(64);
const release = "release-a";
const origin = "https://static.example";
const embedded: EmbeddedPrecacheV1 = {
  contractVersion: 1,
  appBuildId: "build-a",
  dataReleaseId: release,
  releaseDisposition: "synthetic-fixture",
  manifestPath: `/releases/${release}/manifest.json`,
  urls: ["/", "/assets/app.js", `/releases/${release}/manifest.json`],
  precacheSetSha256: A,
};

function harness(fetchOverride?: (request: Request) => Promise<Response>) {
  const entries = new Map<string, Response>();
  const names = new Set<string>();
  const deleted: string[] = [];
  const cache = {
    match: vi.fn(async (url: string) => entries.get(url)),
    put: vi.fn(async (url: string, response: Response) => { entries.set(url, response); }),
  };
  const caches = {
    open: vi.fn(async (name: string) => { names.add(name); return cache; }),
    delete: vi.fn(async (name: string) => {
      deleted.push(name);
      entries.clear();
      return names.delete(name);
    }),
    keys: vi.fn(async () => [...names]),
  };
  const fetcher = vi.fn(fetchOverride ?? (async (request: Request) => new Response("ok", {
    status: 200,
    headers: new URL(request.url).pathname.endsWith("manifest.json")
      ? { "Content-Type": "application/json" }
      : undefined,
  })));
  return { runtime: createServiceWorkerRuntime(embedded, { origin, caches, fetch: fetcher }), cache, caches, deleted, entries, fetcher, names };
}

function request(path: string, overrides: Partial<{ method: string; mode: string; headers: Headers }> = {}) {
  return {
    url: `${origin}${path}`,
    method: overrides.method ?? "GET",
    mode: overrides.mode ?? "same-origin",
    headers: overrides.headers ?? new Headers(),
  };
}

describe("service worker shell runtime", () => {
  it("refuses unapproved release dispositions at the untyped JSON boundary", () => {
    expect(() => createServiceWorkerRuntime(
      { ...embedded, releaseDisposition: "private-engineering" } as unknown as EmbeddedPrecacheV1,
      { origin, caches: harness().caches, fetch: vi.fn() },
    )).toThrow(/disposition/);
  });

  it("populates only a new exact-pair cache and reuses a completed cache", async () => {
    const test = harness();
    await test.runtime.install();
    expect(test.fetcher).toHaveBeenCalledTimes(3);
    expect([...test.entries.keys()]).toEqual(embedded.urls.map((path) => `${origin}${path}`));
    await test.runtime.install();
    expect(test.fetcher).toHaveBeenCalledTimes(3);
    expect(test.deleted).toEqual([]);
  });

  it.each(["partial", "policy-invalid"] as const)(
    "deletes and rebuilds a %s existing exact-name cache",
    async (failure) => {
      const test = harness();
      test.names.add(test.runtime.cacheName);
      test.entries.set(`${origin}/`, new Response("shell"));
      if (failure === "policy-invalid") {
        test.entries.set(`${origin}/assets/app.js`, new Response("app"));
        test.entries.set(`${origin}${embedded.manifestPath}`, new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
        }));
      }

      await test.runtime.install();

      expect(test.deleted).toEqual([test.runtime.cacheName]);
      expect(test.fetcher).toHaveBeenCalledTimes(3);
      expect([...test.entries.keys()]).toEqual(embedded.urls.map((path) => `${origin}${path}`));
    },
  );

  it("rolls back only its new cache on failed or private manifest delivery", async () => {
    const test = harness(async (value) => new Response("{}", {
      status: 200,
      headers: new URL(value.url).pathname.endsWith("manifest.json")
        ? { "Content-Type": "application/json", "Cache-Control": "private, no-store" }
        : undefined,
    }));
    await expect(test.runtime.install()).rejects.toThrow(/Precache response is invalid/);
    expect(test.deleted).toEqual([test.runtime.cacheName]);
  });

  it("serves exact cached resources and canonicalizes only root navigation queries", async () => {
    const test = harness();
    test.entries.set(`${origin}/`, new Response("shell"));
    expect(await (await test.runtime.fetch(request("/?scenario=ssp2-45", { mode: "navigate" }))!)!.text()).toBe("shell");
    expect(test.cache.match).toHaveBeenCalledWith(`${origin}/`);
    expect(test.runtime.fetch(request("/assets/app.js?query=private"))).toBeUndefined();
    expect(test.entries.has(`${origin}/?scenario=ssp2-45`)).toBe(false);
  });

  it("bypasses ranges, non-GET, cross-origin, architecture, and release artifacts", () => {
    const test = harness();
    expect(test.runtime.fetch(request("/assets/app.js", { headers: new Headers({ Range: "bytes=0-1" }) }))).toBeUndefined();
    expect(test.runtime.fetch(request("/assets/app.js", { method: "POST" }))).toBeUndefined();
    expect(test.runtime.fetch({ ...request("/assets/app.js"), url: "https://other.example/assets/app.js" })).toBeUndefined();
    expect(test.runtime.fetch(request("/about/architecture/", { mode: "navigate" }))).toBeUndefined();
    expect(test.runtime.fetch(request(`/releases/${release}/analysis.tif`))).toBeUndefined();
  });

  it("returns validated exact-pair identity and defers valid activation", () => {
    const { runtime } = harness();
    const pair = { contractVersion: 1, appBuildId: "build-a", dataReleaseId: release };
    expect(runtime.message({ protocol: OFFLINE_WORKER_PROTOCOL, type: "inspect-identity", messageToken: "inspect-1", pair })).toMatchObject({ type: "worker-identity", pair, precacheSetSha256: A });
    expect(runtime.message({ protocol: OFFLINE_WORKER_PROTOCOL, type: "activate-update", messageToken: "activate-1", candidatePair: pair, confirmationToken: "confirm-1" })).toMatchObject({ type: "activation-deferred", candidatePair: pair });
  });

  it("ignores mismatched, extra-field, and unknown messages", () => {
    const { runtime } = harness();
    const pair = { contractVersion: 1, appBuildId: "other", dataReleaseId: release };
    expect(runtime.message({ protocol: OFFLINE_WORKER_PROTOCOL, type: "inspect-identity", messageToken: "inspect-1", pair })).toBeUndefined();
    expect(runtime.message({ protocol: OFFLINE_WORKER_PROTOCOL, type: "inspect-identity", messageToken: "inspect-1", pair: { ...pair, appBuildId: "build-a" }, query: "private" })).toBeUndefined();
    expect(runtime.message({ protocol: OFFLINE_WORKER_PROTOCOL, type: "unknown", messageToken: "inspect-1", pair })).toBeUndefined();
  });
});
