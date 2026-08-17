/* Service-worker-exclusive authority. Keep this module out of the window graph. */

export const SERVICE_WORKER_AUTHORITY_PROTOCOL = "searise-offline-worker-v1" as const;
export const SERVICE_WORKER_RANGE_DATABASE = "searise-offline:v1" as const;
export const SERVICE_WORKER_RANGE_DATABASE_VERSION = 4 as const;
export const SERVICE_WORKER_LEASE_TTL_MS = 120_000 as const;
export const SERVICE_WORKER_CENSUS_TIMEOUT_MS = 5_000 as const;

const STORES = Object.freeze({
  meta: "range-meta",
  ranges: "ranges",
  leases: "leases",
  cleanupFences: "cleanup-fences",
});
const AUTHORITY_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;

interface Pair {
  readonly contractVersion: 1;
  readonly appBuildId: string;
  readonly dataReleaseId: string;
}
interface LeaseRecord {
  readonly key: string;
  readonly leaseId: string;
  readonly pairKey: string;
  readonly pair: Pair;
  readonly sourceClientId: string;
  readonly expiresAtEpochMs: number;
}
interface MetaRecord {
  readonly key: "state";
  rangeBytes: number;
  rangeEntries: number;
  nextSequence: number;
  activePair: Pair | null;
  previousPair: Pair | null;
}
interface SourceClientLike { readonly id: string; readonly type: string }
interface CensusClientLike extends SourceClientLike {
  postMessage(message: unknown, transfer: Transferable[]): void;
}
interface ClientsLike {
  matchAll(options: Readonly<{ type: "window"; includeUncontrolled: true }>): Promise<readonly CensusClientLike[]>;
}
interface AuthorityDependencies {
  readonly indexedDB: IDBFactory;
  readonly clients: ClientsLike;
  readonly now?: () => number;
  readonly randomUUID?: () => string;
  readonly createChannel?: () => MessageChannel;
  readonly setTimer?: (callback: () => void, milliseconds: number) => number;
  readonly clearTimer?: (id: number) => void;
}

function exactRecord(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError("Worker authority message is invalid.");
  const record = value as Record<string, unknown>;
  const expected = new Set(keys);
  if (Object.keys(record).length !== expected.size || Object.keys(record).some((key) => !expected.has(key))) {
    throw new TypeError("Worker authority message has missing or additional fields.");
  }
  return record;
}
function protocolId(value: unknown): string {
  if (typeof value !== "string" || !AUTHORITY_ID.test(value)) throw new TypeError("Worker authority identity is invalid.");
  return value;
}
function pair(value: unknown): Pair {
  const record = exactRecord(value, ["contractVersion", "appBuildId", "dataReleaseId"]);
  if (record.contractVersion !== 1) throw new TypeError("Worker authority pair version is invalid.");
  return Object.freeze({ contractVersion: 1, appBuildId: protocolId(record.appBuildId), dataReleaseId: protocolId(record.dataReleaseId) });
}
function samePair(left: Pair, right: Pair): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}
function pairKey(value: Pair): string { return `${value.appBuildId}::${value.dataReleaseId}`; }
function leaseKey(value: Pair, leaseId: string): string { return JSON.stringify([pairKey(value), leaseId]); }
function request<T>(input: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    input.onsuccess = () => resolve(input.result);
    input.onerror = () => reject(input.error);
  });
}
function completed(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = transaction.onerror = () => reject(transaction.error ?? new DOMException("Worker authority transaction aborted.", "AbortError"));
  });
}

