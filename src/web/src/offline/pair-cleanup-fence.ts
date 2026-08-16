import { cacheNamespaces, validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";

export const OFFLINE_RANGE_DATABASE = "searise-offline:v1" as const;
export const OFFLINE_RANGE_DATABASE_VERSION = 3 as const;
export const OFFLINE_RANGE_STORES = {
  meta: "range-meta",
  ranges: "ranges",
  leases: "leases",
  cleanupFences: "cleanup-fences",
} as const;

interface StoredCleanupFenceV1 {
  readonly pairKey: string;
  readonly pair: AppReleasePairV1;
  readonly state: "cleanup-pending";
  readonly createdAtEpochMs: number;
}

interface StoredLeaseAuthority {
  readonly pairKey?: unknown;
  readonly expiresAtEpochMs?: unknown;
}

export interface PairCleanupLockPort {
  request<T>(
    name: string,
    options: Readonly<{ mode: "exclusive"; signal: AbortSignal }>,
    operation: () => Promise<T>,
  ): Promise<T>;
}

export class PairCleanupFenceError extends Error {
  readonly code: "CleanupBlocked" | "CleanupPending" | "StorageFailed";

  constructor(code: PairCleanupFenceError["code"], message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "PairCleanupFenceError";
    this.code = code;
  }
}

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
      transaction.error ?? new DOMException("Range authority transaction aborted.", "AbortError"),
    );
  });
}

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}

export function pairAdmissionLockName(pairInput: AppReleasePairV1): string {
  const pair = validateAppReleasePair(pairInput);
  return `searise-offline:admission:${cacheNamespaces(pair).pairKey}`;
}

export function openOfflineRangeDatabase(indexedDB: IDBFactory): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(OFFLINE_RANGE_DATABASE, OFFLINE_RANGE_DATABASE_VERSION);
    open.onupgradeneeded = (event) => {
      const database = open.result;
      if (!database.objectStoreNames.contains(OFFLINE_RANGE_STORES.meta)) {
        database.createObjectStore(OFFLINE_RANGE_STORES.meta, { keyPath: "key" });
      }
      if (!database.objectStoreNames.contains(OFFLINE_RANGE_STORES.ranges)) {
        const ranges = database.createObjectStore(OFFLINE_RANGE_STORES.ranges, { keyPath: "key" });
        ranges.createIndex("by-pair", "pairKey");
        ranges.createIndex("by-lru", ["lastAccessSequence", "key"], { unique: true });
      }
      // Version 2 replaced the legacy leaseId-only key. Never recreate the
      // current store during the v2 -> v3 cleanup-fence migration.
      if (event.oldVersion < 2 && database.objectStoreNames.contains(OFFLINE_RANGE_STORES.leases)) {
        database.deleteObjectStore(OFFLINE_RANGE_STORES.leases);
      }
      if (!database.objectStoreNames.contains(OFFLINE_RANGE_STORES.leases)) {
        const leases = database.createObjectStore(OFFLINE_RANGE_STORES.leases, { keyPath: "key" });
        leases.createIndex("by-pair", "pairKey");
        leases.createIndex("by-expiry", ["expiresAtEpochMs", "pairKey", "leaseId"], { unique: true });
      }
      if (!database.objectStoreNames.contains(OFFLINE_RANGE_STORES.cleanupFences)) {
        database.createObjectStore(OFFLINE_RANGE_STORES.cleanupFences, { keyPath: "pairKey" });
      }
    };
    open.onsuccess = () => {
      open.result.onversionchange = () => open.result.close();
      resolve(open.result);
    };
    open.onerror = () => reject(open.error ?? new PairCleanupFenceError(
      "StorageFailed", "Range authority database open failed.",
    ));
    open.onblocked = () => reject(new PairCleanupFenceError(
      "StorageFailed", "Range authority database open was blocked.",
    ));
  });
}

export async function assertPairAdmissionOpen(
  indexedDB: IDBFactory,
  pairInput: AppReleasePairV1,
): Promise<void> {
  const pair = validateAppReleasePair(pairInput);
  const key = cacheNamespaces(pair).pairKey;
  const database = await openOfflineRangeDatabase(indexedDB);
  try {
    const transaction = database.transaction(OFFLINE_RANGE_STORES.cleanupFences, "readonly");
    const done = completed(transaction);
    const fence = await request(transaction.objectStore(OFFLINE_RANGE_STORES.cleanupFences).get(key));
    await done;
    if (fence !== undefined) {
      throw new PairCleanupFenceError("CleanupPending", "Exact-pair cleanup is pending; new admission is refused.");
    }
  } finally {
    database.close();
  }
}

/**
 * Atomically refuses unsafe cleanup or publishes the fail-closed exact-pair
 * tombstone. Once published, it intentionally survives successful cleanup so
 * a stale client cannot recreate accepted state for a removed pair.
 */
export async function beginPairCleanupFence(
  indexedDB: IDBFactory,
  pairInput: AppReleasePairV1,
  now: () => number,
): Promise<void> {
  const pair = validateAppReleasePair(pairInput);
  const key = cacheNamespaces(pair).pairKey;
  const database = await openOfflineRangeDatabase(indexedDB);
  const transaction = database.transaction([
    OFFLINE_RANGE_STORES.meta,
    OFFLINE_RANGE_STORES.leases,
    OFFLINE_RANGE_STORES.cleanupFences,
  ], "readwrite");
  const done = completed(transaction);
  try {
    const meta = await request(transaction.objectStore(OFFLINE_RANGE_STORES.meta).get("state")) as
      | Readonly<{ activePair?: unknown; previousPair?: unknown }>
      | undefined;
    for (const candidate of [meta?.activePair, meta?.previousPair]) {
      if (candidate === null || candidate === undefined) continue;
      try {
        if (samePair(validateAppReleasePair(candidate), pair)) {
          throw new PairCleanupFenceError(
            "CleanupBlocked", "Range authority still protects this pair as active or previous.",
          );
        }
      } catch (error) {
        if (error instanceof PairCleanupFenceError) throw error;
        throw new PairCleanupFenceError("CleanupBlocked", "Unknown protected range authority blocks cleanup.", error);
      }
    }

    const leases = await request(transaction.objectStore(OFFLINE_RANGE_STORES.leases).getAll()) as StoredLeaseAuthority[];
    const observedAt = now();
    const unsafeLease = leases.some((lease) => {
      if (typeof lease.pairKey !== "string") return true;
      if (lease.pairKey !== key) return false;
      return !Number.isSafeInteger(lease.expiresAtEpochMs) || Number(lease.expiresAtEpochMs) > observedAt;
    });
    if (unsafeLease) {
      throw new PairCleanupFenceError(
        "CleanupBlocked", "An active or unknown client lease blocks exact-pair cleanup.",
      );
    }

    const fences = transaction.objectStore(OFFLINE_RANGE_STORES.cleanupFences);
    if (await request(fences.get(key)) === undefined) {
      fences.add({ pairKey: key, pair, state: "cleanup-pending", createdAtEpochMs: observedAt } satisfies StoredCleanupFenceV1);
    }
    await done;
  } catch (error) {
    try { transaction.abort(); } catch { /* Transaction already completed or aborted. */ }
    await done.catch(() => undefined);
    if (error instanceof PairCleanupFenceError) throw error;
    throw new PairCleanupFenceError("StorageFailed", "Exact-pair cleanup fence could not be established.", error);
  } finally {
    database.close();
  }
}
