import {
  assertPersistentEligibility,
  persistenceEligibility,
  validateAppAuthority,
  validateByteInterval,
  validateRangeIdentity,
  type AppAuthorityV1,
  type PersistenceEligibilityV1,
  type RangeIdentityV1,
} from "./contracts/v1";
import {
  validateClientLease,
  validateStorageBudget,
  type ClientLeaseV1,
  type StorageBudgetV1,
} from "./contracts/policy";
import { cacheNamespaces, validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";

export type RangeWriteResult = "stored" | "already-present";
export interface VerifiedRangeWrite {
  readonly identity: RangeIdentityV1;
  readonly bytes: ArrayBuffer;
}
export interface RangeAuthorityCatalogV1 {
  readonly contractVersion: 1;
  readonly identities: readonly RangeIdentityV1[];
}
export function createRangeAuthorityCatalog(identities: readonly RangeIdentityV1[]): RangeAuthorityCatalogV1 {
  const validated = identities.map((identity) => validateRangeIdentity(identity));
  const keys = new Set<string>();
  for (const identity of validated) {
    const key = authorityCatalogKey(identity);
    if (keys.has(key)) throw new RangeStoreIntegrityError("Range authority catalog contains a duplicate identity.");
    keys.add(key);
  }
  return Object.freeze({ contractVersion: 1, identities: Object.freeze(validated) });
}
export interface RangeInventoryV1 {
  readonly mode: "memory-only" | "persistent";
  readonly payloadBytes: number;
  readonly entryCount: number;
  readonly activePair: AppReleasePairV1 | null;
  readonly previousPair: AppReleasePairV1 | null;
  readonly entries: readonly Readonly<{
    pair: AppReleasePairV1; artifactId: string; path: string;
    start: number; endExclusive: number; byteLength: number; lastAccessSequence: number;
  }>[];
}
export interface RangeStore {
  readonly mode: "memory-only" | "persistent";
  readExactOrContaining(identity: RangeIdentityV1, requested?: Readonly<{ start: number; endExclusive: number }>): Promise<ArrayBuffer | null>;
  putVerified(identity: RangeIdentityV1, bytes: ArrayBuffer): Promise<RangeWriteResult>;
  putVerifiedBatch(writes: readonly VerifiedRangeWrite[]): Promise<readonly RangeWriteResult[]>;
  acquireLease(lease: ClientLeaseV1): Promise<void>;
  releaseLease(lease: ClientLeaseV1): Promise<void>;
  setProtectedPairs(active: AppReleasePairV1 | null, previous: AppReleasePairV1 | null): Promise<void>;
  inventory(): Promise<RangeInventoryV1>;
  close(): void;
}

export class RangeStoreIntegrityError extends Error {
  constructor(message: string) { super(message); this.name = "RangeStoreIntegrityError"; }
}
export class RangeStoreQuotaError extends Error {
  constructor() { super("The bounded range store cannot admit this verified interval."); this.name = "RangeStoreQuotaError"; }
}
export class RangeStoreUnsupportedError extends Error {
  constructor(message: string) { super(message); this.name = "RangeStoreUnsupportedError"; }
}

interface StoredRange {
  key: string; pairKey: string; artifactKey: string; pair: AppReleasePairV1;
  artifactId: string; path: string; role: RangeIdentityV1["authority"]["role"];
  mediaType: string; totalByteSize: number; artifactSha256: string; integrityChunkSize: number;
  start: number; endExclusive: number;
  authorizedIntervalSha256: string; bytes: ArrayBuffer; byteLength: number;
  contentSequence: number; lastAccessSequence: number;
}

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}
function pairFromAuthority(authority: AppAuthorityV1): AppReleasePairV1 {
  return validateAppReleasePair({
    contractVersion: authority.contractVersion,
    appBuildId: authority.appBuildId,
    dataReleaseId: authority.dataReleaseId,
  });
}
function pairKey(pair: AppReleasePairV1): string { return cacheNamespaces(pair).pairKey; }
function artifactKey(identity: RangeIdentityV1): string {
  const authority = identity.authority;
  return JSON.stringify([pairKey(authority.pair), authority.artifactId, authority.path,
    authority.role, authority.mediaType, authority.totalByteSize, authority.artifactSha256,
    authority.integrityChunkSize]);
}
function rangeKey(identity: RangeIdentityV1): string {
  return JSON.stringify([artifactKey(identity), identity.interval.start, identity.interval.endExclusive,
    identity.authorizedIntervalSha256]);
}
function authorityCatalogKey(identity: RangeIdentityV1): string {
  const authority = identity.authority;
  return JSON.stringify([
    identity.contractVersion, authority.contractVersion, authority.pair.contractVersion,
    authority.pair.appBuildId, authority.pair.dataReleaseId, authority.artifactId,
    authority.role, authority.canonicalUrl, authority.path, authority.mediaType,
    authority.totalByteSize, authority.artifactSha256, authority.etag,
    authority.integrityChunkSize, identity.interval.start, identity.interval.endExclusive,
    identity.authorizedIntervalSha256,
  ]);
}
function checkedIdentity(identity: RangeIdentityV1, expectedPair: AppReleasePairV1): RangeIdentityV1 {
  const validated = validateRangeIdentity(identity);
  if (!samePair(validated.authority.pair, expectedPair)) {
    throw new RangeStoreIntegrityError("Range authority belongs to another app/release pair.");
  }
  return validated;
}
function checkedCogIdentity(identity: RangeIdentityV1, expectedPair: AppReleasePairV1): RangeIdentityV1 {
  const rawInput: unknown = identity;
  const rawAuthority = typeof rawInput === "object" && rawInput !== null && "authority" in rawInput
    ? rawInput.authority
    : null;
  if (typeof rawAuthority === "object" && rawAuthority !== null && "role" in rawAuthority
    && rawAuthority.role === "projection-visual-pmtiles") {
    throw new RangeStoreUnsupportedError("PMTiles is visual, network-only context and cannot enter a range store.");
  }
  const validated = checkedIdentity(identity, expectedPair);
  return validated;
}
function catalogKeys(
  input: RangeAuthorityCatalogV1,
  expectedPair: AppReleasePairV1,
): ReadonlySet<string> {
  if (!input || input.contractVersion !== 1 || !Array.isArray(input.identities)) {
    throw new RangeStoreIntegrityError("Range authority catalog is invalid.");
  }
  const keys = new Set<string>();
  for (const item of input.identities) {
    const identity = checkedCogIdentity(item, expectedPair);
    const key = authorityCatalogKey(identity);
    if (keys.has(key)) throw new RangeStoreIntegrityError("Range authority catalog contains a duplicate identity.");
    keys.add(key);
  }
  return keys;
}
function checkedCatalogIdentity(
  identity: RangeIdentityV1,
  expectedPair: AppReleasePairV1,
  approved: ReadonlySet<string>,
): RangeIdentityV1 {
  const validated = checkedCogIdentity(identity, expectedPair);
  if (!approved.has(authorityCatalogKey(validated))) {
    throw new RangeStoreIntegrityError("Range identity is absent from the trusted authority catalog.");
  }
  return validated;
}
function requestedInterval(identity: RangeIdentityV1, requested?: Readonly<{ start: number; endExclusive: number }>) {
  const interval = validateByteInterval(requested ?? identity.interval, identity.authority.totalByteSize);
  if (interval.start < identity.interval.start || interval.endExclusive > identity.interval.endExclusive) {
    throw new RangeStoreIntegrityError("A cache hit requires one complete containing authorized interval.");
  }
  return interval;
}
async function digest(bytes: ArrayBuffer, subtle: SubtleCrypto): Promise<string> {
  return [...new Uint8Array(await subtle.digest("SHA-256", bytes))]
    .map((value) => value.toString(16).padStart(2, "0")).join("");
}
interface VerifiedAdmission {
  readonly identity: RangeIdentityV1;
  readonly bytes: ArrayBuffer;
  readonly key: string;
}
async function verifyAdmissions(
  writes: readonly VerifiedRangeWrite[],
  expectedPair: AppReleasePairV1,
  approved: ReadonlySet<string>,
  subtle: SubtleCrypto,
): Promise<readonly VerifiedAdmission[]> {
  return Promise.all(writes.map(async ({ identity: input, bytes }) => {
    const identity = checkedCatalogIdentity(input, expectedPair, approved);
    if (bytes.byteLength !== identity.interval.endExclusive - identity.interval.start
      || await digest(bytes, subtle) !== identity.authorizedIntervalSha256) {
      throw new RangeStoreIntegrityError("Only exact release-authorized COG chunk bytes may enter a range store.");
    }
    return Object.freeze({ identity, bytes, key: rangeKey(identity) });
  }));
}
function recordFor(identity: RangeIdentityV1, bytes: ArrayBuffer, sequence: number): StoredRange {
  const authority = identity.authority;
  return {
    key: rangeKey(identity), pairKey: pairKey(authority.pair), artifactKey: artifactKey(identity),
    pair: authority.pair, artifactId: authority.artifactId, path: authority.path, role: authority.role,
    mediaType: authority.mediaType, totalByteSize: authority.totalByteSize,
    artifactSha256: authority.artifactSha256, integrityChunkSize: authority.integrityChunkSize,
    start: identity.interval.start, endExclusive: identity.interval.endExclusive,
    authorizedIntervalSha256: identity.authorizedIntervalSha256, bytes: bytes.slice(0),
    byteLength: bytes.byteLength, contentSequence: sequence, lastAccessSequence: sequence,
  };
}
function matches(record: StoredRange, identity: RangeIdentityV1): boolean {
  return record.key === rangeKey(identity) && record.pairKey === pairKey(identity.authority.pair)
    && record.artifactKey === artifactKey(identity) && record.artifactId === identity.authority.artifactId
    && record.path === identity.authority.path && record.role === identity.authority.role
    && record.mediaType === identity.authority.mediaType
    && record.totalByteSize === identity.authority.totalByteSize
    && record.artifactSha256 === identity.authority.artifactSha256
    && record.integrityChunkSize === identity.authority.integrityChunkSize
    && record.start === identity.interval.start && record.endExclusive === identity.interval.endExclusive
    && record.authorizedIntervalSha256 === identity.authorizedIntervalSha256
    && record.byteLength === record.endExclusive - record.start
    && record.bytes instanceof ArrayBuffer && record.bytes.byteLength === record.byteLength;
}

