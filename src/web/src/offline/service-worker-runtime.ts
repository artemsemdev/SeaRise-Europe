import {
  cacheNamespaces,
  validateAppReleasePair,
  type AppReleasePairV1,
} from "./contracts/keys";
import {
  OFFLINE_WORKER_PROTOCOL,
  validateClientToOfflineWorkerMessage,
  validateOfflineWorkerToClientMessage,
  type OfflineWorkerToClientV1,
} from "./contracts/policy";

export interface EmbeddedPrecacheV1 {
  readonly contractVersion: 1;
  readonly appBuildId: string;
  readonly dataReleaseId: string;
  readonly releaseDisposition: "synthetic-fixture" | "public-promoted";
  readonly manifestPath: string;
  readonly urls: readonly string[];
  readonly precacheSetSha256: string;
}

interface CacheLike {
  match(request: string): Promise<Response | undefined>;
  put(request: string, response: Response): Promise<void>;
}

interface CacheStorageLike {
  open(name: string): Promise<CacheLike>;
  delete(name: string): Promise<boolean>;
  keys(): Promise<string[]>;
}

interface FetchRequest {
  readonly headers: Headers;
  readonly method: string;
  readonly mode: string;
  readonly url: string;
}

interface RuntimeDependencies {
  readonly origin: string;
  readonly caches: CacheStorageLike;
  readonly fetch: (request: Request) => Promise<Response>;
}

const SHA256 = /^[0-9a-f]{64}$/u;

function validatePrecache(value: EmbeddedPrecacheV1): Readonly<{
  pair: AppReleasePairV1;
  manifestPath: string;
  urls: readonly string[];
  precacheSetSha256: string;
}> {
  if (!new Set(["synthetic-fixture", "public-promoted"]).has(value.releaseDisposition)) {
    throw new TypeError("The release disposition cannot install an offline worker.");
  }
  const pair = validateAppReleasePair({
    contractVersion: value.contractVersion,
    appBuildId: value.appBuildId,
    dataReleaseId: value.dataReleaseId,
  });
  const expectedManifest = `/releases/${pair.dataReleaseId}/manifest.json`;
  if (value.manifestPath !== expectedManifest || !SHA256.test(value.precacheSetSha256)) {
    throw new TypeError("The embedded precache authority is invalid.");
  }
  const urls = [...value.urls];
  if (
    urls.length < 3 ||
    urls[0] !== "/" ||
    urls.some((url, index) => url !== [...urls].sort()[index]) ||
    new Set(urls).size !== urls.length ||
    !urls.includes(expectedManifest)
  ) {
    throw new TypeError("The embedded precache URL inventory is not canonical.");
  }
  for (const path of urls) {
    const parsed = new URL(path, "https://static.invalid");
    if (
      parsed.origin !== "https://static.invalid" ||
      parsed.search ||
      parsed.hash ||
      parsed.pathname !== path ||
      (path.startsWith("/releases/") && path !== expectedManifest) ||
      (path !== "/" && path !== expectedManifest && !path.startsWith("/assets/"))
    ) {
      throw new TypeError(`Precache URL is outside the shell allowlist: ${path}`);
    }
  }
  return Object.freeze({ pair, manifestPath: expectedManifest, urls: Object.freeze(urls), precacheSetSha256: value.precacheSetSha256 });
}

function exactPair(expected: AppReleasePairV1, value: unknown): boolean {
  try {
    const actual = validateAppReleasePair(value);
    return actual.appBuildId === expected.appBuildId && actual.dataReleaseId === expected.dataReleaseId;
  } catch {
    return false;
  }
}

