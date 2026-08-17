import { cacheNamespaces, exactRecord, validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import { sha256Hex } from "./contracts/v1";
import type { PairLifecycleStateV1 } from "./contracts/policy";
import {
  beginPairCleanupFence,
  pairAdmissionLockName,
  PairCleanupFenceError,
  type PairCleanupLockPort,
} from "./pair-cleanup-fence";

export const OFFLINE_LIFECYCLE_DATABASE = "searise-offline:lifecycle:v1" as const;
export const OFFLINE_LIFECYCLE_STORE = "pair-lifecycle" as const;
const LIFECYCLE_DATABASE_VERSION = 1;
const RECEIPT_DATABASE = "searise-offline:admission-receipts:v1";
const RECEIPT_STORE = "accepted-receipts";
const RANGE_DATABASE = "searise-offline:v1";
const RANGE_STORES = { meta: "range-meta", ranges: "ranges", leases: "leases" } as const;

type PersistedLifecycleStateV1 = Exclude<PairLifecycleStateV1, "removed">;
export type LifecycleFailureCodeV1 = "corrupt-record" | "storage-failed" | "cleanup-failed";

export interface PairAcceptedIdentityV1 {
  readonly precacheSetSha256: string | null;
  readonly resourcePlanSha256: string | null;
  readonly receiptSha256: string | null;
}

export interface PairLifecycleRecordV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly state: PersistedLifecycleStateV1;
  readonly acceptedIdentity: PairAcceptedIdentityV1;
  readonly lastFailure: LifecycleFailureCodeV1 | null;
}

export type PairLifecycleReadV1 =
  | Readonly<{ status: "missing" }>
  | Readonly<{ status: "found"; record: PairLifecycleRecordV1 }>
  | Readonly<{ status: "corrupt"; pair: AppReleasePairV1; reason: string }>;

export interface PairStorageInventoryV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly cacheNames: readonly string[];
  readonly cacheRequestCount: number;
  readonly rangeRecordCount: number;
  readonly rangeBytes: number;
  readonly receiptRecordCount: number;
  readonly receiptSha256: readonly string[];
  readonly leaseRecordCount: number;
  readonly protectedByRangeAuthority: boolean;
}

export interface LifecycleInventoryV1 {
  readonly contractVersion: 1;
  readonly records: readonly PairLifecycleRecordV1[];
  readonly corruptRecordCount: number;
}

export interface ClientLeaseObservationV1 {
  readonly clientId: string;
  readonly state: "inactive" | "active" | "unknown" | "unresponsive";
}

export interface RemovedPairV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly state: "removed";
  readonly removed: Readonly<{
    receiptRecords: number;
    authorityRecords: number;
    cacheNamespaces: number;
    rangeRecords: number;
  }>;
}

export interface LifecycleCache {
  keys(): Promise<readonly Request[]>;
}

export interface LifecycleCacheStorage {
  keys(): Promise<readonly string[]>;
  open(name: string): Promise<LifecycleCache>;
  delete(name: string): Promise<boolean>;
}

export interface PairLifecycleStoreDependencies {
  readonly indexedDB: IDBFactory;
  readonly cacheStorage: LifecycleCacheStorage;
  readonly locks?: PairCleanupLockPort;
  readonly clientCensus?: Readonly<{
    observe(pair: AppReleasePairV1, signal: AbortSignal): Promise<readonly ClientLeaseObservationV1[]>;
  }>;
  readonly now?: () => number;
}

export class PairLifecycleStoreError extends Error {
  readonly code: "Conflict" | "Corrupt" | "CleanupBlocked" | "StorageFailed";

  constructor(code: PairLifecycleStoreError["code"], message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "PairLifecycleStoreError";
    this.code = code;
  }
}

interface StoredRangeSummary {
  readonly key: IDBValidKey;
  readonly pairKey?: unknown;
  readonly byteLength?: unknown;
}

interface StoredLeaseSummary {
  readonly key: IDBValidKey;
  readonly pairKey?: unknown;
  readonly expiresAtEpochMs?: unknown;
}

interface StoredReceiptSummary {
  readonly key?: unknown;
  readonly receipt?: unknown;
  readonly receiptSha256?: unknown;
}