function openDatabase(indexedDB: IDBFactory): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const opened = indexedDB.open(SERVICE_WORKER_RANGE_DATABASE, SERVICE_WORKER_RANGE_DATABASE_VERSION);
    opened.onupgradeneeded = (event) => {
      const database = opened.result;
      if (!database.objectStoreNames.contains(STORES.meta)) database.createObjectStore(STORES.meta, { keyPath: "key" });
      if (!database.objectStoreNames.contains(STORES.ranges)) {
        const ranges = database.createObjectStore(STORES.ranges, { keyPath: "key" });
        ranges.createIndex("by-pair", "pairKey");
        ranges.createIndex("by-lru", ["lastAccessSequence", "key"], { unique: true });
      }
      if (event.oldVersion < 2 && database.objectStoreNames.contains(STORES.leases)) {
        database.deleteObjectStore(STORES.leases);
      }
      if (!database.objectStoreNames.contains(STORES.leases)) {
        const leases = database.createObjectStore(STORES.leases, { keyPath: "key" });
        leases.createIndex("by-pair", "pairKey");
        leases.createIndex("by-expiry", ["expiresAtEpochMs", "pairKey", "leaseId"], { unique: true });
      }
      const leases = opened.transaction!.objectStore(STORES.leases);
      if (!leases.indexNames.contains("by-pair-source")) leases.createIndex("by-pair-source", ["pairKey", "sourceClientId"], { unique: true });
      if (!leases.indexNames.contains("by-source")) leases.createIndex("by-source", "sourceClientId");
      if (!database.objectStoreNames.contains(STORES.cleanupFences)) database.createObjectStore(STORES.cleanupFences, { keyPath: "pairKey" });
      void event;
    };
    opened.onsuccess = () => { opened.result.onversionchange = () => opened.result.close(); resolve(opened.result); };
    opened.onerror = () => reject(opened.error ?? new TypeError("Worker authority database open failed."));
    opened.onblocked = () => reject(new TypeError("Worker authority database open was blocked."));
  });
}

function initialMeta(): MetaRecord {
  return { key: "state", rangeBytes: 0, rangeEntries: 0, nextSequence: 0, activePair: null, previousPair: null };
}

function liveRecord(value: unknown, expectedSource: string, now: number): LeaseRecord | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Partial<LeaseRecord>;
  try {
    const validatedPair = pair(record.pair);
    if (record.sourceClientId !== expectedSource || typeof record.leaseId !== "string" ||
        !AUTHORITY_ID.test(record.leaseId) || record.pairKey !== pairKey(validatedPair) ||
        record.key !== leaseKey(validatedPair, record.leaseId) || !Number.isSafeInteger(record.expiresAtEpochMs) ||
        Number(record.expiresAtEpochMs) <= now) return null;
    return Object.freeze({ ...record, pair: validatedPair } as LeaseRecord);
  } catch { return null; }
}

