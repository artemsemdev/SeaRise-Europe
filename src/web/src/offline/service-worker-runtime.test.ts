import { createHash, webcrypto } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { OFFLINE_WORKER_PROTOCOL } from "./contracts/policy";
import { createServiceWorkerRuntime, type EmbeddedPrecacheV3 } from "./service-worker-runtime";

const release = "release-a";
const origin = "https://static.example";
const buildIdentity = {
  schemaVersion: "1.0.0",
  appBuildId: "build-a",
  dataReleaseId: release,
  releaseDisposition: "synthetic-fixture",
  manifestPath: `/releases/${release}/manifest.json`,
} as const;
const resourceBodies = Object.freeze({
  "/": "<html>shell</html>",
  "/assets/app.js": "console.log('app');",
  [`/releases/${release}/manifest.json`]: '{"release":"release-a"}',
});
const resourceMediaTypes = Object.freeze({
  "/": "text/html",
  "/assets/app.js": "text/javascript",
  [`/releases/${release}/manifest.json`]: "application/json",
});
const entries = Object.keys(resourceBodies).sort().map((path) => ({
  path,
  mediaType: resourceMediaTypes[path as keyof typeof resourceMediaTypes],
  byteSize: Buffer.byteLength(resourceBodies[path as keyof typeof resourceBodies]),
  sha256: createHash("sha256").update(resourceBodies[path as keyof typeof resourceBodies]).digest("hex"),
}));
const authority = {
  authorityKind: "searise-shell-precache-v3",
  contractVersion: 3,
  buildIdentity,
  entries,
} as const;
const embedded: EmbeddedPrecacheV3 = {
  ...authority,
  precacheSetSha256: createHash("sha256").update(JSON.stringify(authority)).digest("hex"),
};

function responseFor(path: string, body: string = resourceBodies[path as keyof typeof resourceBodies]) {
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": resourceMediaTypes[path as keyof typeof resourceMediaTypes] },
  });
}