async function requireCacheableResponse(
  url: string,
  response: Response | undefined,
  manifestPath: string,
): Promise<Response> {
  if (!response) throw new TypeError(`Precache response is missing for ${new URL(url).pathname}.`);
  const responsePolicy = new Set(
    (response.headers.get("cache-control") ?? "")
      .split(",")
      .map((directive) => directive.trim().toLowerCase().split("=", 1)[0])
      .filter(Boolean),
  );
  if (
    response.status !== 200 ||
    response.type === "opaque" ||
    response.redirected ||
    responsePolicy.has("private") ||
    responsePolicy.has("no-store") ||
    (new URL(url).pathname === manifestPath &&
      !response.headers.get("content-type")?.toLowerCase().includes("application/json"))
  ) {
    throw new TypeError(`Precache response is invalid for ${new URL(url).pathname}.`);
  }
  try {
    await response.clone().arrayBuffer();
  } catch {
    throw new TypeError(`Precache response is unreadable for ${new URL(url).pathname}.`);
  }
  return response;
}

export function createServiceWorkerRuntime(
  embedded: EmbeddedPrecacheV1,
  dependencies: RuntimeDependencies,
) {
  const precache = validatePrecache(embedded);
  const absoluteUrls = new Map(
    precache.urls.map((path) => [path, new URL(path, dependencies.origin).href]),
  );
  const cacheName = `${cacheNamespaces(precache.pair).shell}:${precache.precacheSetSha256}`;

  return Object.freeze({
    cacheName,
    pair: precache.pair,
    async install(): Promise<void> {
      if ((await dependencies.caches.keys()).includes(cacheName)) {
        try {
          const existing = await dependencies.caches.open(cacheName);
          for (const url of absoluteUrls.values()) {
            await requireCacheableResponse(url, await existing.match(url), precache.manifestPath);
          }
          return;
        } catch {
          if (!await dependencies.caches.delete(cacheName)) {
            throw new TypeError("The incomplete precache could not be removed.");
          }
        }
      }
      try {
        const cache = await dependencies.caches.open(cacheName);
        for (const url of absoluteUrls.values()) {
          const request = new Request(url, {
            cache: "reload",
            credentials: "omit",
            redirect: "error",
          });
          const response = await requireCacheableResponse(
            url,
            await dependencies.fetch(request),
            precache.manifestPath,
          );
          await cache.put(url, response);
        }
      } catch (error) {
        await dependencies.caches.delete(cacheName);
        throw error;
      }
    },
    fetch(request: FetchRequest): Promise<Response> | undefined {
      if (
        request.method !== "GET" ||
        request.headers.has("range") ||
        new URL(request.url).origin !== dependencies.origin
      ) return undefined;

      const parsed = new URL(request.url);
      const path = request.mode === "navigate" && parsed.pathname === "/"
        ? "/"
        : parsed.search || parsed.hash
          ? null
          : parsed.pathname;
      const canonicalUrl = path ? absoluteUrls.get(path) : undefined;
      if (!canonicalUrl) return undefined;
      return dependencies.caches.open(cacheName).then(async (cache) =>
        (await cache.match(canonicalUrl)) ?? dependencies.fetch(request as Request));
    },
    message(value: unknown): OfflineWorkerToClientV1 | undefined {
      let request;
      try {
        request = validateClientToOfflineWorkerMessage(value);
      } catch {
        return undefined;
      }
      if (request.type === "inspect-identity" && exactPair(precache.pair, request.pair)) {
        return validateOfflineWorkerToClientMessage({
          protocol: OFFLINE_WORKER_PROTOCOL,
          type: "worker-identity",
          messageToken: request.messageToken,
          pair: precache.pair,
          precacheSetSha256: precache.precacheSetSha256,
        });
      }
      if (request.type === "activate-update" && exactPair(precache.pair, request.candidatePair)) {
        return validateOfflineWorkerToClientMessage({
          protocol: OFFLINE_WORKER_PROTOCOL,
          type: "activation-deferred",
          messageToken: request.messageToken,
          candidatePair: precache.pair,
          reason: "update-coordinator-not-installed",
        });
      }
      return undefined;
    },
  });
}