const PERSISTED_STATES = new Set<PersistedLifecycleStateV1>([
  "staging", "bootstrap-complete", "core-complete", "active", "previous", "cleanup-pending", "corrupt",
]);
const FAILURES = new Set<LifecycleFailureCodeV1>(["corrupt-record", "storage-failed", "cleanup-failed"]);
const COMPLETE_STATES = new Set<PersistedLifecycleStateV1>([
  "core-complete", "active", "previous",
]);
const CLIENT_ID = /^[A-Za-z0-9._:-]{1,128}$/u;

function request<T>(value: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    value.onsuccess = () => resolve(value.result);
    value.onerror = () => reject(value.error);
  });
}

function completed(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = transaction.onerror = () => reject(
      transaction.error ?? new DOMException("Lifecycle transaction aborted.", "AbortError"),
    );
  });
}

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}

function lifecycleKey(pair: AppReleasePairV1): string {
  return cacheNamespaces(pair).pairKey;
}

function digest(value: unknown, name: string): string | null {
  return value === null ? null : sha256Hex(value, name);
}

function completeIdentity(identity: PairAcceptedIdentityV1): boolean {
  return identity.precacheSetSha256 !== null &&
    identity.resourcePlanSha256 !== null && identity.receiptSha256 !== null;
}

function validateAcceptedIdentity(value: unknown): PairAcceptedIdentityV1 {
  const record = exactRecord(
    value,
    ["precacheSetSha256", "resourcePlanSha256", "receiptSha256"],
    "pair accepted identity",
  );
  const identity = Object.freeze({
    precacheSetSha256: digest(record.precacheSetSha256, "precacheSetSha256"),
    resourcePlanSha256: digest(record.resourcePlanSha256, "resourcePlanSha256"),
    receiptSha256: digest(record.receiptSha256, "receiptSha256"),
  });
  if ((identity.resourcePlanSha256 === null) !== (identity.receiptSha256 === null)) {
    throw new TypeError("Resource-plan and admission-receipt identities must be bound together.");
  }
  if (identity.precacheSetSha256 === null && identity.resourcePlanSha256 !== null) {
    throw new TypeError("Core admission identity cannot exist without its accepted precache identity.");
  }
  return identity;
}

export function validatePairLifecycleRecord(value: unknown): PairLifecycleRecordV1 {
  const record = exactRecord(
    value,
    ["contractVersion", "pair", "state", "acceptedIdentity", "lastFailure"],
    "stored pair lifecycle",
  );
  if (record.contractVersion !== 1 || !PERSISTED_STATES.has(record.state as PersistedLifecycleStateV1)) {
    throw new TypeError("Stored pair lifecycle version or state is unsupported.");
  }
  const state = record.state as PersistedLifecycleStateV1;
  const acceptedIdentity = validateAcceptedIdentity(record.acceptedIdentity);
  const lastFailure = record.lastFailure === null ? null : record.lastFailure as LifecycleFailureCodeV1;
  if (lastFailure !== null && !FAILURES.has(lastFailure)) throw new TypeError("Lifecycle failure code is unsupported.");
  if (state === "staging" && Object.values(acceptedIdentity).some((value) => value !== null)) {
    throw new TypeError("Staging cannot claim accepted bytes.");
  }
  if (state === "bootstrap-complete" && (
    acceptedIdentity.precacheSetSha256 === null || acceptedIdentity.resourcePlanSha256 !== null
  )) throw new TypeError("Bootstrap completion requires only the exact precache identity.");
  if (COMPLETE_STATES.has(state) && !completeIdentity(acceptedIdentity)) {
    throw new TypeError("Complete lifecycle states require the composite accepted identity.");
  }
  if (state === "corrupt" && lastFailure === null) throw new TypeError("Corrupt lifecycle state requires a failure code.");
  return Object.freeze({
    contractVersion: 1,
    pair: validateAppReleasePair(record.pair),
    state,
    acceptedIdentity,
    lastFailure,
  });
}

function emptyIdentity(): PairAcceptedIdentityV1 {
  return Object.freeze({ precacheSetSha256: null, resourcePlanSha256: null, receiptSha256: null });
}