export class MemoryRangeStore implements RangeStore {
  readonly mode = "memory-only" as const;
  readonly #pair: AppReleasePairV1; readonly #budget: StorageBudgetV1; readonly #subtle: SubtleCrypto;
  readonly #now: () => number; readonly #approved: ReadonlySet<string>;
  readonly #entries = new Map<string, StoredRange>(); readonly #leases = new Map<string, ClientLeaseV1>();
  #sequence = 0; #active: AppReleasePairV1 | null = null; #previous: AppReleasePairV1 | null = null;
  constructor(pair: AppReleasePairV1, budget: StorageBudgetV1, subtle: SubtleCrypto, approved: ReadonlySet<string>, now: () => number = Date.now) {
    this.#pair = validateAppReleasePair(pair); this.#budget = validateStorageBudget(budget); this.#subtle = subtle;
    this.#approved = approved; this.#now = now;
  }
  async readExactOrContaining(input: RangeIdentityV1, requested?: Readonly<{ start: number; endExclusive: number }>): Promise<ArrayBuffer | null> {
    const identity = checkedCatalogIdentity(input, this.#pair, this.#approved); const interval = requestedInterval(identity, requested);
    const record = this.#entries.get(rangeKey(identity)); if (!record) return null;
    if (!matches(record, identity) || await digest(record.bytes, this.#subtle) !== record.authorizedIntervalSha256) {
      this.#entries.delete(record.key); throw new RangeStoreIntegrityError("Stored range bytes failed their authorized SHA-256 identity.");
    }
    record.lastAccessSequence = ++this.#sequence;
    return record.bytes.slice(interval.start - record.start, interval.endExclusive - record.start);
  }
  async putVerified(input: RangeIdentityV1, bytes: ArrayBuffer): Promise<RangeWriteResult> {
    return (await this.putVerifiedBatch([{ identity: input, bytes }]))[0]!;
  }
  async putVerifiedBatch(writes: readonly VerifiedRangeWrite[]): Promise<readonly RangeWriteResult[]> {
    const admissions = await verifyAdmissions(writes, this.#pair, this.#approved, this.#subtle);
    if (admissions.length === 0) return Object.freeze([]);

    const unique = new Map<string, VerifiedAdmission>();
    const initiallyPresent = new Set(this.#entries.keys());
    const results = admissions.map((admission) => {
      const present = initiallyPresent.has(admission.key) || unique.has(admission.key);
      if (!unique.has(admission.key)) unique.set(admission.key, admission);
      return present ? "already-present" as const : "stored" as const;
    });
    const incomingKeys = new Set(unique.keys());
    const protectedKeys = new Set([this.#active, this.#previous].filter(Boolean).map((pair) => pairKey(pair!)));
    const expiredLeases: string[] = [];
    for (const lease of this.#leases.values()) {
      if (lease.expiresAtEpochMs <= this.#now()) expiredLeases.push(lease.leaseId);
      else protectedKeys.add(pairKey(lease.pair));
    }
    const ordered = [...this.#entries.values()].sort((a, b) => a.lastAccessSequence - b.lastAccessSequence || a.key.localeCompare(b.key));
    let total = ordered.reduce((sum, record) => sum + record.byteLength, 0);
    const additions = [...unique.values()].filter((admission) => !initiallyPresent.has(admission.key));
    const additionBytes = additions.reduce((sum, admission) => sum + admission.bytes.byteLength, 0);
    let projectedEntries = this.#entries.size + additions.length;
    const evictions: StoredRange[] = [];
    while ((total + additionBytes > this.#budget.maxRangeBytes || projectedEntries > this.#budget.maxRangeEntries) && ordered.length) {
      const candidate = ordered.shift()!;
      if (protectedKeys.has(candidate.pairKey) || incomingKeys.has(candidate.key)) continue;
      evictions.push(candidate); total -= candidate.byteLength; projectedEntries -= 1;
    }
    if (total + additionBytes > this.#budget.maxRangeBytes || projectedEntries > this.#budget.maxRangeEntries) {
      throw new RangeStoreQuotaError();
    }

    let nextSequence = this.#sequence;
    const records = [...unique.values()].map((admission) =>
      recordFor(admission.identity, admission.bytes, ++nextSequence));
    for (const candidate of evictions) this.#entries.delete(candidate.key);
    for (const leaseId of expiredLeases) this.#leases.delete(leaseId);
    for (const record of records) this.#entries.set(record.key, record);
    this.#sequence = nextSequence;
    return Object.freeze(results);
  }
  async acquireLease(input: ClientLeaseV1): Promise<void> { const lease = validateClientLease(input); this.#leases.set(lease.leaseId, lease); }
  async releaseLease(input: ClientLeaseV1): Promise<void> { this.#leases.delete(validateClientLease(input).leaseId); }
  async setProtectedPairs(active: AppReleasePairV1 | null, previous: AppReleasePairV1 | null): Promise<void> {
    this.#active = active ? validateAppReleasePair(active) : null; this.#previous = previous ? validateAppReleasePair(previous) : null;
    if (this.#active && this.#previous && samePair(this.#active, this.#previous)) throw new RangeStoreIntegrityError("Active and previous pairs must differ.");
  }
  async inventory(): Promise<RangeInventoryV1> {
    const entries = [...this.#entries.values()];
    return { mode: this.mode, payloadBytes: entries.reduce((sum, record) => sum + record.byteLength, 0),
      entryCount: entries.length, activePair: this.#active, previousPair: this.#previous,
      entries: entries.map(({ pair, artifactId, path, start, endExclusive, byteLength, lastAccessSequence }) =>
        ({ pair, artifactId, path, start, endExclusive, byteLength, lastAccessSequence })) };
  }
  close(): void { this.#entries.clear(); this.#leases.clear(); }
}

export interface RangeStoreBrowserApis { readonly indexedDB?: IDBFactory; readonly subtle: SubtleCrypto; readonly now?: () => number }
export interface RangeStoreOptionsV1 { readonly localCandidate?: boolean; readonly catalog: RangeAuthorityCatalogV1 }
export function createRangeStore(authorityInput: AppAuthorityV1, budget: StorageBudgetV1, apis: RangeStoreBrowserApis, options: RangeStoreOptionsV1): RangeStore {
  const authority = validateAppAuthority(authorityInput);
  const eligibility = persistenceEligibility(authority, options.localCandidate === true);
  const pair = pairFromAuthority(authority);
  const approved = catalogKeys(options.catalog, pair);
  if (eligibility.mode === "memory-only") return new MemoryRangeStore(pair, budget, apis.subtle, approved, apis.now);
  if (!apis.indexedDB) throw new RangeStoreUnsupportedError("IndexedDB is unavailable for persistent range storage.");
  return new IndexedDbRangeStore(eligibility, budget, approved, apis);
}

interface MetaRecord { key: "state"; rangeBytes: number; rangeEntries: number; nextSequence: number; activePair: AppReleasePairV1 | null; previousPair: AppReleasePairV1 | null }
interface LeaseRecord { leaseId: string; pairKey: string; pair: AppReleasePairV1; expiresAtEpochMs: number }
const STORES = { meta: "range-meta", ranges: "ranges", leases: "leases" } as const;
const initialMeta = (): MetaRecord => ({ key: "state", rangeBytes: 0, rangeEntries: 0, nextSequence: 0, activePair: null, previousPair: null });
function request<T>(value: IDBRequest<T>): Promise<T> { return new Promise((resolve, reject) => { value.onsuccess = () => resolve(value.result); value.onerror = () => reject(value.error); }); }
function completed(transaction: IDBTransaction): Promise<void> { return new Promise((resolve, reject) => { transaction.oncomplete = () => resolve(); transaction.onabort = transaction.onerror = () => reject(transaction.error ?? new DOMException("IndexedDB transaction aborted.", "AbortError")); }); }

class IndexedDbRangeStore implements RangeStore {
  readonly mode = "persistent" as const;
  readonly #pair: AppReleasePairV1; readonly #budget: StorageBudgetV1; readonly #idb: IDBFactory;
  readonly #subtle: SubtleCrypto; readonly #approved: ReadonlySet<string>; readonly #now: () => number; #database: Promise<IDBDatabase> | null = null;
  constructor(eligibility: PersistenceEligibilityV1, budget: StorageBudgetV1, approved: ReadonlySet<string>, apis: RangeStoreBrowserApis) {
    this.#pair = assertPersistentEligibility(eligibility); this.#budget = validateStorageBudget(budget);
    if (!apis.indexedDB) throw new RangeStoreUnsupportedError("IndexedDB is unavailable.");
    this.#idb = apis.indexedDB; this.#subtle = apis.subtle; this.#approved = approved; this.#now = apis.now ?? Date.now;
  }
  #open(): Promise<IDBDatabase> {
    if (!this.#database) this.#database = new Promise((resolve, reject) => {
      const open = this.#idb.open(cacheNamespaces(this.#pair).rangeDatabase, 1);
      open.onupgradeneeded = () => {
        const database = open.result;
        database.createObjectStore(STORES.meta, { keyPath: "key" });
        const ranges = database.createObjectStore(STORES.ranges, { keyPath: "key" });
        ranges.createIndex("by-pair", "pairKey"); ranges.createIndex("by-lru", ["lastAccessSequence", "key"], { unique: true });
        const leases = database.createObjectStore(STORES.leases, { keyPath: "leaseId" });
        leases.createIndex("by-pair", "pairKey"); leases.createIndex("by-expiry", ["expiresAtEpochMs", "leaseId"], { unique: true });
      };
      open.onsuccess = () => { open.result.onversionchange = () => open.result.close(); resolve(open.result); };
      open.onerror = () => reject(open.error ?? new RangeStoreUnsupportedError("IndexedDB open failed."));
      open.onblocked = () => reject(new RangeStoreUnsupportedError("IndexedDB open was blocked."));
    });
    return this.#database;
  }
  async #meta(store: IDBObjectStore): Promise<MetaRecord> { return (await request(store.get("state")) as MetaRecord | undefined) ?? initialMeta(); }
  async readExactOrContaining(input: RangeIdentityV1, requested?: Readonly<{ start: number; endExclusive: number }>): Promise<ArrayBuffer | null> {
    const identity = checkedCatalogIdentity(input, this.#pair, this.#approved);
    const interval = requestedInterval(identity, requested); const database = await this.#open();
    const key = rangeKey(identity); const transaction = database.transaction(STORES.ranges, "readonly"); const done = completed(transaction);
    const record = await request(transaction.objectStore(STORES.ranges).get(key)) as StoredRange | undefined; await done;
    if (!record) return null;
    if (!matches(record, identity) || await digest(record.bytes, this.#subtle) !== identity.authorizedIntervalSha256) {
      await this.#quarantine(key, record.contentSequence); throw new RangeStoreIntegrityError("Stored range bytes failed their release-authorized SHA-256 identity.");
    }
    const touch = database.transaction([STORES.meta, STORES.ranges], "readwrite"); const touched = completed(touch);
    const current = await request(touch.objectStore(STORES.ranges).get(record.key)) as StoredRange | undefined;
    if (current?.contentSequence === record.contentSequence) { const meta = await this.#meta(touch.objectStore(STORES.meta)); current.lastAccessSequence = ++meta.nextSequence; touch.objectStore(STORES.ranges).put(current); touch.objectStore(STORES.meta).put(meta); }
    await touched;
    return record.bytes.slice(interval.start - record.start, interval.endExclusive - record.start);
  }
  async #quarantine(key: string, contentSequence: unknown): Promise<void> {
    const database = await this.#open(); const tx = database.transaction([STORES.meta, STORES.ranges], "readwrite"); const done = completed(tx);
    const ranges = tx.objectStore(STORES.ranges); const current = await request(ranges.get(key)) as StoredRange | undefined;
    if (current && current.contentSequence === contentSequence) {
      const meta = await this.#meta(tx.objectStore(STORES.meta)); const storedLength = Number.isSafeInteger(current.byteLength)
        && current.byteLength >= 0 ? current.byteLength : current.bytes instanceof ArrayBuffer ? current.bytes.byteLength : 0;
      ranges.delete(key); meta.rangeBytes = Math.max(0, meta.rangeBytes - storedLength);
      meta.rangeEntries = Math.max(0, meta.rangeEntries - 1); tx.objectStore(STORES.meta).put(meta);
    }
    await done;
  }
  async putVerified(input: RangeIdentityV1, bytes: ArrayBuffer): Promise<RangeWriteResult> {
    return (await this.putVerifiedBatch([{ identity: input, bytes }]))[0]!;
  }
  async putVerifiedBatch(writes: readonly VerifiedRangeWrite[]): Promise<readonly RangeWriteResult[]> {
    const admissions = await verifyAdmissions(writes, this.#pair, this.#approved, this.#subtle);
    if (admissions.length === 0) return Object.freeze([]);
    const database = await this.#open(); const tx = database.transaction([STORES.meta, STORES.ranges, STORES.leases], "readwrite"); const done = completed(tx); let quota = false;
    try {
      const metaStore = tx.objectStore(STORES.meta); const rangeStore = tx.objectStore(STORES.ranges); const leaseStore = tx.objectStore(STORES.leases);
      const meta = await this.#meta(metaStore);
      const unique = new Map<string, VerifiedAdmission>();
      const existingKeys = new Set<string>();
      const results: RangeWriteResult[] = [];
      for (const admission of admissions) {
        if (unique.has(admission.key)) {
          results.push("already-present");
          continue;
        }
        unique.set(admission.key, admission);
        const existing = await request(rangeStore.get(admission.key)) as StoredRange | undefined;
        if (existing) existingKeys.add(admission.key);
        results.push(existing ? "already-present" : "stored");
      }
      const leases = await request(leaseStore.getAll()) as LeaseRecord[]; const protectedPairs = new Set([meta.activePair, meta.previousPair].filter(Boolean).map((pair) => pairKey(pair!)));
      const expiredLeases: string[] = [];
      for (const lease of leases) { if (lease.expiresAtEpochMs <= this.#now()) expiredLeases.push(lease.leaseId); else protectedPairs.add(lease.pairKey); }
      const candidates = await request(rangeStore.index("by-lru").getAll()) as StoredRange[];
      const additions = [...unique.values()].filter((admission) => !existingKeys.has(admission.key));
      let projectedBytes = meta.rangeBytes + additions.reduce((sum, admission) => sum + admission.bytes.byteLength, 0);
      let projectedEntries = meta.rangeEntries + additions.length;
      const evictions: StoredRange[] = [];
      for (const candidate of candidates) {
        if (projectedBytes <= this.#budget.maxRangeBytes && projectedEntries <= this.#budget.maxRangeEntries) break;
        if (protectedPairs.has(candidate.pairKey) || unique.has(candidate.key)) continue;
        evictions.push(candidate); projectedBytes -= candidate.byteLength; projectedEntries -= 1;
      }
      if (projectedBytes > this.#budget.maxRangeBytes || projectedEntries > this.#budget.maxRangeEntries) { quota = true; tx.abort(); await done; }
      for (const leaseId of expiredLeases) leaseStore.delete(leaseId);
      for (const candidate of evictions) rangeStore.delete(candidate.key);
      for (const admission of unique.values()) {
        rangeStore.put(recordFor(admission.identity, admission.bytes, ++meta.nextSequence));
      }
      meta.rangeBytes = projectedBytes; meta.rangeEntries = projectedEntries; metaStore.put(meta);
      await done; return Object.freeze(results);
    } catch (error) {
      try { tx.abort(); } catch { /* Transaction already completed or aborted. */ }
      await done.catch(() => undefined);
      if (quota || (typeof error === "object" && error !== null && "name" in error
        && error.name === "QuotaExceededError")) throw new RangeStoreQuotaError();
      throw error;
    }
  }
  async acquireLease(input: ClientLeaseV1): Promise<void> {
    const lease = validateClientLease(input); const database = await this.#open(); const tx = database.transaction(STORES.leases, "readwrite"); const done = completed(tx);
    tx.objectStore(STORES.leases).put({ leaseId: lease.leaseId, pairKey: pairKey(lease.pair), pair: lease.pair, expiresAtEpochMs: lease.expiresAtEpochMs } satisfies LeaseRecord); await done;
  }
  async releaseLease(input: ClientLeaseV1): Promise<void> { const lease = validateClientLease(input); const database = await this.#open(); const tx = database.transaction(STORES.leases, "readwrite"); const done = completed(tx); const current = await request(tx.objectStore(STORES.leases).get(lease.leaseId)) as LeaseRecord | undefined; if (current?.pairKey === pairKey(lease.pair)) tx.objectStore(STORES.leases).delete(lease.leaseId); await done; }
  async setProtectedPairs(active: AppReleasePairV1 | null, previous: AppReleasePairV1 | null): Promise<void> {
    const nextActive = active ? validateAppReleasePair(active) : null; const nextPrevious = previous ? validateAppReleasePair(previous) : null;
    if (nextActive && nextPrevious && samePair(nextActive, nextPrevious)) throw new RangeStoreIntegrityError("Active and previous pairs must differ.");
    const database = await this.#open(); const tx = database.transaction(STORES.meta, "readwrite"); const done = completed(tx); const store = tx.objectStore(STORES.meta); const meta = await this.#meta(store); meta.activePair = nextActive; meta.previousPair = nextPrevious; store.put(meta); await done;
  }
  async inventory(): Promise<RangeInventoryV1> {
    const database = await this.#open(); const tx = database.transaction([STORES.meta, STORES.ranges], "readonly"); const done = completed(tx); const meta = await this.#meta(tx.objectStore(STORES.meta)); const records = await request(tx.objectStore(STORES.ranges).index("by-lru").getAll()) as StoredRange[]; await done;
    return { mode: this.mode, payloadBytes: meta.rangeBytes, entryCount: meta.rangeEntries,
      activePair: meta.activePair, previousPair: meta.previousPair,
      entries: records.map(({ pair, artifactId, path, start, endExclusive, byteLength, lastAccessSequence }) => ({ pair, artifactId, path, start, endExclusive, byteLength, lastAccessSequence })) };
  }
  close(): void { if (this.#database) void this.#database.then((database) => database.close()); this.#database = null; }
}
