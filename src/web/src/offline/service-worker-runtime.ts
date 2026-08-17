const OFFLINE_WORKER_PROTOCOL = "searise-offline-worker-v1" as const;
const AUTHORITY_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;
const BUILD_DISPOSITIONS = new Set(["synthetic-fixture", "public-promoted"]);

interface AppReleasePairV1 {
  readonly contractVersion: 1;
  readonly appBuildId: string;
  readonly dataReleaseId: string;
}

interface BuildIdentityV1 {
  readonly schemaVersion: "1.0.0";
  readonly appBuildId: string;
  readonly dataReleaseId: string;
  readonly releaseDisposition: "synthetic-fixture" | "public-promoted";
  readonly manifestPath: string;
}

type OfflineWorkerToClientV1 =
  | Readonly<{
      protocol: typeof OFFLINE_WORKER_PROTOCOL;
      type: "worker-identity";
      messageToken: string;
      pair: AppReleasePairV1;
      precacheSetSha256: string;
    }>
  | Readonly<{
      protocol: typeof OFFLINE_WORKER_PROTOCOL;
      type: "activation-deferred";
      messageToken: string;
      candidatePair: AppReleasePairV1;
      reason: "update-coordinator-not-installed";
    }>;

function exactRecord(value: unknown, keys: readonly string[], name: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${name} must be an object.`);
  const record = value as Record<string, unknown>;
  const expected = new Set(keys);
  if (Object.keys(record).length !== expected.size || Object.keys(record).some((key) => !expected.has(key))) {
    throw new TypeError(`${name} contains missing or additional properties.`);
  }
  return record;
}

function validateAppReleasePair(value: unknown): AppReleasePairV1 {
  const record = exactRecord(value, ["contractVersion", "appBuildId", "dataReleaseId"], "app/release pair");
  if (record.contractVersion !== 1 || typeof record.appBuildId !== "string" || !AUTHORITY_ID.test(record.appBuildId) ||
      typeof record.dataReleaseId !== "string" || !AUTHORITY_ID.test(record.dataReleaseId)) {
    throw new TypeError("App/release pair is invalid.");
  }
  return Object.freeze({ contractVersion: 1, appBuildId: record.appBuildId, dataReleaseId: record.dataReleaseId });
}

function validateBuildIdentity(value: unknown): BuildIdentityV1 {
  const record = exactRecord(
    value,
    ["schemaVersion", "appBuildId", "dataReleaseId", "releaseDisposition", "manifestPath"],
    "build identity",
  );
  if (record.releaseDisposition === "private-engineering") {
    throw new TypeError("Private engineering identity is restricted to explicit local Candidate mode.");
  }
  if (record.schemaVersion !== "1.0.0" || typeof record.appBuildId !== "string" || !AUTHORITY_ID.test(record.appBuildId) ||
      typeof record.dataReleaseId !== "string" || !AUTHORITY_ID.test(record.dataReleaseId) ||
      typeof record.releaseDisposition !== "string" || !BUILD_DISPOSITIONS.has(record.releaseDisposition) ||
      record.manifestPath !== `/releases/${record.dataReleaseId}/manifest.json`) {
    throw new TypeError("Build identity is invalid.");
  }
  return Object.freeze({
    schemaVersion: "1.0.0",
    appBuildId: record.appBuildId,
    dataReleaseId: record.dataReleaseId,
    releaseDisposition: record.releaseDisposition as BuildIdentityV1["releaseDisposition"],
    manifestPath: record.manifestPath,
  });
}

function cacheNamespaces(pair: AppReleasePairV1): Readonly<{ shell: string }> {
  const exact = validateAppReleasePair(pair);
  return Object.freeze({ shell: `searise-offline:v1:shell:${exact.appBuildId}::${exact.dataReleaseId}` });
}

function protocolId(value: unknown): string {
  if (typeof value !== "string" || !AUTHORITY_ID.test(value)) throw new TypeError("Protocol identity is invalid.");
  return value;
}

function validateWorkerRequest(value: unknown):
  | Readonly<{ type: "discover-identity"; messageToken: string }>
  | Readonly<{ type: "inspect-identity"; messageToken: string; pair: AppReleasePairV1 }>
  | Readonly<{ type: "activate-update"; messageToken: string; candidatePair: AppReleasePairV1 }>
  | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const source = value as Record<string, unknown>;
  if (source.protocol !== OFFLINE_WORKER_PROTOCOL) return undefined;
  if (source.type === "discover-identity") {
    const record = exactRecord(value, ["protocol", "type", "messageToken"], "identity discovery message");
    return Object.freeze({ type: "discover-identity", messageToken: protocolId(record.messageToken) });
  }
  if (source.type === "inspect-identity") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "pair"], "identity message");
    return Object.freeze({ type: "inspect-identity", messageToken: protocolId(record.messageToken), pair: validateAppReleasePair(record.pair) });
  }
  if (source.type === "activate-update") {
    const record = exactRecord(
      value,
      ["protocol", "type", "messageToken", "candidatePair", "confirmationToken"],
      "activation message",
    );
    protocolId(record.confirmationToken);
    return Object.freeze({
      type: "activate-update",
      messageToken: protocolId(record.messageToken),
      candidatePair: validateAppReleasePair(record.candidatePair),
    });
  }
  return undefined;
}

export interface EmbeddedPrecacheEntryV3 {
  readonly path: string;
  readonly mediaType: string;
  readonly byteSize: number;
  readonly sha256: string;
}

export interface EmbeddedPrecacheV3 {
  readonly authorityKind: "searise-shell-precache-v3";
  readonly contractVersion: 3;
  readonly buildIdentity: BuildIdentityV1;
  readonly entries: readonly EmbeddedPrecacheEntryV3[];
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
  readonly crypto?: Readonly<{ subtle: Pick<SubtleCrypto, "digest"> }>;
}

const SHA256 = /^[0-9a-f]{64}$/u;

function expectedMediaType(path: string): string | undefined {
  if (path === "/") return "text/html";
  const extension = path.slice(path.lastIndexOf("."));
  const mediaTypes: Readonly<Record<string, string>> = Object.freeze({
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  });
  return mediaTypes[extension];
}

function validatePrecache(value: EmbeddedPrecacheV3): Readonly<{
  buildIdentity: BuildIdentityV1;
  pair: AppReleasePairV1;
  entries: readonly Readonly<EmbeddedPrecacheEntryV3>[];
  authorityPayload: Readonly<object>;
  precacheSetSha256: string;
}> {
  const record = exactRecord(value, [
    "authorityKind", "contractVersion", "buildIdentity", "entries", "precacheSetSha256",
  ], "embedded precache authority");
  if (record.authorityKind !== "searise-shell-precache-v3" || record.contractVersion !== 3) {
    throw new TypeError("The embedded precache contract is unsupported.");
  }
  const buildIdentity = validateBuildIdentity(record.buildIdentity);
  const pair = validateAppReleasePair({
    contractVersion: 1,
    appBuildId: buildIdentity.appBuildId,
    dataReleaseId: buildIdentity.dataReleaseId,
  });
  const expectedManifest = buildIdentity.manifestPath;
  const expectedRangeIntegrity =
    `/releases/${buildIdentity.dataReleaseId}/analysis/cog-range-integrity.json`;
  if (typeof record.precacheSetSha256 !== "string" || !SHA256.test(record.precacheSetSha256)) {
    throw new TypeError("The embedded precache authority is invalid.");
  }
  if (!Array.isArray(record.entries)) throw new TypeError("The embedded precache entry inventory is invalid.");
  const entryValues = [...record.entries] as unknown[];
  const entries = entryValues.map((value) => {
    const entry = exactRecord(value, ["path", "mediaType", "byteSize", "sha256"], "precache entry");
    if (typeof entry.path !== "string") throw new TypeError("Precache path must be a string.");
    const mediaType = expectedMediaType(entry.path);
    if (
      !mediaType ||
      entry.mediaType !== mediaType ||
      !Number.isSafeInteger(entry.byteSize) ||
      (entry.byteSize as number) < 0 ||
      typeof entry.sha256 !== "string" ||
      !SHA256.test(entry.sha256)
    ) {
      throw new TypeError(`Precache byte authority is invalid for ${entry.path}.`);
    }
    return Object.freeze({
      path: entry.path,
      mediaType,
      byteSize: entry.byteSize as number,
      sha256: entry.sha256,
    });
  });
  const paths = entries.map((entry) => entry.path);
  if (
    entries.length < 3 ||
    paths[0] !== "/" ||
    paths.some((path, index) => path !== [...paths].sort()[index]) ||
    new Set(paths).size !== paths.length ||
    !paths.includes(expectedManifest) ||
    !paths.includes(expectedRangeIntegrity)
  ) {
    throw new TypeError("The embedded precache entry inventory is not canonical.");
  }
  for (const { path } of entries) {
    const parsed = new URL(path, "https://static.invalid");
    if (
      parsed.origin !== "https://static.invalid" ||
      parsed.search ||
      parsed.hash ||
      parsed.pathname !== path ||
      (path.startsWith("/releases/") &&
        path !== expectedManifest && path !== expectedRangeIntegrity) ||
      (path !== "/" && path !== expectedManifest && path !== expectedRangeIntegrity &&
        !path.startsWith("/assets/"))
    ) {
      throw new TypeError(`Precache URL is outside the shell allowlist: ${path}`);
    }
  }
  const canonicalEntries = Object.freeze(entries);
  return Object.freeze({
    buildIdentity,
    pair,
    entries: canonicalEntries,
    authorityPayload: Object.freeze({
      authorityKind: "searise-shell-precache-v3",
      contractVersion: 3,
      buildIdentity,
      entries: canonicalEntries,
    }),
    precacheSetSha256: record.precacheSetSha256,
  });
}

function exactPair(expected: AppReleasePairV1, value: unknown): boolean {
  try {
    const actual = validateAppReleasePair(value);
    return actual.appBuildId === expected.appBuildId && actual.dataReleaseId === expected.dataReleaseId;
  } catch {
    return false;
  }
}

async function requireVerifiedResponse(
  url: string,
  response: Response | undefined,
  entry: Readonly<EmbeddedPrecacheEntryV3>,
  cryptography: Readonly<{ subtle: Pick<SubtleCrypto, "digest"> }>,
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
    response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !== entry.mediaType
  ) {
    throw new TypeError(`Precache response is invalid for ${new URL(url).pathname}.`);
  }
  let bytes: ArrayBuffer;
  try {
    bytes = await response.clone().arrayBuffer();
  } catch {
    throw new TypeError(`Precache response is unreadable for ${new URL(url).pathname}.`);
  }
  // Copy into this execution realm before Web Crypto. Test/runtime Response
  // implementations may return an ArrayBuffer created by another realm.
  const verifiedBytes = Uint8Array.from(new Uint8Array(bytes));
  const digest = await cryptography.subtle.digest("SHA-256", verifiedBytes);
  const actualSha256 = [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  if (verifiedBytes.byteLength !== entry.byteSize || actualSha256 !== entry.sha256) {
    throw new TypeError(`Precache bytes do not match the sealed authority for ${new URL(url).pathname}.`);
  }
  return response;
}

export function createServiceWorkerRuntime(
  embedded: EmbeddedPrecacheV3,
  dependencies: RuntimeDependencies,
) {
  const precache = validatePrecache(embedded);
  const cryptography = dependencies.crypto ?? globalThis.crypto;
  if (!cryptography?.subtle) throw new TypeError("SHA-256 Web Crypto is required.");
  const absoluteEntries = new Map(
    precache.entries.map((entry) => [entry.path, Object.freeze({
      entry,
      url: new URL(entry.path, dependencies.origin).href,
    })]),
  );
  const cacheName = `${cacheNamespaces(precache.pair).shell}:${precache.precacheSetSha256}`;

  const exactNetworkRequest = (url: string): Request => new Request(url, {
    cache: "reload",
    credentials: "omit",
    redirect: "error",
  });

  const verifyAuthorityDigest = async (): Promise<void> => {
    const digest = await cryptography.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(JSON.stringify(precache.authorityPayload)),
    );
    const actual = [...new Uint8Array(digest)]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
    if (actual !== precache.precacheSetSha256) {
      throw new TypeError("The embedded build identity or precache inventory was tampered.");
    }
  };

  return Object.freeze({
    buildIdentity: precache.buildIdentity,
    cacheName,
    pair: precache.pair,
    async install(): Promise<void> {
      await verifyAuthorityDigest();
      if ((await dependencies.caches.keys()).includes(cacheName)) {
        try {
          const existing = await dependencies.caches.open(cacheName);
          for (const { entry, url } of absoluteEntries.values()) {
            await requireVerifiedResponse(url, await existing.match(url), entry, cryptography);
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
        for (const { entry, url } of absoluteEntries.values()) {
          const response = await requireVerifiedResponse(
            url,
            await dependencies.fetch(exactNetworkRequest(url)),
            entry,
            cryptography,
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
      const candidate = path ? absoluteEntries.get(path) : undefined;
      if (!candidate) return undefined;
      return dependencies.caches.open(cacheName).then(async (cache) => {
        const cached = await cache.match(candidate.url);
        if (cached) {
          try {
            return await requireVerifiedResponse(
              candidate.url,
              cached,
              candidate.entry,
              cryptography,
            );
          } catch (error) {
            await dependencies.caches.delete(cacheName);
            throw error;
          }
        }

        try {
          const response = await requireVerifiedResponse(
            candidate.url,
            await dependencies.fetch(exactNetworkRequest(candidate.url)),
            candidate.entry,
            cryptography,
          );
          await cache.put(candidate.url, response.clone());
          return response;
        } catch (error) {
          await dependencies.caches.delete(cacheName);
          throw error;
        }
      });
    },
    message(value: unknown): OfflineWorkerToClientV1 | undefined {
      let request;
      try {
        request = validateWorkerRequest(value);
      } catch {
        return undefined;
      }
      if (!request) return undefined;
      if (request.type === "discover-identity" ||
          (request.type === "inspect-identity" && exactPair(precache.pair, request.pair))) {
        return Object.freeze({
          protocol: OFFLINE_WORKER_PROTOCOL,
          type: "worker-identity",
          messageToken: request.messageToken,
          pair: precache.pair,
          precacheSetSha256: precache.precacheSetSha256,
        });
      }
      if (request.type === "activate-update" && exactPair(precache.pair, request.candidatePair)) {
        return Object.freeze({
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
