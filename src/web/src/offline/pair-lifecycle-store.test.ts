// @vitest-environment node

import { IDBFactory, IDBObjectStore } from "fake-indexeddb";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cacheNamespaces, validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import {
  OFFLINE_LIFECYCLE_DATABASE,
  OFFLINE_LIFECYCLE_STORE,
  PairLifecycleStore,
  PairLifecycleStoreError,
  type LifecycleCache,
  type LifecycleCacheStorage,
  type PairAcceptedIdentityV1,
} from "./pair-lifecycle-store";
import {
  assertPairAdmissionOpen,
  pairAdmissionLockName,
  type PairCleanupLockPort,
} from "./pair-cleanup-fence";

const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);

function pair(build = "build-a", release = "release-a"): AppReleasePairV1 {
  return validateAppReleasePair({ contractVersion: 1, appBuildId: build, dataReleaseId: release });
}

function identity(precacheSetSha256 = A): PairAcceptedIdentityV1 {
  return Object.freeze({ precacheSetSha256, resourcePlanSha256: B, receiptSha256: C });
}

class MemoryCache implements LifecycleCache {
  readonly requests: Request[] = [];
  async keys(): Promise<readonly Request[]> { return this.requests; }
}

class MemoryCaches implements LifecycleCacheStorage {
  readonly stores = new Map<string, MemoryCache>();
  readonly events: string[] = [];
  failDelete = false;
  onDelete: ((name: string) => void | Promise<void>) | null = null;

  seed(name: string, ...urls: string[]): void {
    const cache = new MemoryCache();
    cache.requests.push(...urls.map((url) => new Request(url)));
    this.stores.set(name, cache);
  }

  async keys(): Promise<readonly string[]> { return [...this.stores.keys()]; }
  async open(name: string): Promise<MemoryCache> {
    let cache = this.stores.get(name);
    if (!cache) { cache = new MemoryCache(); this.stores.set(name, cache); }
    return cache;
  }
  async delete(name: string): Promise<boolean> {
    this.events.push(`cache:${name}`);
    await this.onDelete?.(name);
    if (this.failDelete) throw new Error("synthetic cache deletion failure");
    return this.stores.delete(name);
  }
}

class TestPairLocks implements PairCleanupLockPort {
  readonly #tails = new Map<string, Promise<void>>();
  beforeOperation: (() => Promise<void>) | null = null;

  async request<T>(
    name: string,
    options: Readonly<{ mode: "exclusive"; signal: AbortSignal }>,
    operation: () => Promise<T>,
  ): Promise<T> {
    const previous = this.#tails.get(name) ?? Promise.resolve();
    let release!: () => void;
    const current = new Promise<void>((resolve) => { release = resolve; });
    this.#tails.set(name, previous.then(() => current));
    await previous;
    if (options.signal.aborted) throw new DOMException("Aborted", "AbortError");
    try {
      await this.beforeOperation?.();
      return await operation();
    } finally {
      release();
    }
  }
}

function openDatabase(factory: IDBFactory, name: string, version?: number): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const opened = version === undefined ? factory.open(name) : factory.open(name, version);
    opened.onsuccess = () => resolve(opened.result);
    opened.onerror = () => reject(opened.error);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = transaction.onabort = () => reject(transaction.error);
  });
}

