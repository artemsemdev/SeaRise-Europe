// @vitest-environment node

import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";
import { validateAppAuthority, validateRangeIdentity, type RangeIdentityV1 } from "./contracts/v1";
import { validateStorageBudget } from "./contracts/policy";
import { validateAppReleasePair } from "./contracts/keys";
import {
  RangeStoreIntegrityError,
  RangeStoreQuotaError,
  RangeStoreUnsupportedError,
  createRangeStore,
} from "./range-store";

const A = "a".repeat(64);
const C = "c".repeat(64);
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
  build?: string; release?: string; artifact?: string; role?: "projection-analysis-cog" | "projection-visual-pmtiles";
  start?: number; payload: ArrayBuffer; total?: number;
}): Promise<RangeIdentityV1> {
  const build = input.build ?? "build-a"; const release = input.release ?? "release-a";
  const role = input.role ?? "projection-analysis-cog"; const start = input.start ?? 0;
  const extension = role === "projection-analysis-cog" ? "tif" : "pmtiles";
  return validateRangeIdentity({
    contractVersion: 1,
    authority: {
      contractVersion: 1, pair: { contractVersion: 1, appBuildId: build, dataReleaseId: release },
      artifactId: input.artifact ?? "projection-ssp2-45-2050", role,
      canonicalUrl: `https://static.example/releases/${release}/layers/${input.artifact ?? "projection"}.${extension}`,
      path: `layers/${input.artifact ?? "projection"}.${extension}`, mediaType: role === "projection-analysis-cog" ? "image/tiff" : "application/vnd.pmtiles",
      totalByteSize: input.total ?? 12, artifactSha256: C, etag: `"sha256-${C}"`, integrityChunkSize: 4,
    },
    interval: { start, endExclusive: Math.min(start + 4, input.total ?? 12) },
    authorizedIntervalSha256: await hash(input.payload),
  });
}
function persistent(factory: IDBFactory, authority = app(), maximumBytes = 12, maximumEntries = 3, now = () => 1_000) {
  return createRangeStore(authority, budget(maximumBytes, maximumEntries), { indexedDB: factory, subtle, now });
}
async function rawRecords(factory: IDBFactory): Promise<Record<string, unknown>[]> {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = factory.open("searise-offline:v1", 1);
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  const records = await new Promise<Record<string, unknown>[]>((resolve, reject) => {
    const request = database.transaction("ranges").objectStore("ranges").getAll();
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  database.close(); return records;
}

describe("authoritative IndexedDB range store", () => {
  let factory: IDBFactory;
  beforeEach(() => { factory = new IDBFactory(); });

  it("returns exact bytes or a copied slice from one containing authorized chunk", async () => {
    const store = persistent(factory); const chunk = bytes(10, 20, 30, 40); const range = await identity({ payload: chunk });
    await expect(store.putVerified(range, bytes(40, 30, 20, 10))).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.putVerified(range, chunk)).resolves.toBe("stored");
    await expect(store.putVerified(range, chunk)).resolves.toBe("already-present");
    expect([...new Uint8Array((await store.readExactOrContaining(range))!)]).toEqual([10, 20, 30, 40]);
    expect([...new Uint8Array((await store.readExactOrContaining(range, { start: 1, endExclusive: 3 }))!)]).toEqual([20, 30]);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 4, entryCount: 1 });
  });

  it("never assembles adjacent chunks and isolates every app/release/artifact authority", async () => {
    const store = persistent(factory); const first = await identity({ payload: bytes(1, 2, 3, 4) });
    const second = await identity({ start: 4, payload: bytes(5, 6, 7, 8) });
    await store.putVerified(first, bytes(1, 2, 3, 4)); await store.putVerified(second, bytes(5, 6, 7, 8));
    await expect(store.readExactOrContaining(first, { start: 2, endExclusive: 6 })).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    const otherRelease = await identity({ release: "release-b", payload: bytes(1, 2, 3, 4) });
    await expect(store.readExactOrContaining(otherRelease)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    const otherBuild = await identity({ build: "build-b", payload: bytes(1, 2, 3, 4) });
    await expect(store.readExactOrContaining(otherBuild)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    const otherArtifact = await identity({ artifact: "other-cog", payload: bytes(1, 2, 3, 4) });
    await expect(store.readExactOrContaining(otherArtifact)).resolves.toBeNull();
  });

  it("fails PMTiles persistent reads and writes closed", async () => {
    const store = persistent(factory); const value = bytes(1, 2, 3, 4);
    const visual = await identity({ payload: value, role: "projection-visual-pmtiles" });
    await expect(store.putVerified(visual, value)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(store.readExactOrContaining(visual)).rejects.toBeInstanceOf(RangeStoreUnsupportedError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0 });
    expect(await rawRecords(factory)).toEqual([]);
  });

  it("quarantines corrupt bytes and repairs accounting atomically", async () => {
    const store = persistent(factory); const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    await store.putVerified(range, value); const database = await new Promise<IDBDatabase>((resolve) => {
      const request = factory.open("searise-offline:v1", 1); request.onsuccess = () => resolve(request.result);
    });
    const transaction = database.transaction("ranges", "readwrite"); const objectStore = transaction.objectStore("ranges");
    const record = await new Promise<Record<string, unknown>>((resolve) => { const request = objectStore.getAll(); request.onsuccess = () => resolve(request.result[0]); });
    record.bytes = bytes(9, 9, 9, 9); objectStore.put(record); await new Promise<void>((resolve) => { transaction.oncomplete = () => resolve(); }); database.close();
    await expect(store.readExactOrContaining(range)).rejects.toBeInstanceOf(RangeStoreIntegrityError);
    await expect(store.inventory()).resolves.toMatchObject({ payloadBytes: 0, entryCount: 0, entries: [] });
  });

  it("evicts deterministic unleased LRU and protects active and previous pairs", async () => {
    const wide = persistent(factory); const one = await identity({ payload: bytes(1, 1, 1, 1), artifact: "one" });
    const two = await identity({ payload: bytes(2, 2, 2, 2), artifact: "two" });
    await wide.putVerified(one, bytes(1, 1, 1, 1)); await wide.putVerified(two, bytes(2, 2, 2, 2));
    const tight = persistent(factory, app(), 8, 2); await tight.setProtectedPairs(pair("active-build", "active-release"), pair());
    const three = await identity({ payload: bytes(3, 3, 3, 3), artifact: "three" });
    await expect(tight.putVerified(three, bytes(3, 3, 3, 3))).rejects.toBeInstanceOf(RangeStoreQuotaError);
    await tight.setProtectedPairs(null, null); await expect(tight.putVerified(three, bytes(3, 3, 3, 3))).resolves.toBe("stored");
    expect((await tight.inventory()).entries.map((entry) => entry.artifactId)).toEqual(["two", "three"]);
  });

  it("prunes expired leases but preserves live leased pairs", async () => {
    const firstStore = persistent(factory); const first = await identity({ payload: bytes(1, 1, 1, 1) });
    await firstStore.putVerified(first, bytes(1, 1, 1, 1));
    const lease = { contractVersion: 1, leaseId: "lease-a", pair: pair(), expiresAtEpochMs: 2_000, state: "active" } as const;
    await firstStore.acquireLease(lease);
    const secondApp = app("build-b", "release-b"); const second = await identity({ build: "build-b", release: "release-b", payload: bytes(2, 2, 2, 2) });
    const beforeExpiry = persistent(factory, secondApp, 4, 1, () => 1_500);
    await expect(beforeExpiry.putVerified(second, bytes(2, 2, 2, 2))).rejects.toBeInstanceOf(RangeStoreQuotaError);
    const afterExpiry = persistent(factory, secondApp, 4, 1, () => 2_001);
    await expect(afterExpiry.putVerified(second, bytes(2, 2, 2, 2))).resolves.toBe("stored");
    expect((await afterExpiry.inventory()).entries[0].pair.dataReleaseId).toBe("release-b");
  });

  it("rolls back earlier eviction and counters when a quota transaction cannot fit", async () => {
    const populate = persistent(factory, app(), 12, 3); const unprotected = await identity({ artifact: "old", payload: bytes(1, 1, 1, 1) });
    const protectedRange = await identity({ artifact: "active", payload: bytes(2, 2, 2, 2) });
    await populate.putVerified(unprotected, bytes(1, 1, 1, 1)); await populate.putVerified(protectedRange, bytes(2, 2, 2, 2));
    const nextApp = app("build-c", "release-c"); const nextStore = persistent(factory, nextApp, 4, 1);
    await nextStore.setProtectedPairs(pair(), null);
    const oversized = await identity({ build: "build-c", release: "release-c", payload: bytes(3, 3, 3, 3), total: 8 });
    await expect(nextStore.putVerified(oversized, bytes(3, 3, 3, 3))).rejects.toBeInstanceOf(RangeStoreQuotaError);
    await expect(nextStore.inventory()).resolves.toMatchObject({ payloadBytes: 8, entryCount: 2 });
    expect((await nextStore.inventory()).entries.map((entry) => entry.artifactId)).toEqual(["old", "active"]);
  });

  it("serializes concurrent admissions without exceeding byte or entry counters", async () => {
    const left = persistent(factory, app(), 8, 2); const right = persistent(factory, app(), 8, 2);
    const ranges = await Promise.all([1, 2, 3].map((value) => identity({ artifact: `cog-${value}`, payload: bytes(value, value, value, value) })));
    await Promise.all(ranges.map((range, index) => (index % 2 ? right : left).putVerified(range, bytes(index + 1, index + 1, index + 1, index + 1))));
    await expect(left.inventory()).resolves.toMatchObject({ payloadBytes: 8, entryCount: 2 });
  });

  it("keeps private and local-candidate bytes in memory without opening IndexedDB", async () => {
    const inaccessible = { open: () => { throw new Error("persistent API touched"); } } as unknown as IDBFactory;
    const privateStore = createRangeStore(app("build-p", "release-p", "private-engineering"), budget(), { indexedDB: inaccessible, subtle });
    const localStore = createRangeStore(app(), budget(), { indexedDB: inaccessible, subtle }, true);
    expect(privateStore.mode).toBe("memory-only"); expect(localStore.mode).toBe("memory-only");
    const value = bytes(4, 3, 2, 1); const visual = await identity({ payload: value, role: "projection-visual-pmtiles" });
    await expect(localStore.putVerified(visual, value)).resolves.toBe("stored");
    expect([...new Uint8Array((await localStore.readExactOrContaining(visual))!)]).toEqual([4, 3, 2, 1]);
  });

  it("persists only the privacy allowlist and never a full URL", async () => {
    const store = persistent(factory); const value = bytes(1, 2, 3, 4); const range = await identity({ payload: value });
    await store.putVerified(range, value); const serialized = JSON.stringify(await rawRecords(factory));
    expect(serialized).not.toContain("https://"); expect(serialized).not.toContain("canonicalUrl");
    expect(serialized).not.toMatch(/query|latitude|longitude|placeLabel|clientId/i);
  });
});