function lifecycleRecord(
  pair: AppReleasePairV1,
  state: PersistedLifecycleStateV1,
  acceptedIdentity: PairAcceptedIdentityV1,
  lastFailure: LifecycleFailureCodeV1 | null = null,
): PairLifecycleRecordV1 {
  return validatePairLifecycleRecord({ contractVersion: 1, pair, state, acceptedIdentity, lastFailure });
}

function validateObservation(value: ClientLeaseObservationV1): ClientLeaseObservationV1 {
  const record = exactRecord(value, ["clientId", "state"], "client lease observation");
  if (typeof record.clientId !== "string" || !CLIENT_ID.test(record.clientId) ||
      !new Set(["inactive", "active", "unknown", "unresponsive"]).has(record.state as string)) {
    throw new TypeError("Client lease observation is invalid.");
  }
  return Object.freeze({ clientId: record.clientId, state: record.state as ClientLeaseObservationV1["state"] });
}

function receiptPairKey(record: StoredReceiptSummary): string | null {
  if (typeof record.key === "string") {
    try {
      const parsed = JSON.parse(record.key) as unknown;
      if (Array.isArray(parsed) && parsed.length === 2 && typeof parsed[0] === "string") return parsed[0];
    } catch { return null; }
  }
  return null;
}

export class PairLifecycleStore {
  readonly #idb: IDBFactory;
  readonly #cacheStorage: LifecycleCacheStorage;
  readonly #locks: PairCleanupLockPort | undefined;
  readonly #clientCensus: PairLifecycleStoreDependencies["clientCensus"];
  readonly #now: () => number;
  #database: Promise<IDBDatabase> | null = null;

  constructor(dependencies: PairLifecycleStoreDependencies) {
    this.#idb = dependencies.indexedDB;
    this.#cacheStorage = dependencies.cacheStorage;
    this.#locks = dependencies.locks;
    this.#clientCensus = dependencies.clientCensus;
    this.#now = dependencies.now ?? Date.now;
  }