async function seedRangeDatabase(
  factory: IDBFactory,
  target: AppReleasePairV1,
  options: Readonly<{
    leaseExpiresAt?: number;
    protectedAs?: "active" | "previous";
    otherLease?: Readonly<{ pair: AppReleasePairV1; expiresAt: number }>;
  }> = {},
): Promise<void> {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const opened = factory.open("searise-offline:v1", 2);
    opened.onupgradeneeded = () => {
      const meta = opened.result.createObjectStore("range-meta", { keyPath: "key" });
      const ranges = opened.result.createObjectStore("ranges", { keyPath: "key" });
      ranges.createIndex("by-pair", "pairKey");
      ranges.createIndex("by-lru", ["lastAccessSequence", "key"], { unique: true });
      const leases = opened.result.createObjectStore("leases", { keyPath: "key" });
      leases.createIndex("by-pair", "pairKey");
      leases.createIndex("by-expiry", ["expiresAtEpochMs", "pairKey", "leaseId"], { unique: true });
      meta.put({
        key: "state", rangeBytes: 12, rangeEntries: 2, nextSequence: 2,
        activePair: options.protectedAs === "active" ? target : null,
        previousPair: options.protectedAs === "previous" ? target : null,
      });
      const targetKey = cacheNamespaces(target).pairKey;
      ranges.put({ key: "target-range", pairKey: targetKey, byteLength: 4, lastAccessSequence: 1 });
      ranges.put({ key: "other-range", pairKey: cacheNamespaces(pair("build-z", "release-z")).pairKey, byteLength: 8, lastAccessSequence: 2 });
      if (options.leaseExpiresAt !== undefined) leases.put({
        key: "target-lease", leaseId: "target-lease", pairKey: targetKey,
        pair: target, expiresAtEpochMs: options.leaseExpiresAt,
      });
      if (options.otherLease) leases.put({
        key: "other-lease", leaseId: "other-lease",
        pairKey: cacheNamespaces(options.otherLease.pair).pairKey,
        pair: options.otherLease.pair, expiresAtEpochMs: options.otherLease.expiresAt,
      });
    };
    opened.onsuccess = () => resolve(opened.result);
    opened.onerror = () => reject(opened.error);
  });
  database.close();
}

async function seedReceiptDatabase(factory: IDBFactory, target: AppReleasePairV1): Promise<void> {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const opened = factory.open("searise-offline:admission-receipts:v1", 1);
    opened.onupgradeneeded = () => opened.result.createObjectStore("accepted-receipts", { keyPath: "key" });
    opened.onsuccess = () => resolve(opened.result);
    opened.onerror = () => reject(opened.error);
  });
  const transaction = database.transaction("accepted-receipts", "readwrite");
  const store = transaction.objectStore("accepted-receipts");
  store.put({
    key: JSON.stringify([cacheNamespaces(target).pairKey, B]),
    receipt: { pair: target },
    receiptSha256: C,
  });
  store.put({
    key: JSON.stringify([cacheNamespaces(pair("build-z", "release-z")).pairKey, B]),
    receipt: { pair: pair("build-z", "release-z") },
    receiptSha256: C,
  });
  await transactionDone(transaction);
  database.close();
}

async function putLease(
  factory: IDBFactory,
  target: AppReleasePairV1,
  leaseId: string,
  expiresAtEpochMs: number,
): Promise<void> {
  const database = await openDatabase(factory, "searise-offline:v1");
  const transaction = database.transaction("leases", "readwrite");
  transaction.objectStore("leases").put({
    key: JSON.stringify([cacheNamespaces(target).pairKey, leaseId]),
    leaseId,
    pairKey: cacheNamespaces(target).pairKey,
    pair: target,
    expiresAtEpochMs,
  });
  await transactionDone(transaction);
  database.close();
}

async function publishSyntheticAdmission(factory: IDBFactory, target: AppReleasePairV1): Promise<void> {
  await assertPairAdmissionOpen(factory, target);
  const rangeDatabase = await openDatabase(factory, "searise-offline:v1");
  const rangeTransaction = rangeDatabase.transaction("ranges", "readwrite");
  rangeTransaction.objectStore("ranges").put({
    key: "racing-range",
    pairKey: cacheNamespaces(target).pairKey,
    byteLength: 4,
    lastAccessSequence: 100,
  });
  await transactionDone(rangeTransaction);
  rangeDatabase.close();

  const receiptDatabase = await openDatabase(factory, "searise-offline:admission-receipts:v1");
  const receiptTransaction = receiptDatabase.transaction("accepted-receipts", "readwrite");
  receiptTransaction.objectStore("accepted-receipts").put({
    key: JSON.stringify([cacheNamespaces(target).pairKey, "racing-plan"]),
    receipt: { pair: target },
    receiptSha256: C,
  });
  await transactionDone(receiptTransaction);
  receiptDatabase.close();
}

async function makeComplete(store: PairLifecycleStore, value: AppReleasePairV1): Promise<void> {
  await store.stage(value);
  await store.completeBootstrap(value, A);
  await store.completeCore(value, identity());
}

