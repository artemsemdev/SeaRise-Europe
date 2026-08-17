// @vitest-environment node

import { webcrypto } from "node:crypto";
import { IDBFactory, IDBObjectStore } from "fake-indexeddb";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OfflineContractError, validateAppAuthority, validateRangeIdentity, type RangeIdentityV1 } from "./contracts/v1";
import { validateStorageBudget } from "./contracts/policy";
import { cacheNamespaces, validateAppReleasePair } from "./contracts/keys";
import {
  RangeStoreIntegrityError,
  RangeStoreAbortedError,
  RangeStoreQuotaError,
  RangeStoreUnsupportedError,
  createRangeAuthorityCatalog,
  createRangeStore,
} from "./range-store";
import { beginPairCleanupFence } from "./pair-cleanup-fence";

const A = "a".repeat(64);
const C = "c".repeat(64);
const CANONICAL_PROJECTIONS = [
  ["ssp1-26", "2030"], ["ssp1-26", "2050"], ["ssp1-26", "2100"],
  ["ssp2-45", "2030"], ["ssp2-45", "2050"], ["ssp2-45", "2100"],
  ["ssp5-85", "2030"], ["ssp5-85", "2050"], ["ssp5-85", "2100"],
] as const;
const subtle = webcrypto.subtle as SubtleCrypto;
const bytes = (...values: number[]) => Uint8Array.from(values).buffer;
async function hash(value: ArrayBuffer): Promise<string> {
  return Buffer.from(await subtle.digest("SHA-256", value)).toString("hex");
}
const budget = (maxRangeBytes = 12, maxRangeEntries = 3) => validateStorageBudget({
  contractVersion: 1, policyId: "range-store-test", maxTotalBytes: maxRangeBytes + 10,
  maxWholeResourceBytes: 10, maxRangeBytes, maxWholeEntries: 2, maxRangeEntries,
  highWatermarkBytes: maxRangeBytes + 9, lowWatermarkBytes: maxRangeBytes + 8,
  minQuotaReserveBytes: 0, maxQuotaFraction: 0.25, leaseTtlMs: 120_000,
  heartbeatMs: 30_000, retainedCompletePairs: 2, eviction: "unleased-lru",
});
const pair = (build = "build-a", release = "release-a") => validateAppReleasePair({
  contractVersion: 1, appBuildId: build, dataReleaseId: release,
});
const app = (build = "build-a", release = "release-a", disposition: "synthetic-fixture" | "private-engineering" = "synthetic-fixture") => validateAppAuthority({
  contractVersion: 1, appBuildId: build, dataReleaseId: release,
  manifestUrl: `https://static.example/releases/${release}/manifest.json`,
  releaseDisposition: disposition, precacheSetSha256: A,
});
async function identity(input: {
  build?: string; release?: string;
  projection?: readonly ["ssp1-26" | "ssp2-45" | "ssp5-85", "2030" | "2050" | "2100"];
  start?: number; payload: ArrayBuffer; total?: number;
}): Promise<RangeIdentityV1> {
  const build = input.build ?? "build-a"; const release = input.release ?? "release-a";
  const [scenario, horizon] = input.projection ?? ["ssp2-45", "2050"];
  const start = input.start ?? 0;
  return validateRangeIdentity({
    contractVersion: 1,
    authority: {
      contractVersion: 1, pair: { contractVersion: 1, appBuildId: build, dataReleaseId: release },
      artifactId: `projection-${scenario}-${horizon}-cog`, role: "projection-analysis-cog",
      canonicalUrl: `https://static.example/releases/${release}/analysis/${scenario}/${horizon}.tif`,
      path: `analysis/${scenario}/${horizon}.tif`,
      mediaType: "image/tiff; application=geotiff; profile=cloud-optimized",
      totalByteSize: input.total ?? 12, artifactSha256: C, etag: `"sha256-${C}"`, integrityChunkSize: 4,
    },
    interval: { start, endExclusive: Math.min(start + 4, input.total ?? 12) },
    authorizedIntervalSha256: await hash(input.payload),
  });
}
async function forgedVisualIdentity(input: {
  build?: string; release?: string; payload: ArrayBuffer; relabelAsCog?: boolean;
}): Promise<unknown> {
  const build = input.build ?? "build-a"; const release = input.release ?? "release-a";
  return {
    contractVersion: 1,
    authority: {
      contractVersion: 1, pair: { contractVersion: 1, appBuildId: build, dataReleaseId: release },
      artifactId: "projection-ssp2-45-2050-visual",
      role: input.relabelAsCog ? "projection-analysis-cog" : "projection-visual-pmtiles",
      canonicalUrl: `https://static.example/releases/${release}/visual/ssp2-45/2050.pmtiles`,
      path: "visual/ssp2-45/2050.pmtiles", mediaType: "application/vnd.pmtiles",
      totalByteSize: 12, artifactSha256: C, etag: `"sha256-${C}"`, integrityChunkSize: 4,
    },
    interval: { start: 0, endExclusive: 4 },
    authorizedIntervalSha256: await hash(input.payload),
  };
}
function persistent(factory: IDBFactory, approved: readonly RangeIdentityV1[], authority = app(), maximumBytes = 12, maximumEntries = 3, now = () => 1_000) {
  return createRangeStore(authority, budget(maximumBytes, maximumEntries), { indexedDB: factory, subtle, now }, {
    catalog: createRangeAuthorityCatalog(approved),
  });
}
function memory(approved: readonly RangeIdentityV1[], authority = app(), maximumBytes = 12, maximumEntries = 3, now = () => 1_000) {
  return createRangeStore(authority, budget(maximumBytes, maximumEntries), { subtle, now }, {
    catalog: createRangeAuthorityCatalog(approved), localCandidate: true,
  });
}
function storeFor(mode: "persistent" | "memory-only", factory: IDBFactory, approved: readonly RangeIdentityV1[], maximumBytes = 12, maximumEntries = 3) {
  return mode === "persistent"
    ? persistent(factory, approved, app(), maximumBytes, maximumEntries)
    : memory(approved, app(), maximumBytes, maximumEntries);
}
async function rawRecords(factory: IDBFactory): Promise<Record<string, unknown>[]> {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = factory.open("searise-offline:v1");
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  const records = await new Promise<Record<string, unknown>[]>((resolve, reject) => {
    const request = database.transaction("ranges").objectStore("ranges").getAll();
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  database.close(); return records;
}
async function rawLeaseState(factory: IDBFactory): Promise<{
  keyPath: IDBObjectStore["keyPath"];
  records: Record<string, unknown>[];
}> {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = factory.open("searise-offline:v1");
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  const objectStore = database.transaction("leases").objectStore("leases");
  const keyPath = objectStore.keyPath;
  const records = await new Promise<Record<string, unknown>[]>((resolve, reject) => {
    const request = objectStore.getAll();
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  database.close(); return { keyPath, records };
}
async function seedLegacyRangeStore(
  factory: IDBFactory,
  range: RangeIdentityV1,
  payload: ArrayBuffer,
): Promise<void> {
  const pairKey = cacheNamespaces(range.authority.pair).pairKey;
  const artifactKey = JSON.stringify([
    pairKey,
    range.authority.artifactId,
    range.authority.path,
    range.authority.role,
    range.authority.mediaType,
    range.authority.totalByteSize,
    range.authority.artifactSha256,
    range.authority.integrityChunkSize,
  ]);
  const key = JSON.stringify([
    artifactKey,
    range.interval.start,
    range.interval.endExclusive,
    range.authorizedIntervalSha256,
  ]);
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = factory.open("searise-offline:v1", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("range-meta", { keyPath: "key" }).put({
        key: "state", rangeBytes: payload.byteLength, rangeEntries: 1, nextSequence: 8,
        activePair: range.authority.pair, previousPair: null,
      });
      const ranges = request.result.createObjectStore("ranges", { keyPath: "key" });
      ranges.createIndex("by-pair", "pairKey");
      ranges.createIndex("by-lru", ["lastAccessSequence", "key"], { unique: true });
      ranges.put({
        key, pairKey, artifactKey, pair: range.authority.pair,
        artifactId: range.authority.artifactId, path: range.authority.path,
        role: range.authority.role, mediaType: range.authority.mediaType,
        totalByteSize: range.authority.totalByteSize,
        artifactSha256: range.authority.artifactSha256,
        integrityChunkSize: range.authority.integrityChunkSize,
        start: range.interval.start, endExclusive: range.interval.endExclusive,
        authorizedIntervalSha256: range.authorizedIntervalSha256,
        bytes: payload.slice(0), byteLength: payload.byteLength,
        contentSequence: 7, lastAccessSequence: 7,
      });
      request.result.createObjectStore("leases", { keyPath: "leaseId" }).put({
        leaseId: "shared-lease", pairKey: "legacy", pair: pair(), expiresAtEpochMs: 2_000,
      });
    };
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  database.close();
}

describe("authoritative IndexedDB range store", () => {
  let factory: IDBFactory;
  beforeEach(() => { factory = new IDBFactory(); });

  it("returns exact bytes or a copied slice from one containing authorized chunk", async () => {
    const chunk = bytes(10, 20, 30, 40); const range = await identity({ payload: chunk });
    const store = persistent(factory, [range]);
    await expect(store.putVerified(range, bytes(40, 30, 20, 10))).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.putVerified(range, chunk)).resolves.toBe("stored");
    await expect(store.putVerified(range, chunk)).resolves.toBe("already-present");
    expect([...new Uint8Array((await store.readExactOrContaining(range))!)]).toEqual([10, 20, 30, 40]);
    expect([...new Uint8Array((await store.readExactOrContaining(range, { start: 1, endExclusive: 3 }))!)]).toEqual([20, 30]);
    await expect(store.inventory()).resolves.toMatchObject({
      payloadBytes: 4, entryCount: 1, activePair: null, previousPair: null,
    });
  });

  it("refuses range admission and lease acquisition or renewal after an exact-pair cleanup fence", async () => {
    const firstBytes = bytes(10, 20, 30, 40);
    const secondBytes = bytes(50, 60, 70, 80);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ start: 4, payload: secondBytes });
    const store = persistent(factory, [first, second]);
    await store.putVerified(first, firstBytes);
    await store.acquireLease({
      contractVersion: 1,
      leaseId: "expired-before-cleanup",
      pair: pair(),
      expiresAtEpochMs: 900,
      state: "active",
    });

    await beginPairCleanupFence(factory, pair(), () => 1_000);

    await expect(store.acquireLease({
      contractVersion: 1,
      leaseId: "expired-before-cleanup",
      pair: pair(),
      expiresAtEpochMs: 2_000,
      state: "active",
    })).rejects.toThrow(/cleanup is pending/);
    await expect(store.activateClientLease({
      contractVersion: 1,
      leaseId: "late-activation",
      pair: pair(),
      expiresAtEpochMs: 2_000,
      state: "active",
    })).rejects.toThrow(/cleanup is pending/);
    await expect(store.putVerified(second, secondBytes)).rejects.toThrow(/cleanup is pending/);
    await expect(store.admitVerifiedBatch([{ identity: second, bytes: secondBytes }], {
      operationId: "late-admission",
      signal: new AbortController().signal,
    })).rejects.toThrow(/cleanup is pending/);
    await expect(store.inventory()).resolves.toMatchObject({
      payloadBytes: 4, entryCount: 1, activePair: null, previousPair: null,
    });
    await expect(store.readExactOrContaining(first)).resolves.not.toBeNull();
  });

  it("admits one release-authorized interval for every scenario and horizon combination", async () => {
    const values = CANONICAL_PROJECTIONS.map((_, index) => bytes(index + 1, index + 1, index + 1, index + 1));
    const ranges = await Promise.all(CANONICAL_PROJECTIONS.map((projection, index) => identity({
      projection,
      start: (index % 3) * 4,
      payload: values[index],
    })));
    const store = persistent(factory, ranges, app(), 36, 9);

    await expect(store.putVerifiedBatch(ranges.map((range, index) => ({
      identity: range,
      bytes: values[index],
    })))).resolves.toEqual(Array.from({ length: 9 }, () => "stored"));
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 36, entryCount: 9 });
  });

  it.each(["persistent", "memory-only"] as const)("admits a verified multi-chunk batch atomically in %s mode", async (mode) => {
    const firstBytes = bytes(1, 2, 3, 4); const secondBytes = bytes(5, 6, 7, 8);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ start: 4, payload: secondBytes });
    const store = storeFor(mode, factory, [first, second]);

    await expect(store.putVerifiedBatch([
      { identity: first, bytes: firstBytes }, { identity: second, bytes: secondBytes },
    ])).resolves.toEqual(["stored", "stored"]);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 8, entryCount: 2 });
    expect([...new Uint8Array((await store.readExactOrContaining(second))!)]).toEqual([5, 6, 7, 8]);
  });

  it.each(["persistent", "memory-only"] as const)("rejects one invalid digest before mutating a %s batch", async (mode) => {
    const retainedBytes = bytes(1, 1, 1, 1);
    const retained = await identity({ payload: retainedBytes });
    const validBytes = bytes(2, 2, 2, 2); const valid = await identity({ projection: ["ssp1-26", "2030"], payload: validBytes });
    const expectedBytes = bytes(3, 3, 3, 3); const invalid = await identity({ projection: ["ssp5-85", "2100"], payload: expectedBytes });
    const store = storeFor(mode, factory, [retained, valid, invalid]);
    await store.putVerified(retained, retainedBytes);

    await expect(store.putVerifiedBatch([
      { identity: valid, bytes: validBytes }, { identity: invalid, bytes: bytes(9, 9, 9, 9) },
    ])).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 4, entryCount: 1 });
    await expect(store.readExactOrContaining(valid)).resolves.toBeNull();
  });

  it("aborts every staged write when IndexedDB fails in the middle of a batch", async () => {
    const firstBytes = bytes(1, 2, 3, 4); const secondBytes = bytes(5, 6, 7, 8);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ start: 4, payload: secondBytes });
    const store = persistent(factory, [first, second]);
    const originalPut = IDBObjectStore.prototype.put; let rangeWrites = 0;
    const put = vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (
      this: IDBObjectStore,
      value: unknown,
      key?: IDBValidKey,
    ) {
      if (this.name === "ranges" && ++rangeWrites === 2) {
        throw new DOMException("Injected second range write failure.", "UnknownError");
      }
      return Reflect.apply(originalPut, this, key === undefined ? [value] : [value, key]);
    });
    try {
      await expect(store.putVerifiedBatch([
        { identity: first, bytes: firstBytes }, { identity: second, bytes: secondBytes },
      ])).rejects.toMatchObject({ name: "UnknownError" });
    } finally {
      put.mockRestore();
    }
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0, entries: [] });
    expect(await rawRecords(factory)).toEqual([]);
  });

  it.each(["persistent", "memory-only"] as const)("plans batch quota and deterministic LRU eviction before mutating %s storage", async (mode) => {
    const values = [1, 2, 3, 4, 5].map((value) => bytes(value, value, value, value));
    const ranges = await Promise.all(values.map((payload, index) =>
      identity({ projection: CANONICAL_PROJECTIONS[index], payload })));
    const sixBytes = bytes(6, 6, 6, 6); const sevenBytes = bytes(7, 7, 7, 7);
    const six = await identity({ projection: CANONICAL_PROJECTIONS[6], payload: sixBytes });
    const seven = await identity({ projection: CANONICAL_PROJECTIONS[7], payload: sevenBytes });
    const store = storeFor(mode, factory, [...ranges, six, seven], 12, 3);
    await store.putVerifiedBatch(ranges.slice(0, 3).map((range, index) => ({ identity: range, bytes: values[index] })));

    await expect(store.putVerifiedBatch([
      { identity: ranges[3], bytes: values[3] }, { identity: ranges[4], bytes: values[4] },
    ])).resolves.toEqual(["stored", "stored"]);
    expect((await store.inventory()).entries.map((entry) => entry.artifactId)).toEqual([
      "projection-ssp1-26-2100-cog", "projection-ssp2-45-2030-cog", "projection-ssp2-45-2050-cog",
    ]);

    await store.setProtectedPairs(pair(), null);
    await expect(store.putVerifiedBatch([
      { identity: six, bytes: sixBytes }, { identity: seven, bytes: sevenBytes },
    ])).rejects.toBeInstanceOf(RangeStoreQuotaError);
    expect((await store.inventory()).entries.map((entry) => entry.artifactId)).toEqual([
      "projection-ssp1-26-2100-cog", "projection-ssp2-45-2030-cog", "projection-ssp2-45-2050-cog",
    ]);
  });

  it("never assembles adjacent chunks and isolates every app/release/artifact authority", async () => {
    const first = await identity({ payload: bytes(1, 2, 3, 4) });
    const second = await identity({ start: 4, payload: bytes(5, 6, 7, 8) });
    const otherArtifact = await identity({ projection: ["ssp1-26", "2030"], payload: bytes(1, 2, 3, 4) });
    const store = persistent(factory, [first, second, otherArtifact]);
    await store.putVerified(first, bytes(1, 2, 3, 4)); await store.putVerified(second, bytes(5, 6, 7, 8));
    await expect(store.readExactOrContaining(first, { start: 2, endExclusive: 6 })).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    const otherRelease = await identity({ release: "release-b", payload: bytes(1, 2, 3, 4) });
    await expect(store.readExactOrContaining(otherRelease)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    const otherBuild = await identity({ build: "build-b", payload: bytes(1, 2, 3, 4) });
    await expect(store.readExactOrContaining(otherBuild)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.readExactOrContaining(otherArtifact)).resolves.toBeNull();
  });

  it.each(["persistent", "memory-only"] as const)("rejects visual and relabeled PMTiles with zero %s admission", async (mode) => {
    const value = bytes(1, 2, 3, 4);
    const approved = await identity({ payload: bytes(4, 3, 2, 1) });
    const store = storeFor(mode, factory, [approved]);
    const visual = await forgedVisualIdentity({ payload: value });
    const relabeled = await forgedVisualIdentity({ payload: value, relabelAsCog: true });
    await expect(store.putVerified(visual as RangeIdentityV1, value)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(store.readExactOrContaining(visual as RangeIdentityV1)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(store.putVerified(relabeled as RangeIdentityV1, value)).rejects.toBeInstanceOf(OfflineContractError);
    await expect(store.readExactOrContaining(relabeled as RangeIdentityV1)).rejects.toBeInstanceOf(OfflineContractError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0 });
    if (mode === "persistent") expect(await rawRecords(factory)).toEqual([]);
  });

  it.each(["persistent", "memory-only"] as const)("fails closed when the trusted catalog is empty in %s mode", async (mode) => {
    const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    const store = storeFor(mode, factory, []);
    await expect(store.putVerified(range, value)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.readExactOrContaining(range)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0 });
    if (mode === "persistent") expect(await rawRecords(factory)).toEqual([]);
  });

  it.each(["persistent", "memory-only"] as const)("rejects fully relabeled PMTiles bytes absent from the trusted %s catalog", async (mode) => {
    const approvedBytes = bytes(1, 2, 3, 4); const pmtilesBytes = bytes(80, 77, 84, 105);
    const approved = await identity({ payload: approvedBytes });
    const fullyRelabeled = await identity({ payload: pmtilesBytes });
    const catalog = createRangeAuthorityCatalog([approved]);
    expect(Object.isFrozen(catalog)).toBe(true); expect(Object.isFrozen(catalog.identities)).toBe(true);
    const store = mode === "persistent"
      ? createRangeStore(app(), budget(), { indexedDB: factory, subtle }, { catalog })
      : createRangeStore(app(), budget(), { subtle }, { catalog, localCandidate: true });
    await expect(store.putVerified(fullyRelabeled, pmtilesBytes)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.readExactOrContaining(fullyRelabeled)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0 });
    if (mode === "persistent") expect(await rawRecords(factory)).toEqual([]);
  });

  it("quarantines corrupt bytes and repairs accounting atomically", async () => {
    const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    const store = persistent(factory, [range]);
    await store.putVerified(range, value); const database = await new Promise<IDBDatabase>((resolve) => {
      const request = factory.open("searise-offline:v1"); request.onsuccess = () => resolve(request.result);
    });
    const transaction = database.transaction("ranges", "readwrite"); const objectStore = transaction.objectStore("ranges");
    const record = await new Promise<Record<string, unknown>>((resolve) => { const request = objectStore.getAll(); request.onsuccess = () => resolve(request.result[0]); });
    record.bytes = bytes(9, 9, 9, 9); objectStore.put(record); await new Promise<void>((resolve) => { transaction.oncomplete = () => resolve(); }); database.close();
    await expect(store.readExactOrContaining(range)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0, entries: [] });
  });

  it("evicts deterministic unleased LRU and protects active and previous pairs", async () => {
    const one = await identity({ payload: bytes(1, 1, 1, 1) });
    const two = await identity({ payload: bytes(2, 2, 2, 2), projection: ["ssp1-26", "2030"] });
    const three = await identity({ payload: bytes(3, 3, 3, 3), projection: ["ssp5-85", "2100"] });
    const wide = persistent(factory, [one, two, three]);
    await wide.putVerified(one, bytes(1, 1, 1, 1)); await wide.putVerified(two, bytes(2, 2, 2, 2));
    const tight = persistent(factory, [one, two, three], app(), 8, 2); await tight.setProtectedPairs(pair("active-build", "active-release"), pair());
    await expect(tight.putVerified(three, bytes(3, 3, 3, 3))).rejects.toBeInstanceOf(RangeStoreQuotaError);
    await tight.setProtectedPairs(null, null); await expect(tight.putVerified(three, bytes(3, 3, 3, 3))).resolves.toBe("stored");
    expect((await tight.inventory()).entries.map((entry) => entry.artifactId)).toEqual([
      "projection-ssp1-26-2030-cog", "projection-ssp5-85-2100-cog",
    ]);
  });

  it("keeps memory protection state and eviction behavior unchanged after a rejected update", async () => {
    const firstBytes = bytes(1, 1, 1, 1); const secondBytes = bytes(2, 2, 2, 2);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ projection: ["ssp1-26", "2030"], payload: secondBytes });
    const store = memory([first, second], app(), 4, 1);
    const active = pair(); const previous = pair("previous-build", "previous-release");
    await store.putVerified(first, firstBytes); await store.setProtectedPairs(active, previous);
    const invalid = pair("invalid-build", "invalid-release");

    await expect(store.setProtectedPairs(invalid, invalid)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ activePair: active, previousPair: previous });
    await expect(store.putVerified(second, secondBytes)).rejects.toBeInstanceOf(RangeStoreQuotaError);
    expect((await store.inventory()).entries.map((entry) => entry.artifactId)).toEqual([
      "projection-ssp2-45-2050-cog",
    ]);
  });

  it("prunes expired leases but preserves live leased pairs", async () => {
    const first = await identity({ payload: bytes(1, 1, 1, 1) });
    const firstStore = persistent(factory, [first]);
    await firstStore.putVerified(first, bytes(1, 1, 1, 1));
    const lease = { contractVersion: 1, leaseId: "lease-a", pair: pair(), expiresAtEpochMs: 2_000, state: "active" } as const;
    await firstStore.acquireLease(lease);
    const secondApp = app("build-b", "release-b"); const second = await identity({ build: "build-b", release: "release-b", payload: bytes(2, 2, 2, 2) });
    const beforeExpiry = persistent(factory, [second], secondApp, 4, 1, () => 1_500);
    await expect(beforeExpiry.putVerified(second, bytes(2, 2, 2, 2))).rejects.toBeInstanceOf(RangeStoreQuotaError);
    const afterExpiry = persistent(factory, [second], secondApp, 4, 1, () => 2_001);
    await expect(afterExpiry.putVerified(second, bytes(2, 2, 2, 2))).resolves.toBe("stored");
    expect((await afterExpiry.inventory()).entries[0].pair.dataReleaseId).toBe("release-b");
  });

  it("atomically rotates active/previous protection with initial lease activation and preserves it for a second tab", async () => {
    const firstPair = pair();
    const first = await identity({ payload: bytes(1, 1, 1, 1) });
    const firstStore = persistent(factory, [first]);
    await firstStore.activateClientLease({
      contractVersion: 1, leaseId: "first-tab", pair: firstPair,
      expiresAtEpochMs: 2_000, state: "active",
    });
    await firstStore.activateClientLease({
      contractVersion: 1, leaseId: "second-tab", pair: firstPair,
      expiresAtEpochMs: 2_000, state: "active",
    });
    await expect(firstStore.inventory()).resolves.toMatchObject({
      activePair: firstPair, previousPair: null,
    });

    const secondPair = pair("build-b", "release-b");
    const second = await identity({ build: "build-b", release: "release-b", payload: bytes(2, 2, 2, 2) });
    const secondStore = persistent(factory, [second], app("build-b", "release-b"));
    await secondStore.activateClientLease({
      contractVersion: 1, leaseId: "new-build-tab", pair: secondPair,
      expiresAtEpochMs: 2_000, state: "active",
    });
    await expect(secondStore.inventory()).resolves.toMatchObject({
      activePair: secondPair, previousPair: firstPair,
    });
  });

  it("upgrades the v1 lease store and isolates the same active lease ID across two release pairs", async () => {
    const firstBytes = bytes(1, 1, 1, 1); const secondBytes = bytes(2, 2, 2, 2);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ build: "build-b", release: "release-b", payload: secondBytes });
    await seedLegacyRangeStore(factory, first, firstBytes);
    const firstStore = persistent(factory, [first]);
    await expect(firstStore.inventory()).resolves.toMatchObject({
      payloadBytes: 4, entryCount: 1, activePair: pair(), previousPair: null,
    });
    expect([...new Uint8Array((await firstStore.readExactOrContaining(first))!)]).toEqual([1, 1, 1, 1]);
    await expect(firstStore.putVerified(first, firstBytes)).resolves.toBe("already-present");
    await expect(rawLeaseState(factory)).resolves.toEqual({ keyPath: "key", records: [] });

    const secondStore = persistent(factory, [second], app("build-b", "release-b"));
    await secondStore.putVerified(second, secondBytes);
    const expiresAtEpochMs = 2_000;
    await firstStore.acquireLease({ contractVersion: 1, leaseId: "shared-lease", pair: pair(), expiresAtEpochMs, state: "active" });
    await secondStore.acquireLease({ contractVersion: 1, leaseId: "shared-lease", pair: pair("build-b", "release-b"), expiresAtEpochMs, state: "active" });

    const thirdBytes = bytes(3, 3, 3, 3);
    const third = await identity({ build: "build-c", release: "release-c", payload: thirdBytes });
    const thirdStore = persistent(factory, [third], app("build-c", "release-c"), 4, 1, () => 1_500);
    await expect(thirdStore.putVerified(third, thirdBytes)).rejects.toBeInstanceOf(RangeStoreQuotaError);
    const { keyPath, records: leases } = await rawLeaseState(factory);
    expect(keyPath).toBe("key");
    expect(leases).toHaveLength(2);
    expect(new Set(leases.map((lease) => lease.key)).size).toBe(2);
  });

  it.each(["persistent", "memory-only"] as const)("binds %s lease acquire and release to the store pair", async (mode) => {
    const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    const store = storeFor(mode, factory, [range]);
    const foreignLease = {
      contractVersion: 1, leaseId: "foreign", pair: pair("build-b", "release-b"),
      expiresAtEpochMs: 2_000, state: "active",
    } as const;
    await expect(store.acquireLease(foreignLease)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.releaseLease(foreignLease)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0 });
  });

  it("rolls back earlier eviction and counters when a quota transaction cannot fit", async () => {
    const unprotected = await identity({ payload: bytes(1, 1, 1, 1) });
    const protectedRange = await identity({ projection: ["ssp1-26", "2030"], payload: bytes(2, 2, 2, 2) });
    const populate = persistent(factory, [unprotected, protectedRange], app(), 12, 3);
    await populate.putVerified(unprotected, bytes(1, 1, 1, 1)); await populate.putVerified(protectedRange, bytes(2, 2, 2, 2));
    const nextApp = app("build-c", "release-c");
    const oversized = await identity({ build: "build-c", release: "release-c", payload: bytes(3, 3, 3, 3), total: 8 });
    const nextStore = persistent(factory, [oversized], nextApp, 4, 1);
    await nextStore.setProtectedPairs(pair(), null);
    await expect(nextStore.putVerified(oversized, bytes(3, 3, 3, 3))).rejects.toBeInstanceOf(RangeStoreQuotaError);
    await expect(nextStore.inventory()).resolves.toMatchObject({ payloadBytes: 8, entryCount: 2 });
    expect((await nextStore.inventory()).entries.map((entry) => entry.artifactId)).toEqual([
      "projection-ssp2-45-2050-cog", "projection-ssp1-26-2030-cog",
    ]);
  });

  it("serializes concurrent admissions without exceeding byte or entry counters", async () => {
    const projections = [["ssp1-26", "2030"], ["ssp2-45", "2050"], ["ssp5-85", "2100"]] as const;
    const ranges = await Promise.all([1, 2, 3].map((value, index) => identity({ projection: projections[index], payload: bytes(value, value, value, value) })));
    const left = persistent(factory, ranges, app(), 8, 2); const right = persistent(factory, ranges, app(), 8, 2);
    await Promise.all(ranges.map((range, index) => (index % 2 ? right : left).putVerified(range, bytes(index + 1, index + 1, index + 1, index + 1))));
    await expect(left.inventory()).resolves.toMatchObject({ payloadBytes: 8, entryCount: 2 });
  });

  it("keeps private and local-candidate COG bytes in memory but rejects PMTiles without opening IndexedDB", async () => {
    const inaccessible = { open: () => { throw new Error("persistent API touched"); } } as unknown as IDBFactory;
    const value = bytes(4, 3, 2, 1); const cog = await identity({ payload: value });
    const privateCog = await identity({ build: "build-p", release: "release-p", payload: value });
    const privateStore = createRangeStore(app("build-p", "release-p", "private-engineering"), budget(), { indexedDB: inaccessible, subtle }, {
      catalog: createRangeAuthorityCatalog([privateCog]),
    });
    const localStore = createRangeStore(app(), budget(), { indexedDB: inaccessible, subtle }, {
      catalog: createRangeAuthorityCatalog([cog]), localCandidate: true,
    });
    expect(privateStore.mode).toBe("memory-only"); expect(localStore.mode).toBe("memory-only");
    await expect(localStore.putVerified(cog, value)).resolves.toBe("stored");
    expect([...new Uint8Array((await localStore.readExactOrContaining(cog))!)]).toEqual([4, 3, 2, 1]);
    const visual = await forgedVisualIdentity({ payload: value });
    const privateVisual = await forgedVisualIdentity({ build: "build-p", release: "release-p", payload: value });
    await expect(localStore.putVerified(visual as RangeIdentityV1, value)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(localStore.putVerifiedBatch([{ identity: visual as RangeIdentityV1, bytes: value }])).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(localStore.readExactOrContaining(visual as RangeIdentityV1)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(privateStore.putVerified(privateVisual as RangeIdentityV1, value)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(localStore.inventory()).resolves.toMatchObject({ payloadBytes: 4, entryCount: 1 });
  });

  it.each(["persistent", "memory-only"] as const)("conditionally rolls back only operation-owned %s range writes", async (mode) => {
    const firstBytes = bytes(1, 2, 3, 4); const secondBytes = bytes(5, 6, 7, 8);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ start: 4, payload: secondBytes });
    const store = storeFor(mode, factory, [first, second], 8, 2);
    await store.putVerified(first, firstBytes);
    const admission = await store.admitVerifiedBatch([
      { identity: first, bytes: firstBytes },
      { identity: second, bytes: secondBytes },
    ], { operationId: "range-operation", signal: new AbortController().signal });
    expect(admission.entries.map((entry) => entry.disposition)).toEqual(["already-present", "stored"]);
    await expect(store.rollbackAdmission({ ...admission })).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.rollbackAdmission(admission)).resolves.toEqual({
      deleted: 1, retainedAlreadyPresent: 1, ownershipLost: 0,
    });
    await expect(store.readExactOrContaining(first)).resolves.toBeInstanceOf(ArrayBuffer);
    await expect(store.readExactOrContaining(second)).resolves.toBeNull();
  });

  it.each(["persistent", "memory-only"] as const)("does not evict prior %s state for an unreceipted coordinated batch", async (mode) => {
    const firstBytes = bytes(1, 2, 3, 4); const secondBytes = bytes(5, 6, 7, 8);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ projection: ["ssp1-26", "2030"], payload: secondBytes });
    const store = storeFor(mode, factory, [first, second], 4, 1);
    await store.putVerified(first, firstBytes);
    await expect(store.admitVerifiedBatch([{ identity: second, bytes: secondBytes }], {
      operationId: "range-overflow",
      signal: new AbortController().signal,
    })).rejects.toBeInstanceOf(RangeStoreQuotaError);
    await expect(store.readExactOrContaining(first)).resolves.toBeInstanceOf(ArrayBuffer);
    await expect(store.readExactOrContaining(second)).resolves.toBeNull();
  });

  it("counts retained bytes when a coordinated memory batch checks byte quota", async () => {
    const firstBytes = bytes(1, 2, 3, 4); const secondBytes = bytes(5, 6, 7, 8);
    const first = await identity({ payload: firstBytes });
    const second = await identity({ projection: ["ssp1-26", "2030"], payload: secondBytes });
    const store = memory([first, second], app(), 4, 2);
    await store.putVerified(first, firstBytes);

    await expect(store.admitVerifiedBatch([{ identity: second, bytes: secondBytes }], {
      operationId: "range-byte-overflow",
      signal: new AbortController().signal,
    })).rejects.toBeInstanceOf(RangeStoreQuotaError);

    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 4, entryCount: 1 });
    await expect(store.readExactOrContaining(first)).resolves.toBeInstanceOf(ArrayBuffer);
    await expect(store.readExactOrContaining(second)).resolves.toBeNull();
  });

  it.each(["persistent", "memory-only"] as const)("cancels a %s coordinated batch before mutation", async (mode) => {
    const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    const store = storeFor(mode, factory, [range]);
    const controller = new AbortController(); controller.abort();
    await expect(store.admitVerifiedBatch([{ identity: range, bytes: value }], {
      operationId: "range-cancel",
      signal: controller.signal,
    })).rejects.toBeInstanceOf(RangeStoreAbortedError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0 });
  });

  it("persists only the privacy allowlist and never a full URL", async () => {
    const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    const store = persistent(factory, [range]);
    await store.putVerified(range, value); const serialized = JSON.stringify(await rawRecords(factory));
    expect(serialized).not.toContain("https://"); expect(serialized).not.toContain("canonicalUrl");
    expect(serialized).not.toMatch(/query|latitude|longitude|placeLabel|clientId/i);
  });
});