export function createServiceWorkerClientAuthority(expectedPairInput: Pair, dependencies: AuthorityDependencies) {
  const expectedPair = pair(expectedPairInput);
  const now = dependencies.now ?? Date.now;
  const randomUUID = dependencies.randomUUID ?? (() => crypto.randomUUID());
  const createChannel = dependencies.createChannel ?? (() => new MessageChannel());
  const setTimer = dependencies.setTimer ?? ((callback, milliseconds) => globalThis.setTimeout(callback, milliseconds) as unknown as number);
  const clearTimer = dependencies.clearTimer ?? ((id) => globalThis.clearTimeout(id));

  const exactNow = (): number => {
    const value = now();
    if (!Number.isSafeInteger(value) || value < 0 || value > Number.MAX_SAFE_INTEGER - SERVICE_WORKER_LEASE_TTL_MS) {
      throw new TypeError("Worker lease clock is invalid.");
    }
    return value;
  };

  const activate = async (sourceClientId: string, leaseId: string): Promise<LeaseRecord> => {
    const timestamp = exactNow();
    const database = await openDatabase(dependencies.indexedDB);
    try {
      const tx = database.transaction([STORES.meta, STORES.leases, STORES.cleanupFences], "readwrite");
      const done = completed(tx);
      const targetKey = pairKey(expectedPair);
      if (await request(tx.objectStore(STORES.cleanupFences).get(targetKey)) !== undefined) {
        tx.abort(); await done.catch(() => undefined); throw new TypeError("cleanup-pending");
      }
      const leaseStore = tx.objectStore(STORES.leases);
      const existing = await request(leaseStore.index("by-pair-source").get([targetKey, sourceClientId])) as unknown;
      const live = liveRecord(existing, sourceClientId, timestamp);
      if (existing && (!live || live.leaseId !== leaseId)) {
        if (live) { tx.abort(); await done.catch(() => undefined); throw new TypeError("lease-mismatch"); }
        leaseStore.delete((existing as { key: IDBValidKey }).key);
      }
      const record: LeaseRecord = Object.freeze({
        key: leaseKey(expectedPair, leaseId), leaseId, pairKey: targetKey, pair: expectedPair,
        sourceClientId, expiresAtEpochMs: timestamp + SERVICE_WORKER_LEASE_TTL_MS,
      });
      const metaStore = tx.objectStore(STORES.meta);
      const meta = (await request(metaStore.get("state")) as MetaRecord | undefined) ?? initialMeta();
      if (!meta.activePair || !samePair(pair(meta.activePair), expectedPair)) {
        meta.previousPair = meta.activePair;
        meta.activePair = expectedPair;
      }
      metaStore.put(meta);
      leaseStore.put(record);
      await done;
      return record;
    } finally { database.close(); }
  };

  const renew = async (sourceClientId: string, leaseId: string): Promise<LeaseRecord> => {
    const timestamp = exactNow();
    const database = await openDatabase(dependencies.indexedDB);
    try {
      const tx = database.transaction([STORES.leases, STORES.cleanupFences], "readwrite");
      const done = completed(tx);
      const targetKey = pairKey(expectedPair);
      if (await request(tx.objectStore(STORES.cleanupFences).get(targetKey)) !== undefined) {
        tx.abort(); await done.catch(() => undefined); throw new TypeError("cleanup-pending");
      }
      const store = tx.objectStore(STORES.leases);
      const existing = liveRecord(await request(store.get(leaseKey(expectedPair, leaseId))), sourceClientId, timestamp);
      if (!existing) { tx.abort(); await done.catch(() => undefined); throw new TypeError("lease-mismatch"); }
      const record = Object.freeze({ ...existing, expiresAtEpochMs: timestamp + SERVICE_WORKER_LEASE_TTL_MS });
      store.put(record);
      await done;
      return record;
    } finally { database.close(); }
  };

  const release = async (sourceClientId: string, leaseId: string): Promise<void> => {
    const database = await openDatabase(dependencies.indexedDB);
    try {
      const tx = database.transaction(STORES.leases, "readwrite");
      const done = completed(tx);
      const store = tx.objectStore(STORES.leases);
      const key = leaseKey(expectedPair, leaseId);
      const existing = await request(store.get(key)) as LeaseRecord | undefined;
      if (existing && existing.sourceClientId !== sourceClientId) {
        tx.abort(); await done.catch(() => undefined); throw new TypeError("lease-mismatch");
      }
      store.delete(key);
      await done;
    } finally { database.close(); }
  };

  const leasesForSource = async (sourceClientId: string): Promise<readonly LeaseRecord[]> => {
    const timestamp = exactNow();
    const database = await openDatabase(dependencies.indexedDB);
    try {
      const tx = database.transaction(STORES.leases, "readonly");
      const done = completed(tx);
      const values = await request(tx.objectStore(STORES.leases).index("by-source").getAll(sourceClientId)) as unknown[];
      await done;
      return Object.freeze(values.flatMap((value) => {
        const live = liveRecord(value, sourceClientId, timestamp);
        return live ? [live] : [];
      }));
    } finally { database.close(); }
  };

  const challenge = async (client: CensusClientLike, targetPair: Pair): Promise<Readonly<{ clientId: string; state: "inactive" | "active" | "unknown" | "unresponsive" }>> => {
    const messageToken = `challenge-${randomUUID()}`;
    const channel = createChannel();
    let response: unknown;
    try {
      response = await new Promise<unknown>((resolve) => {
        let settled = false;
        const finish = (value: unknown): void => {
          if (settled) return;
          settled = true;
          clearTimer(timeout);
          channel.port1.close();
          resolve(value);
        };
        const timeout = setTimer(() => finish(undefined), SERVICE_WORKER_CENSUS_TIMEOUT_MS);
        channel.port1.onmessage = ({ data }) => finish(data);
        try {
          client.postMessage({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "lease-challenge", messageToken, targetPair }, [channel.port2]);
        } catch { finish(undefined); }
      });
    } finally { channel.port1.close(); }
    if (response === undefined) return Object.freeze({ clientId: client.id, state: "unresponsive" as const });
    let record: Record<string, unknown>;
    try {
      record = response && typeof response === "object" && !Array.isArray(response)
        ? response as Record<string, unknown> : (() => { throw new TypeError(); })();
      if (record.protocol !== SERVICE_WORKER_AUTHORITY_PROTOCOL || record.type !== "lease-challenge-response" ||
          record.messageToken !== messageToken) throw new TypeError();
      const leases = await leasesForSource(client.id);
      if (record.state === "inactive" && Object.keys(record).length === 4) {
        return Object.freeze({ clientId: client.id, state: leases.some(({ pair: value }) => samePair(value, targetPair)) ? "unknown" as const : "inactive" as const });
      }
      const claimedPair = pair(record.pair);
      const leaseId = protocolId(record.leaseId);
      if (record.state !== "active" || Object.keys(record).length !== 6 ||
          !leases.some((lease) => lease.leaseId === leaseId && samePair(lease.pair, claimedPair))) throw new TypeError();
      return Object.freeze({ clientId: client.id, state: samePair(claimedPair, targetPair) ? "active" as const : "inactive" as const });
    } catch { return Object.freeze({ clientId: client.id, state: "unknown" as const }); }
  };

  const census = async (sourceClientId: string, targetPair: Pair) => {
    const requester = await leasesForSource(sourceClientId);
    if (!requester.some(({ pair: value }) => samePair(value, expectedPair))) throw new TypeError("requester-unleased");
    let before: readonly CensusClientLike[];
    try { before = await dependencies.clients.matchAll({ type: "window", includeUncontrolled: true }); }
    catch { throw new TypeError("client-enumeration-failed"); }
    const ids = before.map(({ id }) => protocolId(id));
    if (new Set(ids).size !== ids.length) throw new TypeError("client-enumeration-failed");
    const observations = await Promise.all(before.map((client) => challenge(client, targetPair)));
    let after: readonly CensusClientLike[];
    try { after = await dependencies.clients.matchAll({ type: "window", includeUncontrolled: true }); }
    catch { throw new TypeError("client-enumeration-failed"); }
    const afterIds = after.map(({ id }) => protocolId(id));
    if (new Set(afterIds).size !== afterIds.length || afterIds.length !== ids.length ||
        afterIds.some((id) => !ids.includes(id)) || ids.some((id) => !afterIds.includes(id))) {
      throw new TypeError("client-set-changed");
    }
    return Object.freeze(observations.sort((left, right) => left.clientId.localeCompare(right.clientId)));
  };

  const refusal = (messageToken: string, error: unknown, kind: "lease" | "census") => {
    const code = error instanceof Error ? error.message : "storage-failed";
    if (kind === "lease") {
      const reason = ["cleanup-pending", "lease-mismatch"].includes(code) ? code : "storage-failed";
      return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "lease-refused", messageToken, reason });
    }
    const reason = ["requester-unleased", "client-enumeration-failed", "client-set-changed"].includes(code)
      ? code : "client-unknown";
    return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "census-refused", messageToken, reason });
  };

  return Object.freeze({
    async message(value: unknown, source: SourceClientLike | null, portCount: number): Promise<unknown | undefined> {
      if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
      const raw = value as Record<string, unknown>;
      if (raw.protocol !== SERVICE_WORKER_AUTHORITY_PROTOCOL ||
          !["acquire-lease", "heartbeat-lease", "release-lease", "request-client-census"].includes(String(raw.type))) return undefined;
      let messageToken: string;
      try { messageToken = protocolId(raw.messageToken); } catch { return undefined; }
      if (!source || source.type !== "window" || !AUTHORITY_ID.test(source.id) || portCount !== 1) {
        return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: raw.type === "request-client-census" ? "census-refused" : "lease-refused", messageToken, reason: "source-unavailable" });
      }
      if (raw.type === "request-client-census") {
        try {
          const record = exactRecord(value, ["protocol", "type", "messageToken", "targetPair"]);
          const targetPair = pair(record.targetPair);
          const observations = await census(source.id, targetPair);
          return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "client-census", messageToken, targetPair, observations });
        } catch (error) { return refusal(messageToken, error, "census"); }
      }
      try {
        const record = exactRecord(value, ["protocol", "type", "messageToken", "leaseId", "pair"]);
        const requestedPair = pair(record.pair);
        if (!samePair(requestedPair, expectedPair)) return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "lease-refused", messageToken, reason: "pair-mismatch" });
        const leaseId = protocolId(record.leaseId);
        if (raw.type === "release-lease") {
          await release(source.id, leaseId);
          return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "lease-released", messageToken, pair: expectedPair, leaseId });
        }
        const lease = raw.type === "acquire-lease" ? await activate(source.id, leaseId) : await renew(source.id, leaseId);
        return Object.freeze({ protocol: SERVICE_WORKER_AUTHORITY_PROTOCOL, type: "lease-state", messageToken, lease: {
          contractVersion: 1, leaseId: lease.leaseId, pair: lease.pair,
          expiresAtEpochMs: lease.expiresAtEpochMs, state: "active",
        } });
      } catch (error) { return refusal(messageToken, error, "lease"); }
    },
  });
}