  #open(): Promise<IDBDatabase> {
    if (!this.#database) this.#database = new Promise((resolve, reject) => {
      const open = this.#idb.open(OFFLINE_LIFECYCLE_DATABASE, LIFECYCLE_DATABASE_VERSION);
      open.onupgradeneeded = () => {
        if (!open.result.objectStoreNames.contains(OFFLINE_LIFECYCLE_STORE)) {
          open.result.createObjectStore(OFFLINE_LIFECYCLE_STORE, { keyPath: "key" });
        }
      };
      open.onsuccess = () => { open.result.onversionchange = () => open.result.close(); resolve(open.result); };
      open.onerror = () => reject(open.error ?? new PairLifecycleStoreError("StorageFailed", "Lifecycle database open failed."));
      open.onblocked = () => reject(new PairLifecycleStoreError("StorageFailed", "Lifecycle database open was blocked."));
    });
    return this.#database;
  }

  async #databaseNames(): Promise<ReadonlySet<string>> {
    if (typeof this.#idb.databases !== "function") {
      throw new PairLifecycleStoreError("StorageFailed", "Safe IndexedDB inventory is unavailable.");
    }
    return new Set((await this.#idb.databases()).flatMap((entry) => entry.name ? [entry.name] : []));
  }

  async #openExisting(name: string, names: ReadonlySet<string>): Promise<IDBDatabase | null> {
    if (!names.has(name)) return null;
    return await new Promise((resolve, reject) => {
      const open = this.#idb.open(name);
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error ?? new PairLifecycleStoreError("StorageFailed", `IndexedDB ${name} open failed.`));
      open.onblocked = () => reject(new PairLifecycleStoreError("StorageFailed", `IndexedDB ${name} open was blocked.`));
    });
  }

  async read(pairInput: AppReleasePairV1): Promise<PairLifecycleReadV1> {
    const pair = validateAppReleasePair(pairInput);
    const database = await this.#open();
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readonly");
    const done = completed(transaction);
    const stored = await request(transaction.objectStore(OFFLINE_LIFECYCLE_STORE).get(lifecycleKey(pair))) as
      | Readonly<{ key: string; record: unknown }>
      | undefined;
    await done;
    if (!stored) return Object.freeze({ status: "missing" });
    try {
      if (stored.key !== lifecycleKey(pair)) throw new TypeError("Lifecycle key does not match its pair.");
      const record = validatePairLifecycleRecord(stored.record);
      if (!samePair(record.pair, pair)) throw new TypeError("Lifecycle record belongs to another pair.");
      return Object.freeze({ status: "found", record });
    } catch (error) {
      return Object.freeze({
        status: "corrupt",
        pair,
        reason: error instanceof Error ? error.message : "Lifecycle record validation failed.",
      });
    }
  }

  async #putNew(record: PairLifecycleRecordV1): Promise<PairLifecycleRecordV1> {
    const database = await this.#open();
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readwrite");
    const done = completed(transaction);
    const store = transaction.objectStore(OFFLINE_LIFECYCLE_STORE);
    const key = lifecycleKey(record.pair);
    if (await request(store.get(key))) {
      transaction.abort(); await done.catch(() => undefined);
      throw new PairLifecycleStoreError("Conflict", "A lifecycle record already exists for this exact pair.");
    }
    store.add({ key, record });
    await done;
    return record;
  }

  async stage(pairInput: AppReleasePairV1): Promise<PairLifecycleRecordV1> {
    const pair = validateAppReleasePair(pairInput);
    return this.#putNew(lifecycleRecord(pair, "staging", emptyIdentity()));
  }

  async #replace(
    pair: AppReleasePairV1,
    expected: readonly PersistedLifecycleStateV1[],
    next: (current: PairLifecycleRecordV1) => PairLifecycleRecordV1,
  ): Promise<PairLifecycleRecordV1> {
    const database = await this.#open();
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readwrite");
    const done = completed(transaction);
    const store = transaction.objectStore(OFFLINE_LIFECYCLE_STORE);
    const key = lifecycleKey(pair);
    try {
      const stored = await request(store.get(key)) as Readonly<{ key: string; record: unknown }> | undefined;
      if (!stored) throw new PairLifecycleStoreError("Conflict", "Lifecycle record is missing for this exact pair.");
      const current = validatePairLifecycleRecord(stored.record);
      if (!samePair(current.pair, pair) || !expected.includes(current.state)) {
        throw new PairLifecycleStoreError("Conflict", `Lifecycle transition from ${current.state} is not allowed.`);
      }
      const replacement = next(current);
      store.put({ key, record: replacement });
      await done;
      return replacement;
    } catch (error) {
      try { transaction.abort(); } catch { /* Transaction completed. */ }
      await done.catch(() => undefined);
      if (error instanceof PairLifecycleStoreError) throw error;
      throw new PairLifecycleStoreError("Corrupt", "Lifecycle transition found a corrupt record.", error);
    }
  }

  async completeBootstrap(pairInput: AppReleasePairV1, precacheSetSha256: string): Promise<PairLifecycleRecordV1> {
    const pair = validateAppReleasePair(pairInput);
    const precache = sha256Hex(precacheSetSha256, "precacheSetSha256");
    return this.#replace(pair, ["staging"], () => lifecycleRecord(pair, "bootstrap-complete", {
      precacheSetSha256: precache, resourcePlanSha256: null, receiptSha256: null,
    }));
  }

  async completeCore(pairInput: AppReleasePairV1, identityInput: PairAcceptedIdentityV1): Promise<PairLifecycleRecordV1> {
    const pair = validateAppReleasePair(pairInput);
    const identity = validateAcceptedIdentity(identityInput);
    if (!completeIdentity(identity)) throw new PairLifecycleStoreError("Conflict", "Core completion requires the composite accepted identity.");
    return this.#replace(pair, ["bootstrap-complete"], (current) => {
      if (current.acceptedIdentity.precacheSetSha256 !== identity.precacheSetSha256) {
        throw new PairLifecycleStoreError("Conflict", "Core completion changed the accepted precache identity.");
      }
      return lifecycleRecord(pair, "core-complete", identity);
    });
  }

  async activate(pairInput: AppReleasePairV1): Promise<PairLifecycleRecordV1> {
    const pair = validateAppReleasePair(pairInput);
    const database = await this.#open();
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readwrite");
    const done = completed(transaction);
    const store = transaction.objectStore(OFFLINE_LIFECYCLE_STORE);
    try {
      const stored = await request(store.getAll()) as Readonly<{ key: string; record: unknown }>[];
      const records = stored.map(({ key, record }) => {
        const validated = validatePairLifecycleRecord(record);
        if (key !== lifecycleKey(validated.pair)) throw new TypeError("Lifecycle key does not match its pair.");
        return validated;
      });
      const target = records.find((record) => samePair(record.pair, pair));
      if (!target || target.state !== "core-complete") {
        throw new PairLifecycleStoreError("Conflict", "Only a core-complete pair may become active.");
      }
      if (records.filter(({ state }) => state === "active").length > 1 ||
          records.filter(({ state }) => state === "previous").length > 1) {
        throw new PairLifecycleStoreError("Corrupt", "Lifecycle inventory has multiple active or previous pairs.");
      }
      for (const record of records) {
        if (record.state === "previous") {
          store.put({ key: lifecycleKey(record.pair), record: lifecycleRecord(
            record.pair, "cleanup-pending", record.acceptedIdentity,
          ) });
        } else if (record.state === "active") {
          store.put({ key: lifecycleKey(record.pair), record: lifecycleRecord(
            record.pair, "previous", record.acceptedIdentity,
          ) });
        }
      }
      const active = lifecycleRecord(pair, "active", target.acceptedIdentity);
      store.put({ key: lifecycleKey(pair), record: active });
      await done;
      return active;
    } catch (error) {
      try { transaction.abort(); } catch { /* Transaction completed. */ }
      await done.catch(() => undefined);
      if (error instanceof PairLifecycleStoreError) throw error;
      throw new PairLifecycleStoreError("Corrupt", "Activation found a corrupt lifecycle inventory.", error);
    }
  }

  async markCleanupPending(pairInput: AppReleasePairV1): Promise<PairLifecycleRecordV1> {
    const pair = validateAppReleasePair(pairInput);
    return this.#replace(pair, ["staging", "bootstrap-complete", "core-complete", "corrupt"], (current) =>
      lifecycleRecord(pair, "cleanup-pending", current.acceptedIdentity, current.lastFailure));
  }

  async markCorrupt(pairInput: AppReleasePairV1): Promise<PairLifecycleRecordV1> {
    const pair = validateAppReleasePair(pairInput);
    const current = await this.read(pair);
    if (current.status === "missing") return this.#putNew(lifecycleRecord(pair, "corrupt", emptyIdentity(), "corrupt-record"));
    if (current.status === "corrupt") {
      const database = await this.#open();
      const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readwrite");
      transaction.objectStore(OFFLINE_LIFECYCLE_STORE).put({
        key: lifecycleKey(pair), record: lifecycleRecord(pair, "corrupt", emptyIdentity(), "corrupt-record"),
      });
      await completed(transaction);
      return (await this.read(pair) as Extract<PairLifecycleReadV1, { status: "found" }>).record;
    }
    return this.#replace(pair, [current.record.state], (record) =>
      lifecycleRecord(pair, "corrupt", record.acceptedIdentity, "corrupt-record"));
  }

  async inventory(): Promise<LifecycleInventoryV1> {
    const database = await this.#open();
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readonly");
    const done = completed(transaction);
    const stored = await request(transaction.objectStore(OFFLINE_LIFECYCLE_STORE).getAll()) as
      Readonly<{ key: string; record: unknown }>[];
    await done;
    const records: PairLifecycleRecordV1[] = [];
    let corruptRecordCount = 0;
    for (const item of stored) {
      try {
        const record = validatePairLifecycleRecord(item.record);
        if (item.key !== lifecycleKey(record.pair)) throw new TypeError("Lifecycle key does not match pair.");
        records.push(record);
      } catch { corruptRecordCount += 1; }
    }
    records.sort((left, right) => lifecycleKey(left.pair).localeCompare(lifecycleKey(right.pair)));
    return Object.freeze({ contractVersion: 1, records: Object.freeze(records), corruptRecordCount });
  }

  async storageInventory(pairInput: AppReleasePairV1): Promise<PairStorageInventoryV1> {
    const pair = validateAppReleasePair(pairInput);
    const namespaces = cacheNamespaces(pair);
    const cacheNames = (await this.#cacheStorage.keys()).filter((name) =>
      name === namespaces.shell || name === namespaces.release ||
      name.startsWith(`${namespaces.shell}:staging:`) || name.startsWith(`${namespaces.release}:staging:`));
    let cacheRequestCount = 0;
    for (const name of cacheNames) cacheRequestCount += (await (await this.#cacheStorage.open(name)).keys()).length;

    const names = await this.#databaseNames();
    const range = await this.#openExisting(RANGE_DATABASE, names);
    let ranges: StoredRangeSummary[] = [];
    let leases: StoredLeaseSummary[] = [];
    let protectedByRangeAuthority = false;
    if (range) {
      try {
        const stores = [RANGE_STORES.ranges, RANGE_STORES.leases, RANGE_STORES.meta]
          .filter((name) => range.objectStoreNames.contains(name));
        if (stores.length) {
          const transaction = range.transaction(stores, "readonly");
          const done = completed(transaction);
          ranges = range.objectStoreNames.contains(RANGE_STORES.ranges)
            ? await request(transaction.objectStore(RANGE_STORES.ranges).getAll()) as StoredRangeSummary[] : [];
          leases = range.objectStoreNames.contains(RANGE_STORES.leases)
            ? await request(transaction.objectStore(RANGE_STORES.leases).getAll()) as StoredLeaseSummary[] : [];
          if (range.objectStoreNames.contains(RANGE_STORES.meta)) {
            const meta = await request(transaction.objectStore(RANGE_STORES.meta).get("state")) as
              | Readonly<{ activePair?: unknown; previousPair?: unknown }>
              | undefined;
            for (const candidate of [meta?.activePair, meta?.previousPair]) {
              try { if (candidate && samePair(validateAppReleasePair(candidate), pair)) protectedByRangeAuthority = true; } catch { protectedByRangeAuthority = true; }
            }
          }
          await done;
        }
      } finally { range.close(); }
    }

    const receiptsDatabase = await this.#openExisting(RECEIPT_DATABASE, names);
    let receipts: StoredReceiptSummary[] = [];
    if (receiptsDatabase) {
      try {
        if (receiptsDatabase.objectStoreNames.contains(RECEIPT_STORE)) {
          const transaction = receiptsDatabase.transaction(RECEIPT_STORE, "readonly");
          const done = completed(transaction);
          receipts = await request(transaction.objectStore(RECEIPT_STORE).getAll()) as StoredReceiptSummary[];
          await done;
        }
      } finally { receiptsDatabase.close(); }
    }

    const pairRanges = ranges.filter((record) => record.pairKey === namespaces.pairKey);
    const pairLeases = leases.filter((record) => record.pairKey === namespaces.pairKey);
    const pairReceipts = receipts.filter((record) => receiptPairKey(record) === namespaces.pairKey);
    return Object.freeze({
      contractVersion: 1,
      pair,
      cacheNames: Object.freeze([...cacheNames].sort()),
      cacheRequestCount,
      rangeRecordCount: pairRanges.length,
      rangeBytes: pairRanges.reduce((sum, record) => sum + (
        Number.isSafeInteger(record.byteLength) && Number(record.byteLength) >= 0 ? Number(record.byteLength) : 0
      ), 0),
      receiptRecordCount: pairReceipts.length,
      receiptSha256: Object.freeze(pairReceipts.flatMap((record) => {
        try { return [sha256Hex(record.receiptSha256, "receiptSha256")]; } catch { return []; }
      }).sort()),
      leaseRecordCount: pairLeases.length,
      protectedByRangeAuthority,
    });
  }

  async #deleteReceiptAuthority(pair: AppReleasePairV1): Promise<Readonly<{ receipts: number; authority: number }>> {
    const names = await this.#databaseNames();
    let receipts = 0;
    let authority = 0;
    const receiptDatabase = await this.#openExisting(RECEIPT_DATABASE, names);
    if (receiptDatabase) {
      try {
        if (receiptDatabase.objectStoreNames.contains(RECEIPT_STORE)) {
          const transaction = receiptDatabase.transaction(RECEIPT_STORE, "readwrite");
          const done = completed(transaction);
          const store = transaction.objectStore(RECEIPT_STORE);
          const records = await request(store.getAll()) as StoredReceiptSummary[];
          for (const record of records) {
            if (receiptPairKey(record) === lifecycleKey(pair) && record.key !== undefined) {
              store.delete(record.key as IDBValidKey); receipts += 1;
            }
          }
          await done;
        }
      } finally { receiptDatabase.close(); }
    }
    const rangeDatabase = await this.#openExisting(RANGE_DATABASE, names);
    if (rangeDatabase) {
      try {
        if (rangeDatabase.objectStoreNames.contains(RANGE_STORES.leases)) {
          const transaction = rangeDatabase.transaction(RANGE_STORES.leases, "readwrite");
          const done = completed(transaction);
          const store = transaction.objectStore(RANGE_STORES.leases);
          const records = await request(store.getAll()) as StoredLeaseSummary[];
          for (const record of records) {
            if (record.pairKey === lifecycleKey(pair)) { store.delete(record.key); authority += 1; }
          }
          await done;
        }
      } finally { rangeDatabase.close(); }
    }
    return Object.freeze({ receipts, authority });
  }

  async #deleteRanges(pair: AppReleasePairV1): Promise<number> {
    const names = await this.#databaseNames();
    const database = await this.#openExisting(RANGE_DATABASE, names);
    if (!database || !database.objectStoreNames.contains(RANGE_STORES.ranges)) {
      database?.close(); return 0;
    }
    try {
      const stores = [RANGE_STORES.ranges, ...(database.objectStoreNames.contains(RANGE_STORES.meta) ? [RANGE_STORES.meta] : [])];
      const transaction = database.transaction(stores, "readwrite");
      const done = completed(transaction);
      const rangeStore = transaction.objectStore(RANGE_STORES.ranges);
      const records = await request(rangeStore.getAll()) as StoredRangeSummary[];
      const removed = records.filter((record) => record.pairKey === lifecycleKey(pair));
      for (const record of removed) rangeStore.delete(record.key);
      if (database.objectStoreNames.contains(RANGE_STORES.meta)) {
        const metaStore = transaction.objectStore(RANGE_STORES.meta);
        const meta = await request(metaStore.get("state")) as Record<string, unknown> | undefined;
        if (meta) {
          const bytes = removed.reduce((sum, record) => sum + (
            Number.isSafeInteger(record.byteLength) && Number(record.byteLength) >= 0 ? Number(record.byteLength) : 0
          ), 0);
          meta.rangeEntries = Math.max(0, Number(meta.rangeEntries ?? 0) - removed.length);
          meta.rangeBytes = Math.max(0, Number(meta.rangeBytes ?? 0) - bytes);
          metaStore.put(meta);
        }
      }
      await done;
      return removed.length;
    } finally { database.close(); }
  }

  async #deleteLifecycle(pair: AppReleasePairV1): Promise<void> {
    const database = await this.#open();
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readwrite");
    const done = completed(transaction);
    const store = transaction.objectStore(OFFLINE_LIFECYCLE_STORE);
    const stored = await request(store.get(lifecycleKey(pair))) as Readonly<{ record: unknown }> | undefined;
    const record = stored ? validatePairLifecycleRecord(stored.record) : null;
    if (!record || record.state !== "cleanup-pending" || !samePair(record.pair, pair)) {
      transaction.abort(); await done.catch(() => undefined);
      throw new PairLifecycleStoreError("Conflict", "Lifecycle authority changed before final removal.");
    }
    store.delete(lifecycleKey(pair));
    await done;
  }

  async removeExactPair(
    pairInput: AppReleasePairV1,
  ): Promise<RemovedPairV1> {
    const pair = validateAppReleasePair(pairInput);
    if (!this.#locks || !this.#clientCensus) {
      throw new PairLifecycleStoreError(
        "StorageFailed", "A cross-context lock and service-worker client census are required for cleanup.",
      );
    }
    const signal = new AbortController().signal;
    let operationStarted = false;
    try {
      return await this.#locks.request(pairAdmissionLockName(pair), { mode: "exclusive", signal }, async () => {
        operationStarted = true;
        let observations: readonly ClientLeaseObservationV1[];
        try {
          observations = (await this.#clientCensus!.observe(pair, signal)).map(validateObservation);
        } catch (error) {
          throw new PairLifecycleStoreError(
            "CleanupBlocked", "The service-worker client census failed closed.", error,
          );
        }
        return this.#removeExactPairLocked(pair, observations);
      });
    } catch (error) {
      if (operationStarted || error instanceof PairLifecycleStoreError) throw error;
      throw new PairLifecycleStoreError("StorageFailed", "Cross-context exact-pair cleanup lock failed.", error);
    }
  }

  async #removeExactPairLocked(
    pair: AppReleasePairV1,
    observations: readonly ClientLeaseObservationV1[],
  ): Promise<RemovedPairV1> {
    const lifecycle = await this.read(pair);
    if (lifecycle.status !== "found" || lifecycle.record.state !== "cleanup-pending") {
      throw new PairLifecycleStoreError("Conflict", "Only a cleanup-pending exact pair may be removed.");
    }
    const lifecycleInventory = await this.inventory();
    if (lifecycleInventory.corruptRecordCount > 0) {
      throw new PairLifecycleStoreError("CleanupBlocked", "Unknown corrupt lifecycle authority blocks cleanup.");
    }
    const active = lifecycleInventory.records.filter(({ state }) => state === "active");
    const previous = lifecycleInventory.records.filter(({ state }) => state === "previous");
    const retained = [...active, ...previous];
    if (active.length > 1 || previous.length > 1 || (previous.length === 1 && active.length !== 1) ||
        retained.some(({ acceptedIdentity }) => !completeIdentity(acceptedIdentity)) ||
        retained.some((record) => samePair(record.pair, pair))) {
      throw new PairLifecycleStoreError("CleanupBlocked", "Active and immediately previous complete pairs must be retained.");
    }
    const unsafeObservedLease = observations.some(({ state }) =>
      state === "active" || state === "unknown" || state === "unresponsive");
    if (unsafeObservedLease) {
      throw new PairLifecycleStoreError("CleanupBlocked", "An active, unknown, or unresponsive client lease blocks cleanup.");
    }

    try {
      await beginPairCleanupFence(this.#idb, pair, this.#now);
    } catch (error) {
      if (error instanceof PairCleanupFenceError && error.code === "CleanupBlocked") {
        throw new PairLifecycleStoreError("CleanupBlocked", error.message, error);
      }
      throw new PairLifecycleStoreError("StorageFailed", "Exact-pair cleanup fence could not be established.", error);
    }
    const storage = await this.storageInventory(pair);

    let deletedAuthority: Readonly<{ receipts: number; authority: number }> = { receipts: 0, authority: 0 };
    let cacheNamespacesDeleted = 0;
    let rangeRecords = 0;
    try {
      deletedAuthority = await this.#deleteReceiptAuthority(pair);
      for (const name of storage.cacheNames) {
        if (await this.#cacheStorage.delete(name)) cacheNamespacesDeleted += 1;
      }
      rangeRecords = await this.#deleteRanges(pair);
      await this.#deleteLifecycle(pair);
    } catch (error) {
      await this.#replace(pair, ["cleanup-pending"], (current) =>
        lifecycleRecord(pair, "cleanup-pending", current.acceptedIdentity, "cleanup-failed")).catch(() => undefined);
      if (error instanceof PairLifecycleStoreError) throw error;
      throw new PairLifecycleStoreError("StorageFailed", "Exact-pair cleanup failed and remains retryable.", error);
    }
    return Object.freeze({
      contractVersion: 1,
      pair,
      state: "removed",
      removed: Object.freeze({
        receiptRecords: deletedAuthority.receipts,
        authorityRecords: deletedAuthority.authority,
        cacheNamespaces: cacheNamespacesDeleted,
        rangeRecords,
      }),
    });
  }

  close(): void {
    if (this.#database) void this.#database.then((database) => database.close());
    this.#database = null;
  }
}
