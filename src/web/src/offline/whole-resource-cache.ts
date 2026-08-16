import { cacheNamespaces, type AppReleasePairV1 } from "./contracts/keys";
import {
  OfflineContractError,
  assertPersistentEligibility,
  persistenceEligibility,
  validateAppAuthority,
  validateWholeResourceAuthority,
  type AppAuthorityV1,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";

export interface CachePort {
  match(key: string): Promise<Response | undefined>;
  put(key: string, response: Response): Promise<void>;
  delete(key: string): Promise<boolean>;
}

export interface CacheStoragePort {
  open(name: string): Promise<CachePort>;
  delete(name: string): Promise<boolean>;
}

export interface WholeResourceCacheDependencies {
  readonly cacheStorage: CacheStoragePort;
  readonly fetchResource: (url: string, init: RequestInit) => Promise<Response>;
  readonly digest: (algorithm: "SHA-256", bytes: ArrayBuffer) => Promise<ArrayBuffer>;
  readonly applicationOrigin: string;
  readonly nextOperationId: () => string;
}

export type WholeResourceReadResult =
  | Readonly<{ state: "hit"; response: Response; byteLength: number }>
  | Readonly<{ state: "miss" }>
  | Readonly<{ state: "corrupt"; reason: string }>;

export interface WholeResourceInventory {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly verifiedEntries: number;
  readonly verifiedBytes: number;
  readonly missingEntries: number;
  readonly quarantinedEntries: number;
  readonly availableForDeclaredResources: boolean;
}

export class WholeResourceCacheError extends Error {
  readonly code:
    | "AuthorityRejected"
    | "ResponseRejected"
    | "IntegrityFailed"
    | "AdmissionFailed";

  constructor(code: WholeResourceCacheError["code"], message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "WholeResourceCacheError";
    this.code = code;
  }
}

const MEDIA_TYPE = /^[ \t]*([!#$%&'*+\-.^_`|~0-9A-Za-z]+)\/([!#$%&'*+\-.^_`|~0-9A-Za-z]+)(?:[ \t]*;[ \t]*[!#$%&'*+\-.^_`|~0-9A-Za-z]+[ \t]*=[ \t]*(?:[!#$%&'*+\-.^_`|~0-9A-Za-z]+|"(?:[^"\\\r\n]|\\[\t -~])*"))*[ \t]*$/u;

function mediaTypeEssence(value: string): string | null {
  const match = MEDIA_TYPE.exec(value);
  return match ? `${match[1]}/${match[2]}`.toLowerCase() : null;
}

export class WholeResourceCache {
  readonly #authority: AppAuthorityV1;
  readonly #dependencies: WholeResourceCacheDependencies;
  readonly #origin: string;
  readonly #admissions = new Map<string, Promise<Response>>();

  constructor(
    authority: AppAuthorityV1,
    dependencies: WholeResourceCacheDependencies,
    options: Readonly<{ localCandidate?: boolean }> = {},
  ) {
    this.#authority = validateAppAuthority(authority);
    assertPersistentEligibility(
      persistenceEligibility(this.#authority, options.localCandidate === true),
    );
    this.#dependencies = dependencies;
    this.#origin = canonicalOrigin(dependencies.applicationOrigin);
  }

  async fetchAndAdmit(authority: WholeResourceAuthorityV1): Promise<Response> {
    const resource = this.#resource(authority);
    const admissionKey = `${this.#namespace(resource)}\n${resource.canonicalUrl}`;
    const pending = this.#admissions.get(admissionKey);
    if (pending) return pending.then((response) => response.clone());
    const admission = this.#fetchAndAdmit(resource);
    this.#admissions.set(admissionKey, admission);
    try {
      return await admission;
    } finally {
      if (this.#admissions.get(admissionKey) === admission) this.#admissions.delete(admissionKey);
    }
  }

  /**
   * Serializes one pair/key within this adapter instance. The service-worker
   * orchestrator must also serialize admission across adapter instances.
   */
  async #fetchAndAdmit(resource: WholeResourceAuthorityV1): Promise<Response> {
    const existing = await this.read(resource);
    if (existing.state === "hit") return existing.response;
    let response: Response;
    try {
      response = await this.#dependencies.fetchResource(resource.canonicalUrl, {
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
    } catch (error) {
      throw new WholeResourceCacheError("AdmissionFailed", "Complete resource fetch failed.", error);
    }
    await this.#verify(resource, response, true);
    await this.#admitVerified(resource, response);
    const stored = await this.read(resource);
    if (stored.state !== "hit") {
      throw new WholeResourceCacheError("AdmissionFailed", "Promoted resource was not readable.");
    }
    return stored.response;
  }

  async read(authority: WholeResourceAuthorityV1): Promise<WholeResourceReadResult> {
    const resource = this.#resource(authority);
    const cache = await this.#dependencies.cacheStorage.open(this.#namespace(resource));
    const response = await cache.match(resource.canonicalUrl);
    if (!response) return Object.freeze({ state: "miss" });
    try {
      const byteLength = await this.#verify(resource, response, false);
      return Object.freeze({ state: "hit", response, byteLength });
    } catch (error) {
      await cache.delete(resource.canonicalUrl);
      return Object.freeze({
        state: "corrupt",
        reason: error instanceof Error ? error.message : "Cached resource verification failed.",
      });
    }
  }

  async inventory(authorities: readonly WholeResourceAuthorityV1[]): Promise<WholeResourceInventory> {
    let verifiedEntries = 0;
    let verifiedBytes = 0;
    let missingEntries = 0;
    let quarantinedEntries = 0;
    for (const authority of authorities) {
      const result = await this.read(authority);
      if (result.state === "hit") {
        verifiedEntries += 1;
        verifiedBytes += result.byteLength;
      } else if (result.state === "miss") {
        missingEntries += 1;
      } else {
        quarantinedEntries += 1;
      }
    }
    return Object.freeze({
      contractVersion: 1,
      pair: Object.freeze({
        contractVersion: 1,
        appBuildId: this.#authority.appBuildId,
        dataReleaseId: this.#authority.dataReleaseId,
      }),
      verifiedEntries,
      verifiedBytes,
      missingEntries,
      quarantinedEntries,
      availableForDeclaredResources: missingEntries === 0 && quarantinedEntries === 0,
    });
  }

  #resource(authority: WholeResourceAuthorityV1): WholeResourceAuthorityV1 {
    let resource: WholeResourceAuthorityV1;
    try {
      resource = validateWholeResourceAuthority(authority);
    } catch (error) {
      throw new WholeResourceCacheError("AuthorityRejected", "Whole-resource authority is invalid.", error);
    }
    if (
      resource.pair.appBuildId !== this.#authority.appBuildId
      || resource.pair.dataReleaseId !== this.#authority.dataReleaseId
    ) {
      throw new WholeResourceCacheError("AuthorityRejected", "Resource belongs to another app/release pair.");
    }
    if (new URL(resource.canonicalUrl).origin !== this.#origin) {
      throw new WholeResourceCacheError("AuthorityRejected", "Persistent resources must be same-origin.");
    }
    return resource;
  }

  #namespace(authority: WholeResourceAuthorityV1): string {
    const namespaces = cacheNamespaces(authority.pair);
    return authority.authorityKind === "app-asset" ? namespaces.shell : namespaces.release;
  }

  async #admitVerified(authority: WholeResourceAuthorityV1, response: Response): Promise<void> {
    const namespace = this.#namespace(authority);
    const operationId = safeOperationId(this.#dependencies.nextOperationId());
    const temporaryName = `${namespace}:staging:${operationId}`;
    const temporary = await this.#dependencies.cacheStorage.open(temporaryName);
    let target: CachePort | undefined;
    try {
      target = await this.#dependencies.cacheStorage.open(namespace);
      await temporary.put(authority.canonicalUrl, response.clone());
      const staged = await temporary.match(authority.canonicalUrl);
      if (!staged) throw new WholeResourceCacheError("AdmissionFailed", "Temporary cache admission was not readable.");
      await this.#verify(authority, staged, false);
      await target.put(authority.canonicalUrl, staged.clone());
      const promoted = await target.match(authority.canonicalUrl);
      if (!promoted) throw new WholeResourceCacheError("AdmissionFailed", "Promoted cache admission was not readable.");
      await this.#verify(authority, promoted, false);
    } catch (error) {
      await target?.delete(authority.canonicalUrl);
      if (error instanceof WholeResourceCacheError) throw error;
      throw new WholeResourceCacheError("AdmissionFailed", "Complete resource admission failed.", error);
    } finally {
      await this.#dependencies.cacheStorage.delete(temporaryName);
    }
  }

  async #verify(
    authority: WholeResourceAuthorityV1,
    response: Response,
    requireNetworkUrl: boolean,
  ): Promise<number> {
    if (response.status !== 200 || response.redirected || response.type === "opaque" || response.type === "opaqueredirect") {
      throw new WholeResourceCacheError("ResponseRejected", "Only non-redirected, readable status-200 responses may be persisted.");
    }
    if (requireNetworkUrl && response.url !== authority.canonicalUrl) {
      throw new WholeResourceCacheError("ResponseRejected", "Fetched response URL does not match resource authority.");
    }
    const cacheControl = response.headers.get("cache-control")?.toLowerCase() ?? "";
    if (cacheControl.split(",").some((token) => ["private", "no-store"].includes(token.trim().split("=")[0]))) {
      throw new WholeResourceCacheError("ResponseRejected", "Private or no-store responses cannot be persisted.");
    }
    const responseMediaType = mediaTypeEssence(response.headers.get("content-type") ?? "");
    const authorityMediaType = mediaTypeEssence(authority.mediaType);
    if (
      responseMediaType === null
      || authorityMediaType === null
      || responseMediaType !== authorityMediaType
    ) {
      throw new WholeResourceCacheError("ResponseRejected", "Response media type does not match resource authority.");
    }
    const expectedEtag = `"sha256-${authority.sha256}"`;
    const etag = response.headers.get("etag");
    if (etag !== null && etag !== expectedEtag) {
      throw new WholeResourceCacheError("ResponseRejected", "Response ETag does not match resource authority.");
    }
    if (authority.authorityKind === "release-artifact" && authority.etag !== null && etag !== authority.etag) {
      throw new WholeResourceCacheError("ResponseRejected", "Required release artifact ETag is missing or invalid.");
    }
    const bytes = await response.clone().arrayBuffer();
    if (bytes.byteLength !== authority.byteSize) {
      throw new WholeResourceCacheError("IntegrityFailed", "Response byte length does not match resource authority.");
    }
    const digest = hex(await this.#dependencies.digest("SHA-256", bytes));
    if (digest !== authority.sha256) {
      throw new WholeResourceCacheError("IntegrityFailed", "Response SHA-256 does not match resource authority.");
    }
    return bytes.byteLength;
  }
}

function canonicalOrigin(value: string): string {
  const url = new URL(value);
  if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new OfflineContractError("applicationOrigin must be a canonical HTTP(S) origin.");
  }
  return url.origin;
}

function safeOperationId(value: string): string {
  if (!/^[A-Za-z0-9._-]{1,64}$/u.test(value)) {
    throw new WholeResourceCacheError("AdmissionFailed", "Temporary cache operation identity is invalid.");
  }
  return value;
}

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, "0")).join("");
}