describe("versioned exact-pair lifecycle store", () => {
  let factory: IDBFactory;
  let caches: MemoryCaches;
  let locks: TestPairLocks;
  let store: PairLifecycleStore;

  beforeEach(() => {
    factory = new IDBFactory();
    caches = new MemoryCaches();
    locks = new TestPairLocks();
    store = new PairLifecycleStore({ indexedDB: factory, cacheStorage: caches, locks, now: () => 1_000 });
  });

  it("binds bootstrap and core completion to the exact composite SHA-256 identity", async () => {
    const target = pair();
    await expect(store.stage(target)).resolves.toMatchObject({ state: "staging" });
    await expect(store.completeBootstrap(target, A)).resolves.toMatchObject({
      state: "bootstrap-complete",
      acceptedIdentity: { precacheSetSha256: A, resourcePlanSha256: null, receiptSha256: null },
    });
    await expect(store.completeCore(target, identity())).resolves.toMatchObject({
      state: "core-complete",
      acceptedIdentity: identity(),
    });
    await expect(store.completeBootstrap(target, A)).rejects.toMatchObject({ code: "Conflict" });
    await expect(store.activate(target)).resolves.toMatchObject({ state: "active" });
    expect(JSON.stringify(await store.inventory())).not.toMatch(/query|place|coordinate|profile|latitude|longitude/iu);
  });

  it("rejects a changed precache identity and incomplete admission binding", async () => {
    const target = pair();
    await store.stage(target);
    await store.completeBootstrap(target, A);
    await expect(store.completeCore(target, identity("d".repeat(64)))).rejects.toMatchObject({ code: "Conflict" });
    await expect(store.completeCore(target, {
      precacheSetSha256: A, resourcePlanSha256: B, receiptSha256: null,
    })).rejects.toThrow(/bound together/);
    await expect(store.completeCore(target, {
      precacheSetSha256: null, resourcePlanSha256: B, receiptSha256: C,
    })).rejects.toThrow(/without its accepted precache/);
  });

  it("retains active plus immediate previous complete pair and queues only the older pair", async () => {
    const first = pair("build-1", "release-1");
    const second = pair("build-2", "release-2");
    const third = pair("build-3", "release-3");
    for (const value of [first, second, third]) {
      await makeComplete(store, value);
      await store.activate(value);
    }
    const records = (await store.inventory()).records;
    expect(records.find(({ pair: value }) => value.appBuildId === first.appBuildId)?.state).toBe("cleanup-pending");
    expect(records.find(({ pair: value }) => value.appBuildId === second.appBuildId)?.state).toBe("previous");
    expect(records.find(({ pair: value }) => value.appBuildId === third.appBuildId)?.state).toBe("active");
    expect(records.filter(({ state }) => state === "active" || state === "previous")
      .every(({ acceptedIdentity }) => Object.values(acceptedIdentity).every(Boolean))).toBe(true);
  });

  it("reports malformed lifecycle state as corrupt and blocks deletion under unknown authority", async () => {
    const target = pair();
    await store.stage(target);
    const database = await openDatabase(factory, OFFLINE_LIFECYCLE_DATABASE);
    const transaction = database.transaction(OFFLINE_LIFECYCLE_STORE, "readwrite");
    transaction.objectStore(OFFLINE_LIFECYCLE_STORE).put({
      key: cacheNamespaces(target).pairKey,
      record: { contractVersion: 1, pair: target, state: "staging", acceptedIdentity: {
        precacheSetSha256: null, resourcePlanSha256: null, receiptSha256: null,
      }, lastFailure: null, query: "must-not-persist" },
    });
    await transactionDone(transaction);
    database.close();

    await expect(store.read(target)).resolves.toMatchObject({ status: "corrupt" });
    await expect(store.inventory()).resolves.toMatchObject({ corruptRecordCount: 1, records: [] });
    await expect(store.markCorrupt(target)).resolves.toMatchObject({ state: "corrupt", lastFailure: "corrupt-record" });
    await store.markCleanupPending(target);
    await expect(store.removeExactPair(target, [{ clientId: "client-safe", state: "inactive" }]))
      .resolves.toMatchObject({ state: "removed" });
  });

  it("enumerates only exact pair Cache Storage, range, receipt, and lease records", async () => {
    const target = pair();
    const namespaces = cacheNamespaces(target);
    caches.seed(namespaces.shell, "https://static.example/index.html");
    caches.seed(namespaces.release, "https://static.example/releases/release-a/manifest.json");
    caches.seed(`${namespaces.release}:staging:operation-1`, "https://static.example/staged");
    caches.seed(cacheNamespaces(pair("build-z", "release-z")).release, "https://static.example/other");
    await seedRangeDatabase(factory, target, { leaseExpiresAt: 900 });
    await seedReceiptDatabase(factory, target);

    await expect(store.storageInventory(target)).resolves.toEqual({
      contractVersion: 1,
      pair: target,
      cacheNames: [namespaces.release, `${namespaces.release}:staging:operation-1`, namespaces.shell].sort(),
      cacheRequestCount: 3,
      rangeRecordCount: 1,
      rangeBytes: 4,
      receiptRecordCount: 1,
      receiptSha256: [C],
      leaseRecordCount: 1,
      protectedByRangeAuthority: false,
    });
  });

  it.each(["active", "unknown", "unresponsive"] as const)(
    "blocks cleanup for a %s client observation",
    async (state) => {
      const target = pair();
      await store.stage(target);
      await store.markCleanupPending(target);
      await expect(store.removeExactPair(target, [{ clientId: "client-1", state }]))
        .rejects.toMatchObject({ code: "CleanupBlocked" });
      await expect(store.read(target)).resolves.toMatchObject({ status: "found", record: { state: "cleanup-pending" } });
    },
  );

  it("blocks cleanup for a target-pair unexpired stored lease or protected range authority", async () => {
    const target = pair();
    await store.stage(target);
    await store.markCleanupPending(target);
    await seedRangeDatabase(factory, target, {
      leaseExpiresAt: 2_000,
      otherLease: { pair: pair("build-z", "release-z"), expiresAt: 2_000 },
    });
    await expect(store.removeExactPair(target)).rejects.toMatchObject({ code: "CleanupBlocked" });

    const protectedFactory = new IDBFactory();
    const protectedStore = new PairLifecycleStore({ indexedDB: protectedFactory, cacheStorage: caches, locks, now: () => 3_000 });
    await protectedStore.stage(target);
    await protectedStore.markCleanupPending(target);
    await seedRangeDatabase(protectedFactory, target, { leaseExpiresAt: 900, protectedAs: "previous" });
    await expect(protectedStore.removeExactPair(target)).rejects.toMatchObject({ code: "CleanupBlocked" });
  });

  it("ignores another pair's live lease after the target pair lease expires", async () => {
    const target = pair();
    await store.stage(target);
    await store.markCleanupPending(target);
    await seedRangeDatabase(factory, target, {
      leaseExpiresAt: 900,
      otherLease: { pair: pair("build-live", "release-live"), expiresAt: 2_000 },
    });

    await expect(store.removeExactPair(target)).resolves.toMatchObject({ state: "removed" });
    const other = await store.storageInventory(pair("build-live", "release-live"));
    expect(other.leaseRecordCount).toBe(1);
  });

  it("preserves existing data when a lease is acquired after the caller's initial observation", async () => {
    const target = pair();
    await makeComplete(store, target);
    await store.markCleanupPending(target);
    const namespaces = cacheNamespaces(target);
    caches.seed(namespaces.shell, "https://static.example/index.html");
    await seedRangeDatabase(factory, target, { leaseExpiresAt: 900 });
    await seedReceiptDatabase(factory, target);

    let cleanupReachedLock!: () => void;
    let continueCleanup!: () => void;
    const reachedLock = new Promise<void>((resolve) => { cleanupReachedLock = resolve; });
    const continueGate = new Promise<void>((resolve) => { continueCleanup = resolve; });
    locks.beforeOperation = async () => {
      locks.beforeOperation = null;
      cleanupReachedLock();
      await continueGate;
    };

    const cleanup = store.removeExactPair(target, [{ clientId: "initially-inactive", state: "inactive" }]);
    await reachedLock;
    await putLease(factory, target, "late-live-client", 2_000);
    continueCleanup();

    await expect(cleanup).rejects.toMatchObject({ code: "CleanupBlocked" });
    await expect(store.read(target)).resolves.toMatchObject({ status: "found", record: { state: "cleanup-pending" } });
    await expect(store.storageInventory(target)).resolves.toMatchObject({
      cacheNames: [namespaces.shell], rangeRecordCount: 1, receiptRecordCount: 1, leaseRecordCount: 2,
    });
  });

  it("serializes racing admission behind cleanup and leaves no orphaned receipt or range bytes", async () => {
    const target = pair();
    await makeComplete(store, target);
    await store.markCleanupPending(target);
    const namespaces = cacheNamespaces(target);
    caches.seed(namespaces.shell, "https://static.example/index.html");
    await seedRangeDatabase(factory, target, { leaseExpiresAt: 900 });
    await seedReceiptDatabase(factory, target);

    let cleanupReachedDeletion!: () => void;
    let continueCleanup!: () => void;
    const reachedDeletion = new Promise<void>((resolve) => { cleanupReachedDeletion = resolve; });
    const continueGate = new Promise<void>((resolve) => { continueCleanup = resolve; });
    caches.onDelete = async () => {
      caches.onDelete = null;
      cleanupReachedDeletion();
      await continueGate;
    };

    const cleanup = store.removeExactPair(target, [{ clientId: "closed-client", state: "inactive" }]);
    await reachedDeletion;
    const signal = new AbortController().signal;
    const racingAdmission = locks.request(
      pairAdmissionLockName(target),
      { mode: "exclusive", signal },
      async () => publishSyntheticAdmission(factory, target),
    );
    continueCleanup();

    await expect(cleanup).resolves.toMatchObject({ state: "removed" });
    await expect(racingAdmission).rejects.toMatchObject({ code: "CleanupPending" });
    await expect(store.storageInventory(target)).resolves.toMatchObject({
      cacheNames: [], rangeRecordCount: 0, receiptRecordCount: 0, leaseRecordCount: 0,
    });
  });

  it("deletes exact receipt authority before caches and ranges, then removes lifecycle last", async () => {
    const target = pair();
    await makeComplete(store, target);
    await store.markCleanupPending(target);
    const namespaces = cacheNamespaces(target);
    caches.seed(namespaces.shell, "https://static.example/index.html");
    caches.seed(namespaces.release, "https://static.example/releases/release-a/manifest.json");
    await seedRangeDatabase(factory, target, { leaseExpiresAt: 900 });
    await seedReceiptDatabase(factory, target);

    const events: string[] = [];
    caches.onDelete = (name) => { events.push(`cache:${name}`); };
    const originalDelete = IDBObjectStore.prototype.delete;
    vi.spyOn(IDBObjectStore.prototype, "delete").mockImplementation(function (this: IDBObjectStore, key) {
      events.push(`idb:${this.name}`);
      return originalDelete.call(this, key);
    });
    const result = await store.removeExactPair(target, [{ clientId: "closed-client", state: "inactive" }]);

    expect(result).toMatchObject({
      state: "removed",
      removed: { receiptRecords: 1, authorityRecords: 1, cacheNamespaces: 2, rangeRecords: 1 },
    });
    expect(await store.read(target)).toEqual({ status: "missing" });
    const receipt = events.indexOf("idb:accepted-receipts");
    const lease = events.indexOf("idb:leases");
    const cache = events.findIndex((event) => event.startsWith("cache:"));
    const range = events.indexOf("idb:ranges");
    const lifecycle = events.indexOf(`idb:${OFFLINE_LIFECYCLE_STORE}`);
    expect(receipt).toBeGreaterThanOrEqual(0);
    expect(lease).toBeGreaterThanOrEqual(0);
    expect(cache).toBeGreaterThan(receipt);
    expect(cache).toBeGreaterThan(lease);
    expect(range).toBeGreaterThan(cache);
    expect(range).toBeGreaterThan(receipt);
    expect(range).toBeGreaterThan(lease);
    expect(lifecycle).toBeGreaterThan(range);
    expect(await store.storageInventory(target)).toMatchObject({
      cacheNames: [], rangeRecordCount: 0, receiptRecordCount: 0, leaseRecordCount: 0,
    });
    const other = await store.storageInventory(pair("build-z", "release-z"));
    expect(other.rangeRecordCount).toBe(1);
    expect(other.receiptRecordCount).toBe(1);
  });

  it("keeps cleanup retryable with failure state when physical deletion fails", async () => {
    const target = pair();
    await makeComplete(store, target);
    await store.markCleanupPending(target);
    caches.seed(cacheNamespaces(target).shell, "https://static.example/index.html");
    await seedReceiptDatabase(factory, target);
    caches.failDelete = true;

    await expect(store.removeExactPair(target)).rejects.toBeInstanceOf(PairLifecycleStoreError);
    await expect(store.read(target)).resolves.toMatchObject({
      status: "found", record: { state: "cleanup-pending", lastFailure: "cleanup-failed" },
    });
    caches.failDelete = false;
    await expect(store.removeExactPair(target)).resolves.toMatchObject({ state: "removed" });
  });
});