function harness(
  fetchOverride?: (request: Request) => Promise<Response>,
  candidate: EmbeddedPrecacheV3 = embedded,
) {
  const stores = new Map<string, Map<string, Response>>();
  const deleted: string[] = [];
  const caches = {
    open: vi.fn(async (name: string) => {
      let entriesForCache = stores.get(name);
      if (!entriesForCache) {
        entriesForCache = new Map();
        stores.set(name, entriesForCache);
      }
      return {
        match: vi.fn(async (url: string) => entriesForCache!.get(url)),
        put: vi.fn(async (url: string, response: Response) => { entriesForCache!.set(url, response); }),
      };
    }),
    delete: vi.fn(async (name: string) => {
      deleted.push(name);
      return stores.delete(name);
    }),
    keys: vi.fn(async () => [...stores.keys()]),
  };
  const fetcher = vi.fn(fetchOverride ?? (async (request: Request) => responseFor(new URL(request.url).pathname)));
  const runtime = createServiceWorkerRuntime(candidate, {
    origin,
    caches,
    fetch: fetcher,
    crypto: webcrypto,
  });
  return {
    runtime,
    caches,
    deleted,
    fetcher,
    stores,
    candidateStore: () => stores.get(runtime.cacheName),
  };
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
      {
        ...embedded,
        buildIdentity: { ...embedded.buildIdentity, releaseDisposition: "private-engineering" },
      } as unknown as EmbeddedPrecacheV3,
      { origin, caches: harness().caches, fetch: vi.fn() },
    )).toThrow(/local Candidate mode/);
  });

  it.each([
    ["identity", {
      ...embedded,
      buildIdentity: { ...embedded.buildIdentity, appBuildId: "other-build" },
    }],
    ["entry", {
      ...embedded,
      entries: embedded.entries.map((entry, index) => index === 1
        ? { ...entry, byteSize: entry.byteSize + 1 }
        : entry),
    }],
  ])("fails closed when the embedded %s differs from its sealed digest", async (_name, tampered) => {
    await expect(harness(undefined, tampered as EmbeddedPrecacheV3).runtime.install()).rejects.toThrow(/tampered/);
  });

  it.each([
    ["missing", entries.slice(0, -1)],
    ["duplicate", [entries[0], entries[0], ...entries.slice(1)]],
  ])("rejects a %s entry inventory", (_name, invalidEntries) => {
    const invalidAuthority = { ...authority, entries: invalidEntries };
    expect(() => harness(undefined, {
      ...invalidAuthority,
      precacheSetSha256: createHash("sha256").update(JSON.stringify(invalidAuthority)).digest("hex"),
    } as EmbeddedPrecacheV3)).toThrow(/inventory is not canonical/);
  });

  it("populates only a new exact-pair cache and reuses a byte-verified completed cache", async () => {
    const test = harness();
    await test.runtime.install();
    expect(test.fetcher).toHaveBeenCalledTimes(3);
    expect([...test.candidateStore()!.keys()]).toEqual(entries.map(({ path }) => `${origin}${path}`));
    await test.runtime.install();
    expect(test.fetcher).toHaveBeenCalledTimes(3);
    expect(test.deleted).toEqual([]);
  });

  it.each(["missing", "mime", "size", "hash"] as const)(
    "deletes and rebuilds an existing candidate cache with an invalid %s entry",
    async (failure) => {
      const test = harness();
      const existing = new Map(entries.map(({ path }) => [`${origin}${path}`, responseFor(path)]));
      const appUrl = `${origin}/assets/app.js`;
      if (failure === "missing") existing.delete(appUrl);
      if (failure === "mime") existing.set(appUrl, new Response(resourceBodies["/assets/app.js"], {
        headers: { "Content-Type": "text/css" },
      }));
      if (failure === "size") existing.set(appUrl, responseFor("/assets/app.js", "x"));
      if (failure === "hash") existing.set(appUrl, responseFor("/assets/app.js", "x".repeat(resourceBodies["/assets/app.js"].length)));
      test.stores.set(test.runtime.cacheName, existing);

      await test.runtime.install();

      expect(test.deleted).toEqual([test.runtime.cacheName]);
      expect(test.fetcher).toHaveBeenCalledTimes(3);
      expect([...test.candidateStore()!.keys()]).toEqual(entries.map(({ path }) => `${origin}${path}`));
    },
  );

  it.each(["mime", "size", "hash"] as const)(
    "rejects a network response with a %s mismatch and deletes only the incomplete candidate cache",
    async (failure) => {
      const test = harness(async (value) => {
        const path = new URL(value.url).pathname;
        if (path !== "/assets/app.js") return responseFor(path);
        if (failure === "mime") return new Response(resourceBodies[path], { headers: { "Content-Type": "text/css" } });
        if (failure === "size") return responseFor(path, "x");
        return responseFor(path, "x".repeat(resourceBodies[path].length));
      });
      test.stores.set("unrelated-active-cache", new Map([["safe", new Response("safe")]]));

      await expect(test.runtime.install()).rejects.toThrow(/invalid|sealed authority/);

      expect(test.deleted).toEqual([test.runtime.cacheName]);
      expect(test.stores.get("unrelated-active-cache")?.has("safe")).toBe(true);
      expect(test.candidateStore()).toBeUndefined();
    },
  );

  it("rolls back its incomplete cache when a response is unreadable or private", async () => {
    const test = harness(async (value) => {
      const path = new URL(value.url).pathname;
      const response = responseFor(path);
      if (path === buildIdentity.manifestPath) response.headers.set("Cache-Control", "private, no-store");
      return response;
    });
    await expect(test.runtime.install()).rejects.toThrow(/Precache response is invalid/);
    expect(test.deleted).toEqual([test.runtime.cacheName]);
  });

  it("serves exact cached resources and canonicalizes only root navigation queries", async () => {
    const test = harness();
    test.stores.set(test.runtime.cacheName, new Map([[`${origin}/`, responseFor("/")]]));
    expect(await (await test.runtime.fetch(request("/?scenario=ssp2-45", { mode: "navigate" }))!)!.text()).toBe(resourceBodies["/"]);
    expect(test.runtime.fetch(request("/assets/app.js?query=private"))).toBeUndefined();
    expect(test.candidateStore()!.has(`${origin}/?scenario=ssp2-45`)).toBe(false);
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
    expect(runtime.message({ protocol: OFFLINE_WORKER_PROTOCOL, type: "inspect-identity", messageToken: "inspect-1", pair })).toMatchObject({ type: "worker-identity", pair, precacheSetSha256: embedded.precacheSetSha256 });
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
