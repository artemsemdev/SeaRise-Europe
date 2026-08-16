import { describe, expect, it, vi } from "vitest";
import { cacheNamespaces, validateAppReleasePair } from "./contracts/keys";
import {
  validateAppAuthority,
  validateWholeResourceAuthority,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";
import {
  WholeResourceCache,
  WholeResourceCacheError,
  type CachePort,
  type CacheStoragePort,
  type WholeResourceCacheDependencies,
} from "./whole-resource-cache";

const ORIGIN = "https://static.example";
const BODY = new TextEncoder().encode("hello");
const SHA = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824";

class FakeCache implements CachePort {
  readonly entries = new Map<string, Response>();
  failPut = false;
  corruptPut = false;

  async match(key: string): Promise<Response | undefined> {
    return this.entries.get(key)?.clone();
  }

  async put(key: string, response: Response): Promise<void> {
    if (this.failPut) throw new Error("quota");
    this.entries.set(key, this.corruptPut ? responseFor("wrong") : response.clone());
  }

  async delete(key: string): Promise<boolean> {
    return this.entries.delete(key);
  }
}

class FakeCacheStorage implements CacheStoragePort {
  readonly stores = new Map<string, FakeCache>();
  readonly deletedNames: string[] = [];

  async open(name: string): Promise<FakeCache> {
    let cache = this.stores.get(name);
    if (!cache) {
      cache = new FakeCache();
      this.stores.set(name, cache);
    }
    return cache;
  }

  async delete(name: string): Promise<boolean> {
    this.deletedNames.push(name);
    return this.stores.delete(name);
  }
}

function appAuthority(
  disposition: "synthetic-fixture" | "private-engineering" | "public-promoted" = "synthetic-fixture",
) {
  return validateAppAuthority({
    contractVersion: 1,
    appBuildId: "build-a",
    dataReleaseId: "release-a",
    manifestUrl: `${ORIGIN}/releases/release-a/manifest.json`,
    releaseDisposition: disposition,
    precacheSetSha256: "a".repeat(64),
  });
}

function resource(overrides: Record<string, unknown> = {}) {
  return validateWholeResourceAuthority({
    contractVersion: 1,
    authorityKind: "release-artifact",
    pair: validateAppReleasePair({ contractVersion: 1, appBuildId: "build-a", dataReleaseId: "release-a" }),
    artifactId: "methodology",
    role: "methodology",
    canonicalUrl: `${ORIGIN}/releases/release-a/docs/methodology.json`,
    path: "docs/methodology.json",
    mediaType: "application/json",
    byteSize: BODY.byteLength,
    sha256: SHA,
    etag: `"sha256-${SHA}"`,
    ...overrides,
  });
}

function responseFor(
  body: BodyInit = BODY,
  overrides: Readonly<{
    status?: number;
    url?: string;
    redirected?: boolean;
    contentType?: string;
    cacheControl?: string;
    etag?: string | null;
  }> = {},
): Response {
  const headers = new Headers({
    "content-type": overrides.contentType ?? "application/json",
    "cache-control": overrides.cacheControl ?? "public, max-age=31536000, immutable",
  });
  if (overrides.etag !== null) headers.set("etag", overrides.etag ?? `"sha256-${SHA}"`);
  const response = new Response(body, { status: overrides.status ?? 200, headers });
  Object.defineProperties(response, {
    url: { value: overrides.url ?? resource().canonicalUrl },
    redirected: { value: overrides.redirected ?? false },
  });
  return response;
}

function bytesFromHex(value: string): ArrayBuffer {
  const bytes = new Uint8Array(value.length / 2);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(value.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes.buffer;
}

function harness(options: Readonly<{ response?: Response; localCandidate?: boolean }> = {}) {
  const storage = new FakeCacheStorage();
  const fetchResource = vi.fn(async () => options.response ?? responseFor());
  const digest = vi.fn(async (_algorithm: "SHA-256", bytes: ArrayBuffer) => {
    return bytes.byteLength === BODY.byteLength && new TextDecoder().decode(bytes) === "hello"
      ? bytesFromHex(SHA)
      : bytesFromHex("0".repeat(64));
  });
  const dependencies: WholeResourceCacheDependencies = {
    cacheStorage: storage,
    fetchResource,
    digest,
    applicationOrigin: ORIGIN,
    nextOperationId: () => "operation-1",
  };
  const cache = new WholeResourceCache(appAuthority(), dependencies, {
    localCandidate: options.localCandidate,
  });
  return { cache, storage, fetchResource, digest };
}

describe("whole-resource cache admission", () => {
  it("verifies, stages, promotes, reads back, and removes the temporary cache", async () => {
    const { cache, storage, fetchResource, digest } = harness();
    const admitted = await cache.fetchAndAdmit(resource());
    expect(await admitted.text()).toBe("hello");
    expect(fetchResource).toHaveBeenCalledWith(resource().canonicalUrl, {
      cache: "no-store", credentials: "omit", redirect: "error",
    });
    expect(digest).toHaveBeenCalledTimes(4);
    const names = cacheNamespaces(resource().pair);
    expect(storage.stores.get(names.release)?.entries.has(resource().canonicalUrl)).toBe(true);
    expect(storage.deletedNames).toEqual([`${names.release}:staging:operation-1`]);
  });

  it("reuses an already verified immutable entry without fetching", async () => {
    const { cache, fetchResource } = harness();
    await cache.fetchAndAdmit(resource());
    await cache.fetchAndAdmit(resource());
    expect(fetchResource).toHaveBeenCalledTimes(1);
  });

  it("serializes concurrent admission for the same pair and key", async () => {
    const { cache, fetchResource } = harness();
    const [first, second] = await Promise.all([
      cache.fetchAndAdmit(resource()),
      cache.fetchAndAdmit(resource()),
    ]);
    expect(await first.text()).toBe("hello");
    expect(await second.text()).toBe("hello");
    expect(fetchResource).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["non-200", responseFor(BODY, { status: 206 })],
    ["redirect", responseFor(BODY, { redirected: true })],
    ["wrong URL", responseFor(BODY, { url: `${ORIGIN}/other.json` })],
    ["private", responseFor(BODY, { cacheControl: "private, max-age=60" })],
    ["no-store", responseFor(BODY, { cacheControl: "no-store" })],
    ["media", responseFor(BODY, { contentType: "text/plain" })],
    ["ETag", responseFor(BODY, { etag: `"sha256-${"f".repeat(64)}"` })],
    ["missing ETag", responseFor(BODY, { etag: null })],
    ["size", responseFor("longer")],
    ["digest", responseFor("abcde")],
  ])("refuses %s responses before durable admission", async (_name, response) => {
    const { cache, storage } = harness({ response });
    await expect(cache.fetchAndAdmit(resource())).rejects.toBeInstanceOf(WholeResourceCacheError);
    expect(storage.stores.get(cacheNamespaces(resource().pair).release)?.entries.size ?? 0).toBe(0);
  });

  it.each([
    "Application/JSON; charset=utf-8",
    "application/json; profile=release-v1; charset=\"utf-8\"",
    "application/json; profile=\"release;v1\"",
  ])("accepts the expected MIME essence with valid parameters: %s", async (contentType) => {
    const { cache } = harness({ response: responseFor(BODY, { contentType }) });
    await expect(cache.fetchAndAdmit(resource())).resolves.toBeInstanceOf(Response);
  });

  it("permits a charset parameter when the text/html essence matches", async () => {
    const html = resource({
      canonicalUrl: `${ORIGIN}/releases/release-a/docs/methodology.html`,
      path: "docs/methodology.html",
      mediaType: "text/html",
    });
    const { cache } = harness({ response: responseFor(BODY, {
      contentType: "Text/HTML; charset=utf-8",
      url: html.canonicalUrl,
    }) });
    await expect(cache.fetchAndAdmit(html)).resolves.toBeInstanceOf(Response);
  });

  it.each([
    "",
    "; charset=utf-8",
    "application",
    "application/",
    "application/json;",
    "application/json; charset",
    "application/json; charset=\"unterminated",
  ])("rejects an empty or malformed Content-Type: %j", async (contentType) => {
    const { cache } = harness({ response: responseFor(BODY, { contentType }) });
    await expect(cache.fetchAndAdmit(resource())).rejects.toMatchObject({
      code: "ResponseRejected",
    });
  });

  it("rolls back a corrupt promoted write and always deletes staging", async () => {
    const { cache, storage } = harness();
    const names = cacheNamespaces(resource().pair);
    (await storage.open(names.release)).corruptPut = true;
    await expect(cache.fetchAndAdmit(resource())).rejects.toMatchObject({ code: "IntegrityFailed" });
    expect((await storage.open(names.release)).entries.size).toBe(0);
    expect(storage.deletedNames).toContain(`${names.release}:staging:operation-1`);
  });

  it("rolls back target admission when Cache.put fails", async () => {
    const { cache, storage } = harness();
    const names = cacheNamespaces(resource().pair);
    (await storage.open(names.release)).failPut = true;
    await expect(cache.fetchAndAdmit(resource())).rejects.toMatchObject({ code: "AdmissionFailed" });
    expect((await storage.open(names.release)).entries.size).toBe(0);
  });
});

describe("whole-resource cache authority and readback", () => {
  it("routes complete app assets only to the pair-scoped shell namespace", async () => {
    const appAsset = validateWholeResourceAuthority({
      contractVersion: 1, authorityKind: "app-asset", pair: resource().pair,
      resourceId: "assets/app.js", canonicalUrl: `${ORIGIN}/assets/app.js`, path: "assets/app.js",
      mediaType: "text/javascript", byteSize: BODY.byteLength, sha256: SHA,
    });
    const { cache, storage } = harness({ response: responseFor(BODY, {
      url: appAsset.canonicalUrl, contentType: "text/javascript",
    }) });
    await cache.fetchAndAdmit(appAsset);
    const names = cacheNamespaces(appAsset.pair);
    expect(storage.stores.get(names.shell)?.entries.has(appAsset.canonicalUrl)).toBe(true);
    expect(storage.stores.get(names.release)?.entries.size ?? 0).toBe(0);
  });

  it("refuses COG and PMTiles whole-resource admission", async () => {
    const { cache } = harness();
    for (const role of ["projection-analysis-cog", "projection-visual-pmtiles"]) {
      await expect(cache.read({ ...resource(), role } as unknown as WholeResourceAuthorityV1))
        .rejects.toMatchObject({ code: "AuthorityRejected" });
    }
  });

  it("refuses cross-pair and cross-origin resources", async () => {
    const { cache } = harness();
    await expect(cache.read(resource({
      pair: validateAppReleasePair({ contractVersion: 1, appBuildId: "build-a", dataReleaseId: "release-b" }),
      canonicalUrl: `${ORIGIN}/releases/release-b/docs/methodology.json`,
    }))).rejects.toMatchObject({ code: "AuthorityRejected" });
    await expect(cache.read(resource({ canonicalUrl: "https://other.example/releases/release-a/docs/methodology.json" }))).rejects.toMatchObject({ code: "AuthorityRejected" });
  });

  it("refuses private engineering and explicit local-candidate persistent adapters", () => {
    const dependencies = harness().cache;
    void dependencies;
    const ports = harness();
    const injected = {
      cacheStorage: ports.storage,
      fetchResource: ports.fetchResource,
      digest: ports.digest,
      applicationOrigin: ORIGIN,
      nextOperationId: () => "one",
    };
    expect(() => new WholeResourceCache(appAuthority("private-engineering"), injected)).toThrow(/session memory only/);
    expect(() => new WholeResourceCache(appAuthority(), injected, { localCandidate: true })).toThrow(/session memory only/);
  });

  it("returns an exact miss without opening another release namespace", async () => {
    const { cache, storage } = harness();
    await expect(cache.read(resource())).resolves.toEqual({ state: "miss" });
    expect([...storage.stores.keys()]).toEqual([cacheNamespaces(resource().pair).release]);
  });

  it("quarantines corrupt cached bytes by deleting the exact key", async () => {
    const { cache, storage } = harness();
    const target = await storage.open(cacheNamespaces(resource().pair).release);
    await target.put(resource().canonicalUrl, responseFor("wrong"));
    await expect(cache.read(resource())).resolves.toMatchObject({ state: "corrupt" });
    expect(target.entries.has(resource().canonicalUrl)).toBe(false);
  });

  it("returns only aggregate privacy-safe inventory evidence", async () => {
    const { cache } = harness();
    await cache.fetchAndAdmit(resource());
    const evidence = await cache.inventory([resource(), validateWholeResourceAuthority({
      ...resource(), artifactId: "attribution", role: "source-attribution",
      canonicalUrl: `${ORIGIN}/releases/release-a/docs/attribution.json`, path: "docs/attribution.json",
    })]);
    expect(evidence).toMatchObject({ verifiedEntries: 1, verifiedBytes: 5, missingEntries: 1, quarantinedEntries: 0, availableForDeclaredResources: false });
    expect(JSON.stringify(evidence)).not.toMatch(/canonicalUrl|artifactId|path|query|latitude|longitude/);
  });
});
