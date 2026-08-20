import { cacheNamespaces, type AppReleasePairV1 } from "./contracts/keys";
import {
  assertAcceptedWholeResource,
  type AcceptedAdmissionGateV1,
} from "./admission-receipt";
import {
  OfflineContractError,
  assertPersistentEligibility,
  persistenceEligibility,
  storageProfile,
  validateAppAuthority,
  validateWholeResourceAuthority,
  type AppAuthorityV1,
  type StorageProfileV1,
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

export interface WholeResourceAdmissionOptionsV1 {
  readonly operationId: string;
  readonly signal: AbortSignal;
}

export interface WholeResourceAdmissionEntryV1 {
  readonly authority: WholeResourceAuthorityV1;
  readonly disposition: "stored" | "already-present";
}

export interface WholeResourceAdmissionV1 {
  readonly contractVersion: 1;
  readonly operationId: string;
  readonly entries: readonly WholeResourceAdmissionEntryV1[];
}

export interface WholeResourceRollbackResultV1 {
  readonly deleted: number;
  readonly retainedAlreadyPresent: number;
  readonly ownershipLost: number;
}

export interface WholeResourceStore {
  readonly mode: "persistent" | "memory-only";
  readonly storageProfile: StorageProfileV1;
  fetchAndAdmit(authority: WholeResourceAuthorityV1, signal?: AbortSignal): Promise<Response>;
  fetchAndAdmitBatch(
    authorities: readonly WholeResourceAuthorityV1[],
    options: WholeResourceAdmissionOptionsV1,
  ): Promise<WholeResourceAdmissionV1>;
  rollbackAdmission(admission: WholeResourceAdmissionV1): Promise<WholeResourceRollbackResultV1>;
  read(authority: WholeResourceAuthorityV1): Promise<WholeResourceReadResult>;
  readAccepted(authority: WholeResourceAuthorityV1, gate: AcceptedAdmissionGateV1): Promise<WholeResourceReadResult>;
  inventory(authorities: readonly WholeResourceAuthorityV1[]): Promise<WholeResourceInventory>;
  close(): void;
}

export class WholeResourceCacheError extends Error {
  readonly code:
    | "AuthorityRejected"
    | "ResponseRejected"
    | "IntegrityFailed"
    | "AdmissionFailed"
    | "Aborted";

  constructor(code: WholeResourceCacheError["code"], message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "WholeResourceCacheError";
    this.code = code;
  }
}

const MEDIA_TYPE = /^[ \t]*([!#$%&'*+\-.^_`|~0-9A-Za-z]+)\/([!#$%&'*+\-.^_`|~0-9A-Za-z]+)(?:[ \t]*;[ \t]*[!#$%&'*+\-.^_`|~0-9A-Za-z]+[ \t]*=[ \t]*(?:[!#$%&'*+\-.^_`|~0-9A-Za-z]+|"(?:[^"\\\r\n]|\\[\t -~])*"))*[ \t]*$/u;
const OWNER_HEADER = "x-searise-admission-operation";
const VERIFIED_ADMISSIONS = new WeakMap<object, ReadonlyMap<string, Readonly<{ namespace: string; url: string }>>>();
const MEMORY_ADMISSIONS = new WeakMap<object, ReadonlyMap<string, number>>();

function aborted(): WholeResourceCacheError {
  return new WholeResourceCacheError("Aborted", "Whole-resource admission was cancelled before receipt publication.");
}

function abortIfNeeded(signal: AbortSignal): void {
  if (signal.aborted) throw aborted();
}

function ownedResponse(response: Response, operationId: string): Response {
  const headers = new Headers(response.headers);
  headers.set(OWNER_HEADER, operationId);
  return new Response(response.clone().body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function arrayBuffer(value: BufferSource): ArrayBuffer {
  if (value instanceof ArrayBuffer) return value;
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer;
}

function mediaTypeEssence(value: string): string | null {
  const match = MEDIA_TYPE.exec(value);
  return match ? `${match[1]}/${match[2]}`.toLowerCase() : null;
}

export class WholeResourceCache implements WholeResourceStore {
  readonly mode = "persistent" as const;
  readonly storageProfile: StorageProfileV1;
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
    this.storageProfile = storageProfile(this.#authority, options.localCandidate === true);
    assertPersistentEligibility(persistenceEligibility(this.#authority, options.localCandidate === true));
    this.#dependencies = dependencies;
    this.#origin = canonicalOrigin(dependencies.applicationOrigin);
  }

  async fetchAndAdmit(authority: WholeResourceAuthorityV1, signal?: AbortSignal): Promise<Response> {
    const resource = this.#resource(authority);
    const admissionKey = `${this.#namespace(resource)}\n${resource.canonicalUrl}`;
    const pending = this.#admissions.get(admissionKey);
    if (pending) return pending.then((response) => response.clone());
    const admission = this.#fetchAndAdmit(resource, signal);
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
  async #fetchAndAdmit(resource: WholeResourceAuthorityV1, signal?: AbortSignal): Promise<Response> {
    const existing = await this.read(resource);
    if (existing.state === "hit") return existing.response;
    const controller = signal ? undefined : new AbortController();
    const admissionSignal = signal ?? controller!.signal;
    await this.fetchAndAdmitBatch([resource], {
      operationId: safeOperationId(this.#dependencies.nextOperationId()),
      signal: admissionSignal,
    });
    const stored = await this.read(resource);
    if (stored.state !== "hit") {
      throw new WholeResourceCacheError("AdmissionFailed", "Promoted resource was not readable.");
    }
    return stored.response;
  }

  async fetchAndAdmitBatch(
    authorities: readonly WholeResourceAuthorityV1[],
    options: WholeResourceAdmissionOptionsV1,
  ): Promise<WholeResourceAdmissionV1> {
    const operation = safeOperationId(options.operationId);
    abortIfNeeded(options.signal);
    const resources = authorities.map((authority) => this.#resource(authority));
    const keys = resources.map((resource) => `${this.#namespace(resource)}\n${resource.canonicalUrl}`);
    if (new Set(keys).size !== keys.length) {
      throw new WholeResourceCacheError("AuthorityRejected", "A whole-resource batch cannot contain duplicate authorities.");
    }
    const stagingNames = new Set(resources.map((resource) => `${this.#namespace(resource)}:staging:${operation}`));
    const entries: WholeResourceAdmissionEntryV1[] = [];
    const staged = new Map<string, Readonly<{ resource: WholeResourceAuthorityV1; response: Response }>>();
    const written = new Map<string, Readonly<{ namespace: string; url: string }>>();
    try {
      for (const resource of resources) {
        abortIfNeeded(options.signal);
        const existing = await this.read(resource);
        abortIfNeeded(options.signal);
        if (existing.state === "hit") {
          entries.push(Object.freeze({ authority: resource, disposition: "already-present" }));
          continue;
        }
        let response: Response;
        try {
          response = await this.#dependencies.fetchResource(resource.canonicalUrl, {
            cache: "no-store",
            credentials: "omit",
            redirect: "error",
            signal: options.signal,
          });
        } catch (error) {
          if (options.signal.aborted) throw aborted();
          throw new WholeResourceCacheError("AdmissionFailed", "Complete resource fetch failed.", error);
        }
        abortIfNeeded(options.signal);
        await this.#verify(resource, response, true);
        abortIfNeeded(options.signal);
        const stagingName = `${this.#namespace(resource)}:staging:${operation}`;
        const staging = await this.#dependencies.cacheStorage.open(stagingName);
        await staging.put(resource.canonicalUrl, ownedResponse(response, operation));
        const stagedResponse = await staging.match(resource.canonicalUrl);
        if (!stagedResponse) {
          throw new WholeResourceCacheError("AdmissionFailed", "Temporary cache batch admission was not readable.");
        }
        await this.#verify(resource, stagedResponse, false);
        abortIfNeeded(options.signal);
        staged.set(keys[entries.length], Object.freeze({ resource, response: stagedResponse }));
        entries.push(Object.freeze({ authority: resource, disposition: "stored" }));
      }

      abortIfNeeded(options.signal);
      for (const entry of entries) {
        if (entry.disposition !== "stored") continue;
        const key = `${this.#namespace(entry.authority)}\n${entry.authority.canonicalUrl}`;
        const stagedEntry = staged.get(key);
        if (!stagedEntry) throw new WholeResourceCacheError("AdmissionFailed", "Staged batch resource identity was lost.");
        const namespace = this.#namespace(entry.authority);
        const target = await this.#dependencies.cacheStorage.open(namespace);
        await target.put(entry.authority.canonicalUrl, stagedEntry.response.clone());
        written.set(key, Object.freeze({ namespace, url: entry.authority.canonicalUrl }));
        const promoted = await target.match(entry.authority.canonicalUrl);
        if (!promoted) throw new WholeResourceCacheError("AdmissionFailed", "Promoted batch resource was not readable.");
        await this.#verify(entry.authority, promoted, false);
        abortIfNeeded(options.signal);
      }
      const admission = Object.freeze({
        contractVersion: 1 as const,
        operationId: operation,
        entries: Object.freeze(entries),
      });
      VERIFIED_ADMISSIONS.set(admission, written);
      return admission;
    } catch (error) {
      await this.#rollbackOwned(operation, written);
      if (error instanceof WholeResourceCacheError) throw error;
      if (options.signal.aborted) throw aborted();
      throw new WholeResourceCacheError("AdmissionFailed", "Whole-resource batch admission failed.", error);
    } finally {
      await Promise.allSettled([...stagingNames].map((name) => this.#dependencies.cacheStorage.delete(name)));
    }
  }

  async rollbackAdmission(admission: WholeResourceAdmissionV1): Promise<WholeResourceRollbackResultV1> {
    const owned = VERIFIED_ADMISSIONS.get(admission);
    if (!owned) throw new WholeResourceCacheError("AuthorityRejected", "Whole-resource admission handle is not verified.");
    const deleted = await this.#rollbackOwned(admission.operationId, owned);
    VERIFIED_ADMISSIONS.delete(admission);
    return Object.freeze({
      deleted,
      retainedAlreadyPresent: admission.entries.filter((entry) => entry.disposition === "already-present").length,
      ownershipLost: owned.size - deleted,
    });
  }

  async #rollbackOwned(
    operation: string,
    owned: ReadonlyMap<string, Readonly<{ namespace: string; url: string }>>,
  ): Promise<number> {
    let deleted = 0;
    for (const { namespace, url } of owned.values()) {
      try {
        const target = await this.#dependencies.cacheStorage.open(namespace);
        const current = await target.match(url);
        if (current?.headers.get(OWNER_HEADER) === operation && await target.delete(url)) deleted += 1;
      } catch {
        // Physical orphan cleanup is conditional and best-effort. Without a
        // published receipt these bytes are never authoritative.
      }
    }
    return deleted;
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

  async readAccepted(
    authority: WholeResourceAuthorityV1,
    gate: AcceptedAdmissionGateV1,
  ): Promise<WholeResourceReadResult> {
    const resource = this.#resource(authority);
    await assertAcceptedWholeResource(gate, resource, {
      digest: (_algorithm: AlgorithmIdentifier, bytes: BufferSource) =>
        this.#dependencies.digest("SHA-256", arrayBuffer(bytes)),
    } as SubtleCrypto, this);
    return this.read(resource);
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

  close(): void { /* Cache Storage owns persistent lifetime. */ }

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

  async #verify(
    authority: WholeResourceAuthorityV1,
    response: Response,
    requireNetworkUrl: boolean,
  ): Promise<number> {
    return verifyWholeResponse(
      authority,
      response,
      requireNetworkUrl,
      this.#dependencies.digest,
      false,
    );
  }
}

async function verifyWholeResponse(
  authority: WholeResourceAuthorityV1,
  response: Response,
  requireNetworkUrl: boolean,
  digestPort: WholeResourceCacheDependencies["digest"],
  allowPrivateResponse: boolean,
): Promise<number> {
  if (response.status !== 200 || response.redirected || response.type === "opaque" || response.type === "opaqueredirect") {
    throw new WholeResourceCacheError("ResponseRejected", "Only non-redirected, readable status-200 responses may be admitted.");
  }
  if (requireNetworkUrl && response.url !== authority.canonicalUrl) {
    throw new WholeResourceCacheError("ResponseRejected", "Fetched response URL does not match resource authority.");
  }
  const cacheControl = response.headers.get("cache-control")?.toLowerCase() ?? "";
  if (!allowPrivateResponse && cacheControl.split(",").some((token) => ["private", "no-store"].includes(token.trim().split("=")[0]))) {
    throw new WholeResourceCacheError("ResponseRejected", "Private or no-store responses cannot be persisted.");
  }
  const responseMediaType = mediaTypeEssence(response.headers.get("content-type") ?? "");
  const authorityMediaType = mediaTypeEssence(authority.mediaType);
  if (responseMediaType === null || authorityMediaType === null || responseMediaType !== authorityMediaType) {
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
  const digest = hex(await digestPort("SHA-256", bytes));
  if (digest !== authority.sha256) {
    throw new WholeResourceCacheError("IntegrityFailed", "Response SHA-256 does not match resource authority.");
  }
  return bytes.byteLength;
}

export type MemoryWholeResourceCacheDependencies = Pick<
  WholeResourceCacheDependencies,
  "fetchResource" | "digest" | "applicationOrigin" | "nextOperationId"
>;

interface MemoryWholeRecord {
  readonly authority: WholeResourceAuthorityV1;
  readonly bytes: ArrayBuffer;
  readonly contentSequence: number;
  readonly operationId: string;
}

export class MemoryWholeResourceCache implements WholeResourceStore {
  readonly mode = "memory-only" as const;
  readonly storageProfile: StorageProfileV1;
  readonly #authority: AppAuthorityV1;
  readonly #dependencies: MemoryWholeResourceCacheDependencies;
  readonly #origin: string;
  readonly #maxBytes: number;
  readonly #maxEntries: number;
  readonly #records = new Map<string, MemoryWholeRecord>();
  #sequence = 0;

  constructor(
    authority: AppAuthorityV1,
    dependencies: MemoryWholeResourceCacheDependencies,
    options: Readonly<{ localCandidate?: boolean; maxBytes: number; maxEntries: number }>,
  ) {
    this.#authority = validateAppAuthority(authority);
    this.storageProfile = storageProfile(this.#authority, options.localCandidate === true);
    const eligibility = persistenceEligibility(this.#authority, options.localCandidate === true);
    if (eligibility.mode !== "memory-only") {
      throw new WholeResourceCacheError("AuthorityRejected", "Memory whole-resource storage is only for private or local Candidate releases.");
    }
    if (!Number.isSafeInteger(options.maxBytes) || options.maxBytes <= 0 ||
        !Number.isSafeInteger(options.maxEntries) || options.maxEntries <= 0) {
      throw new WholeResourceCacheError("AuthorityRejected", "Memory whole-resource budget is invalid.");
    }
    this.#dependencies = dependencies;
    this.#origin = canonicalOrigin(dependencies.applicationOrigin);
    this.#maxBytes = options.maxBytes;
    this.#maxEntries = options.maxEntries;
  }

  #resource(authority: WholeResourceAuthorityV1): WholeResourceAuthorityV1 {
    let resource: WholeResourceAuthorityV1;
    try {
      resource = validateWholeResourceAuthority(authority);
    } catch (error) {
      throw new WholeResourceCacheError("AuthorityRejected", "Whole-resource authority is invalid.", error);
    }
    if (resource.pair.appBuildId !== this.#authority.appBuildId ||
        resource.pair.dataReleaseId !== this.#authority.dataReleaseId ||
        new URL(resource.canonicalUrl).origin !== this.#origin) {
      throw new WholeResourceCacheError("AuthorityRejected", "Memory resource belongs to another app/release or origin.");
    }
    return resource;
  }

  #key(authority: WholeResourceAuthorityV1): string {
    const resourceId = authority.authorityKind === "release-artifact"
      ? authority.artifactId
      : authority.authorityKind === "app-asset"
        ? authority.resourceId
        : "release-manifest";
    return JSON.stringify([
      authority.pair.appBuildId,
      authority.pair.dataReleaseId,
      resourceId,
      authority.canonicalUrl,
      authority.sha256,
    ]);
  }

  #response(record: MemoryWholeRecord): Response {
    return new Response(record.bytes.slice(0), {
      status: 200,
      headers: {
        "cache-control": "private, no-store",
        "content-length": String(record.bytes.byteLength),
        "content-type": record.authority.mediaType,
        etag: `"sha256-${record.authority.sha256}"`,
      },
    });
  }

  async fetchAndAdmit(authority: WholeResourceAuthorityV1, signal?: AbortSignal): Promise<Response> {
    const resource = this.#resource(authority);
    const existing = await this.read(resource);
    if (existing.state === "hit") return existing.response;
    const admissionSignal = signal ?? new AbortController().signal;
    await this.fetchAndAdmitBatch([resource], {
      operationId: safeOperationId(this.#dependencies.nextOperationId()),
      signal: admissionSignal,
    });
    const stored = await this.read(resource);
    if (stored.state !== "hit") throw new WholeResourceCacheError("AdmissionFailed", "Memory admission was not readable.");
    return stored.response;
  }

  async fetchAndAdmitBatch(
    authorities: readonly WholeResourceAuthorityV1[],
    options: WholeResourceAdmissionOptionsV1,
  ): Promise<WholeResourceAdmissionV1> {
    const operation = safeOperationId(options.operationId);
    abortIfNeeded(options.signal);
    const resources = authorities.map((authority) => this.#resource(authority));
    const keys = resources.map((resource) => this.#key(resource));
    if (new Set(keys).size !== keys.length) {
      throw new WholeResourceCacheError("AuthorityRejected", "A memory batch cannot contain duplicate authorities.");
    }
    const entries: WholeResourceAdmissionEntryV1[] = [];
    const additions = new Map<string, Readonly<{ authority: WholeResourceAuthorityV1; bytes: ArrayBuffer }>>();
    for (let index = 0; index < resources.length; index += 1) {
      const resource = resources[index];
      const key = keys[index];
      abortIfNeeded(options.signal);
      const existing = await this.read(resource);
      if (existing.state === "hit") {
        entries.push(Object.freeze({ authority: resource, disposition: "already-present" }));
        continue;
      }
      let response: Response;
      try {
        response = await this.#dependencies.fetchResource(resource.canonicalUrl, {
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          signal: options.signal,
        });
      } catch (error) {
        if (options.signal.aborted) throw aborted();
        throw new WholeResourceCacheError("AdmissionFailed", "Private complete resource fetch failed.", error);
      }
      abortIfNeeded(options.signal);
      await verifyWholeResponse(resource, response, true, this.#dependencies.digest, true);
      const bytes = await response.clone().arrayBuffer();
      abortIfNeeded(options.signal);
      additions.set(key, Object.freeze({ authority: resource, bytes }));
      entries.push(Object.freeze({ authority: resource, disposition: "stored" }));
    }
    const retainedBytes = [...this.#records.values()].reduce((sum, record) => sum + record.bytes.byteLength, 0);
    const incomingBytes = [...additions.values()].reduce((sum, record) => sum + record.bytes.byteLength, 0);
    if (this.#records.size + additions.size > this.#maxEntries || retainedBytes + incomingBytes > this.#maxBytes) {
      throw new WholeResourceCacheError("AdmissionFailed", "Memory whole-resource budget cannot admit this batch.");
    }
    abortIfNeeded(options.signal);
    const ownership = new Map<string, number>();
    for (const [key, addition] of additions) {
      const contentSequence = ++this.#sequence;
      this.#records.set(key, Object.freeze({
        authority: addition.authority,
        bytes: addition.bytes.slice(0),
        contentSequence,
        operationId: operation,
      }));
      ownership.set(key, contentSequence);
    }
    const admission = Object.freeze({
      contractVersion: 1 as const,
      operationId: operation,
      entries: Object.freeze(entries),
    });
    MEMORY_ADMISSIONS.set(admission, ownership);
    return admission;
  }

  async rollbackAdmission(admission: WholeResourceAdmissionV1): Promise<WholeResourceRollbackResultV1> {
    const ownership = MEMORY_ADMISSIONS.get(admission);
    if (!ownership) throw new WholeResourceCacheError("AuthorityRejected", "Memory admission handle is not verified.");
    let deleted = 0;
    for (const [key, contentSequence] of ownership) {
      const current = this.#records.get(key);
      if (current?.operationId === admission.operationId && current.contentSequence === contentSequence) {
        this.#records.delete(key);
        deleted += 1;
      }
    }
    MEMORY_ADMISSIONS.delete(admission);
    return Object.freeze({
      deleted,
      retainedAlreadyPresent: admission.entries.filter((entry) => entry.disposition === "already-present").length,
      ownershipLost: ownership.size - deleted,
    });
  }

  async read(authority: WholeResourceAuthorityV1): Promise<WholeResourceReadResult> {
    const resource = this.#resource(authority);
    const key = this.#key(resource);
    const record = this.#records.get(key);
    if (!record) return Object.freeze({ state: "miss" });
    const response = this.#response(record);
    try {
      const byteLength = await verifyWholeResponse(resource, response, false, this.#dependencies.digest, true);
      return Object.freeze({ state: "hit", response, byteLength });
    } catch (error) {
      if (this.#records.get(key)?.contentSequence === record.contentSequence) this.#records.delete(key);
      return Object.freeze({ state: "corrupt", reason: error instanceof Error ? error.message : "Memory resource verification failed." });
    }
  }

  async readAccepted(authority: WholeResourceAuthorityV1, gate: AcceptedAdmissionGateV1): Promise<WholeResourceReadResult> {
    const resource = this.#resource(authority);
    await assertAcceptedWholeResource(gate, resource, {
      digest: (_algorithm: AlgorithmIdentifier, bytes: BufferSource) =>
        this.#dependencies.digest("SHA-256", arrayBuffer(bytes)),
    } as SubtleCrypto, this);
    return this.read(resource);
  }

  async inventory(authorities: readonly WholeResourceAuthorityV1[]): Promise<WholeResourceInventory> {
    let verifiedEntries = 0;
    let verifiedBytes = 0;
    let missingEntries = 0;
    let quarantinedEntries = 0;
    for (const authority of authorities) {
      const result = await this.read(authority);
      if (result.state === "hit") { verifiedEntries += 1; verifiedBytes += result.byteLength; }
      else if (result.state === "miss") missingEntries += 1;
      else quarantinedEntries += 1;
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

  close(): void { this.#records.clear(); }
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
