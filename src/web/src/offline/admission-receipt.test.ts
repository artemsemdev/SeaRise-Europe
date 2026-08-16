// @vitest-environment node

import { webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { IDBFactory } from "fake-indexeddb";
import fixture from "../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { describe, expect, it } from "vitest";
import { ManifestRepository } from "../data/manifest-repository";
import {
  validateAppAuthority,
  type RangeIdentityV1,
  type StorageProfileV1,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";
import {
  assertAcceptedRangeResource,
  assertAcceptedWholeResource,
  coordinateVerifiedAdmission,
  createAdmissionPlanIdentity,
  createAdmissionReceiptStore,
  type AdmissionLockPort,
} from "./admission-receipt";
import { createVerifiedReleaseResourcePlan, type VerifiedReleaseResourcePlanV1 } from "./release-resource-plan";
import type { WholeResourceStore } from "./whole-resource-cache";
import type { RangeStore } from "./range-store";

const subtle = webcrypto.subtle as SubtleCrypto;
const A = "a".repeat(64);
const RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const MANIFEST_URL = `https://fixture.example/releases/${RELEASE_ID}/manifest.json`;
const INDEX_PATH = resolve(process.cwd(), "../../contracts/release/v2/fixtures/browser-release", RELEASE_ID, "analysis/cog-range-integrity.json");

class TestAdmissionLocks implements AdmissionLockPort {
  readonly #tails = new Map<string, Promise<void>>();

  async request<T>(
    name: string,
    options: Readonly<{ mode: "exclusive"; signal: AbortSignal }>,
    operation: () => Promise<T>,
  ): Promise<T> {
    const previous = this.#tails.get(name) ?? Promise.resolve();
    let release!: () => void;
    const current = new Promise<void>((resolvePromise) => { release = resolvePromise; });
    this.#tails.set(name, previous.then(() => current));
    await previous;
    if (options.signal.aborted) throw new DOMException("Aborted", "AbortError");
    try { return await operation(); } finally { release(); }
  }
}
const app = (disposition: "synthetic-fixture" | "private-engineering" = "synthetic-fixture") => validateAppAuthority({
  contractVersion: 1,
  appBuildId: "app-build-60",
  dataReleaseId: RELEASE_ID,
  manifestUrl: MANIFEST_URL,
  releaseDisposition: disposition,
  precacheSetSha256: A,
});

let publicReleasePlan: Promise<VerifiedReleaseResourcePlanV1> | undefined;
let candidateReleasePlan: Promise<VerifiedReleaseResourcePlanV1> | undefined;
async function releasePlan(localCandidate: boolean): Promise<VerifiedReleaseResourcePlanV1> {
  const current = localCandidate ? candidateReleasePlan : publicReleasePlan;
  if (current) return current;
  const created = (async () => {
    const context = await new ManifestRepository({
      manifestUrl: MANIFEST_URL,
      allowedOrigins: ["https://fixture.example"],
      expectedDisposition: "synthetic-fixture",
      transport: async () => new Response(JSON.stringify(fixture), { headers: { "content-type": "application/json" } }),
    }).load(RELEASE_ID, new AbortController().signal);
    const bytes = await readFile(INDEX_PATH);
    return createVerifiedReleaseResourcePlan({
      context,
      appAuthority: app(),
      rangeIntegrityBytes: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
      localCandidate,
    });
  })();
  if (localCandidate) candidateReleasePlan = created;
  else publicReleasePlan = created;
  return created;
}

async function plan(localCandidate = true) {
  const exact = await releasePlan(localCandidate);
  return createAdmissionPlanIdentity({
    releasePlan: exact,
    wholeResources: exact.routes
      .filter((route) => route.kind === "complete-resource")
      .map((route) => route.authority),
    rangeResources: exact.routes
      .filter((route) => route.kind === "analysis-cog-ranges")
      .flatMap((route) => route.ranges),
    subtle,
  });
}

async function subjectPlan(
  wholeResources: readonly WholeResourceAuthorityV1[],
  rangeResources: readonly RangeIdentityV1[] = [],
) {
  return createAdmissionPlanIdentity({
    releasePlan: await releasePlan(true),
    wholeResources,
    rangeResources,
    subtle,
  });
}

async function resources(localCandidate = true) {
  const exact = await releasePlan(localCandidate);
  return {
    wholeResources: exact.routes.filter((route) => route.kind === "complete-resource").map((route) => route.authority),
    rangeWrites: exact.routes.filter((route) => route.kind === "analysis-cog-ranges").flatMap((route) =>
      route.ranges.map((identity) => ({
        identity,
        bytes: new ArrayBuffer(identity.interval.endExclusive - identity.interval.start),
      }))),
  };
}

function admissionStores(profile: StorageProfileV1, options: Readonly<{
  log?: string[];
  failWholeAdmission?: boolean;
  failWholeReadback?: boolean;
  abortAfterWholeAdmission?: AbortController;
}> = {}): { wholeStore: WholeResourceStore; rangeStore: RangeStore } {
  const wholeStore = {
    mode: profile.mode,
    storageProfile: profile,
    fetchAndAdmit: async () => new Response("hello"),
    fetchAndAdmitBatch: async (authorities: readonly WholeResourceAuthorityV1[], admission: { operationId: string }) => {
      options.log?.push("whole-admit");
      if (options.failWholeAdmission) throw new Error("injected whole admission failure");
      options.abortAfterWholeAdmission?.abort();
      return Object.freeze({
        contractVersion: 1 as const,
        operationId: admission.operationId,
        entries: Object.freeze(authorities.map((authority) => Object.freeze({ authority, disposition: "stored" as const }))),
      });
    },
    rollbackAdmission: async () => {
      options.log?.push("whole-rollback");
      return Object.freeze({ deleted: 0, retainedAlreadyPresent: 0, ownershipLost: 0 });
    },
    read: async () => {
      options.log?.push("whole-readback");
      return options.failWholeReadback
        ? Object.freeze({ state: "miss" as const })
        : Object.freeze({ state: "hit" as const, response: new Response("hello"), byteLength: 5 });
    },
    readAccepted: async () => Object.freeze({ state: "hit" as const, response: new Response("hello"), byteLength: 5 }),
    inventory: async () => Object.freeze({
      contractVersion: 1 as const, pair: profile.pair, verifiedEntries: 1, verifiedBytes: 5,
      missingEntries: 0, quarantinedEntries: 0, availableForDeclaredResources: true,
    }),
    close: () => undefined,
  } satisfies WholeResourceStore;
  const rangeStore = {
    mode: profile.mode,
    storageProfile: profile,
    putVerified: async () => "stored" as const,
    putVerifiedBatch: async () => Object.freeze(["stored" as const]),
    admitVerifiedBatch: async (writes: readonly { identity: RangeIdentityV1 }[], admission: { operationId: string }) => {
      options.log?.push("range-admit");
      return Object.freeze({
        contractVersion: 1 as const,
        operationId: admission.operationId,
        entries: Object.freeze(writes.map(({ identity }) => Object.freeze({ identity, disposition: "stored" as const }))),
      });
    },
    rollbackAdmission: async () => {
      options.log?.push("range-rollback");
      return Object.freeze({ deleted: 0, retainedAlreadyPresent: 0, ownershipLost: 0 });
    },
    readExactOrContaining: async (identity: RangeIdentityV1) => {
      options.log?.push("range-readback");
      return new ArrayBuffer(identity.interval.endExclusive - identity.interval.start);
    },
    readAccepted: async () => new ArrayBuffer(4),
    acquireLease: async () => undefined,
    releaseLease: async () => undefined,
    setProtectedPairs: async () => undefined,
    inventory: async () => Object.freeze({
      mode: profile.mode, payloadBytes: 4, entryCount: 1,
      activePair: null, previousPair: null, entries: Object.freeze([]),
    }),
    close: () => undefined,
  } satisfies RangeStore;
  return { wholeStore, rangeStore };
}

async function admit(
  identity: Awaited<ReturnType<typeof plan>>,
  receiptStore: ReturnType<typeof createAdmissionReceiptStore>,
  options: Readonly<{
    wholeResources?: readonly WholeResourceAuthorityV1[];
    rangeWrites?: readonly Readonly<{ identity: RangeIdentityV1; bytes: ArrayBuffer }>[];
    signal?: AbortSignal;
  }> = {},
) {
  const exactResources = await resources(identity.storageProfile.memoryReason === "local-candidate");
  const stores = admissionStores(identity.storageProfile);
  return coordinateVerifiedAdmission({
    plan: identity,
    wholeResources: options.wholeResources ?? exactResources.wholeResources,
    rangeWrites: options.rangeWrites ?? exactResources.rangeWrites,
    ...stores,
    receiptStore,
    subtle,
    signal: options.signal ?? new AbortController().signal,
  });
}

describe("verified coordinated-admission receipt v1", () => {
  it("derives one deterministic, order-independent exact resource-plan identity", async () => {
    const first = await plan();
    const second = await plan();
    expect(first).toEqual(second);
    expect(first.wholeResources.length).toBeGreaterThan(0);
    expect(first.rangeResources.length).toBeGreaterThan(0);
    expect(first.storageProfile).toMatchObject({ mode: "memory-only", memoryReason: "local-candidate" });
    expect(first.resourcePlanSha256).toMatch(/^[0-9a-f]{64}$/u);
  });

  it("rejects copied release plans and partial routed admission sets", async () => {
    const exactReleasePlan = await releasePlan(true);
    await expect(createAdmissionPlanIdentity({
      releasePlan: { ...exactReleasePlan },
      wholeResources: [],
      rangeResources: [],
      subtle,
    })).rejects.toMatchObject({ code: "AuthorityRejected" });
    const identity = await plan();
    const exactResources = await resources(true);
    const store = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "partial" });
    await expect(admit(identity, store, {
      wholeResources: exactResources.wholeResources.slice(1),
    })).rejects.toMatchObject({ code: "AuthorityRejected" });
    await expect(admit(identity, store, {
      wholeResources: [],
      rangeWrites: [],
    })).rejects.toMatchObject({ code: "AuthorityRejected" });
    await expect(coordinateVerifiedAdmission({
      plan: { ...identity },
      ...exactResources,
      ...admissionStores(identity.storageProfile),
      receiptStore: store,
      subtle,
      signal: new AbortController().signal,
    })).rejects.toMatchObject({ code: "AuthorityRejected" });
  });

  it("rejects a forged subject even when it copies an otherwise canonical release authority", async () => {
    const exactResources = await resources(true);
    const forged = Object.freeze({
      ...exactResources.wholeResources[0],
      sha256: "b".repeat(64),
      etag: `"sha256-${"b".repeat(64)}"`,
    }) as WholeResourceAuthorityV1;
    await expect(subjectPlan([forged])).rejects.toMatchObject({ code: "AuthorityRejected" });
  });

  it("keeps two valid subject receipts coexisting and rejects cross-subject gate confusion", async () => {
    const exactResources = await resources(true);
    const firstResource = exactResources.wholeResources[0]!;
    const secondResource = exactResources.wholeResources[1]!;
    const firstPlan = await subjectPlan([firstResource]);
    const secondPlan = await subjectPlan([secondResource]);
    expect(firstPlan.releaseRoutesSha256).toBe(secondPlan.releaseRoutesSha256);
    expect(firstPlan.resourcePlanSha256).not.toBe(secondPlan.resourcePlanSha256);
    const store = createAdmissionReceiptStore(app(), subtle, {
      localCandidate: true,
      nextOperationId: (() => { let value = 0; return () => `subject-${++value}`; })(),
    });
    const first = await coordinateVerifiedAdmission({
      plan: firstPlan,
      wholeResources: [firstResource],
      rangeWrites: [],
      ...admissionStores(firstPlan.storageProfile),
      receiptStore: store,
      subtle,
      signal: new AbortController().signal,
    });
    const second = await coordinateVerifiedAdmission({
      plan: secondPlan,
      wholeResources: [secondResource],
      rangeWrites: [],
      ...admissionStores(secondPlan.storageProfile),
      receiptStore: store,
      subtle,
      signal: new AbortController().signal,
    });
    await expect(store.accepted(firstPlan)).resolves.toMatchObject({
      receiptSha256: first.gate.receiptSha256,
    });
    await expect(store.accepted(secondPlan)).resolves.toMatchObject({
      receiptSha256: second.gate.receiptSha256,
    });
    await expect(assertAcceptedWholeResource(first.gate, secondResource, subtle))
      .rejects.toMatchObject({ code: "AuthorityRejected" });
    await expect(assertAcceptedWholeResource(second.gate, firstResource, subtle))
      .rejects.toMatchObject({ code: "AuthorityRejected" });
  });

  it("publishes a memory-only receipt last and issues non-forgeable exact read gates", async () => {
    const identity = await plan();
    const store = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "candidate" });
    const { gate } = await admit(identity, store);
    const exactResources = await resources(true);
    const firstWhole = exactResources.wholeResources[0]!;
    const firstRange = exactResources.rangeWrites[0]!.identity;
    expect(store.mode).toBe("memory-only");
    await expect(assertAcceptedWholeResource(gate, firstWhole, subtle)).resolves.toBeUndefined();
    await expect(assertAcceptedRangeResource(gate, firstRange, subtle)).resolves.toBeUndefined();
    await expect(assertAcceptedWholeResource({ ...gate }, firstWhole, subtle)).rejects.toMatchObject({
      code: "AuthorityRejected",
    });
    await expect(store.publishLast({
      contractVersion: 1,
      plan: identity,
      operationId: "forged",
      expectedPreviousReceiptSha256: null,
    }, new AbortController().signal)).rejects.toMatchObject({ code: "AuthorityRejected" });
  });

  it("preserves the prior accepted receipt across cancellation and repeated admission", async () => {
    const firstPlan = await plan();
    const store = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "preserve" });
    const first = await admit(firstPlan, store);
    const aborted = new AbortController();
    aborted.abort();
    await expect(admit(firstPlan, store, {
      signal: aborted.signal,
    })).rejects.toMatchObject({
      code: "Aborted",
    });
    await expect(admit(firstPlan, store)).resolves.toMatchObject({
      gate: { receiptSha256: first.gate.receiptSha256 },
    });
    await expect(store.accepted(firstPlan)).resolves.toMatchObject({ receiptSha256: first.gate.receiptSha256 });
  });

  it("persists and revalidates an exact receipt across store instances", async () => {
    const factory = new IDBFactory();
    const locks = new TestAdmissionLocks();
    const identity = await plan(false);
    const firstStore = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory, locks, nextOperationId: () => "persistent-1" });
    const published = await admit(identity, firstStore);
    firstStore.close();
    const reopened = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory, locks, nextOperationId: () => "persistent-2" });
    await expect(reopened.accepted(identity)).resolves.toMatchObject({ receiptSha256: published.gate.receiptSha256 });
    reopened.close();
  });

  it("treats tampered persisted receipt bytes as absent authority", async () => {
    const factory = new IDBFactory();
    const locks = new TestAdmissionLocks();
    const identity = await plan(false);
    const store = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory, locks, nextOperationId: () => "tamper-1" });
    await admit(identity, store);
    store.close();
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open("searise-offline:admission-receipts:v1", 1);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const transaction = database.transaction("accepted-receipts", "readwrite");
    const objectStore = transaction.objectStore("accepted-receipts");
    const record = await new Promise<Record<string, unknown>>((resolve, reject) => {
      const request = objectStore.getAll();
      request.onsuccess = () => resolve(request.result[0] as Record<string, unknown>);
      request.onerror = () => reject(request.error);
    });
    const key = record.key as string;
    const exactRecord = await new Promise<Record<string, unknown>>((resolve, reject) => {
      const request = objectStore.get(key);
      request.onsuccess = () => resolve(request.result as Record<string, unknown>);
      request.onerror = () => reject(request.error);
    });
    objectStore.put({ ...exactRecord, receiptSha256: "f".repeat(64) });
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
    database.close();
    const reopened = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory, locks, nextOperationId: () => "tamper-2" });
    await expect(reopened.accepted(identity)).resolves.toBeNull();
    reopened.close();
  });

  it("deletes only the exact current receipt and cannot delete through a copied gate", async () => {
    const identity = await plan();
    const store = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "delete" });
    const { gate } = await admit(identity, store);
    await expect(store.deleteIfCurrent({ ...gate })).rejects.toMatchObject({ code: "AuthorityRejected" });
    await expect(store.deleteIfCurrent(gate)).resolves.toBe(true);
    await expect(store.accepted(identity)).resolves.toBeNull();
  });

  it("stores only resource authority aggregates and no scientific or personal state", async () => {
    const identity = await plan();
    const store = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "privacy" });
    const { gate } = await admit(identity, store);
    expect(JSON.stringify({ identity, gate })).not.toMatch(
      /ProjectionAvailable|DataUnavailable|OutOfScope|UnsupportedGeography|latitude|longitude|query|placeId/u,
    );
  });

  it("fails closed on mixed persistence profiles before any store admission", async () => {
    const identity = await plan();
    const exactResources = await resources(true);
    const stores = admissionStores(identity.storageProfile, { failWholeAdmission: true });
    const persistentReceipt = createAdmissionReceiptStore(app(), subtle, {
      indexedDB: new IDBFactory(),
      locks: new TestAdmissionLocks(),
      nextOperationId: () => "must-not-run",
    });
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      ...exactResources,
      ...stores,
      receiptStore: persistentReceipt,
      subtle,
      signal: new AbortController().signal,
    })).rejects.toMatchObject({ code: "AuthorityRejected" });
    expect(() => createAdmissionReceiptStore(app(), subtle, {
      indexedDB: new IDBFactory(),
    })).toThrow(/LockManager is unavailable/);
  });

  it("keeps an explicit local Candidate memory-only without opening supplied persistence APIs", async () => {
    let persistenceCalls = 0;
    const neverIndexedDb = {
      open: () => { persistenceCalls += 1; throw new Error("Candidate opened IndexedDB"); },
    } as unknown as IDBFactory;
    const neverLocks: AdmissionLockPort = {
      request: async () => { persistenceCalls += 1; throw new Error("Candidate requested a persistent lock"); },
    };
    const identity = await plan();
    const receipt = createAdmissionReceiptStore(app(), subtle, {
      localCandidate: true,
      indexedDB: neverIndexedDb,
      locks: neverLocks,
      nextOperationId: () => "candidate-memory",
    });
    await expect(admit(identity, receipt)).resolves.toBeDefined();
    expect(receipt.mode).toBe("memory-only");
    expect(persistenceCalls).toBe(0);
  });

  it("publishes the verified receipt strictly after both admissions and exact readback", async () => {
    const identity = await plan();
    const exactResources = await resources(true);
    const log: string[] = [];
    const stores = admissionStores(identity.storageProfile, { log });
    const receipts = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "ordered" });
    const loggedReceipts = {
      mode: receipts.mode,
      storageProfile: receipts.storageProfile,
      runExclusive: receipts.runExclusive.bind(receipts),
      publishLast: async (...args: Parameters<typeof receipts.publishLast>) => {
        log.push("receipt-publish");
        return receipts.publishLast(...args);
      },
      accepted: receipts.accepted.bind(receipts),
      deleteIfCurrent: receipts.deleteIfCurrent.bind(receipts),
      close: receipts.close.bind(receipts),
    } satisfies typeof receipts;
    await coordinateVerifiedAdmission({
      plan: identity,
      ...exactResources,
      ...stores,
      receiptStore: loggedReceipts,
      subtle,
      signal: new AbortController().signal,
    });
    expect(log.slice(0, 2)).toEqual(["range-admit", "whole-admit"]);
    expect(log.at(-1)).toBe("receipt-publish");
    expect(log.slice(2, -1)).toEqual([
      ...exactResources.wholeResources.map(() => "whole-readback"),
      ...exactResources.rangeWrites.map(() => "range-readback"),
    ]);
  });

  it("rolls back range ownership when whole admission fails and publishes no receipt", async () => {
    const identity = await plan();
    const exactResources = await resources(true);
    const log: string[] = [];
    const stores = admissionStores(identity.storageProfile, { log, failWholeAdmission: true });
    const receipts = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "failed" });
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      ...exactResources,
      ...stores,
      receiptStore: receipts,
      subtle,
      signal: new AbortController().signal,
    })).rejects.toThrow(/injected whole admission failure/);
    expect(log).toEqual(["range-admit", "whole-admit", "range-rollback"]);
    await expect(receipts.accepted(identity)).resolves.toBeNull();
  });

  it("rolls back both operation handles when post-admission readback fails", async () => {
    const identity = await plan();
    const exactResources = await resources(true);
    const log: string[] = [];
    const stores = admissionStores(identity.storageProfile, { log, failWholeReadback: true });
    const receipts = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "readback" });
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      ...exactResources,
      ...stores,
      receiptStore: receipts,
      subtle,
      signal: new AbortController().signal,
    })).rejects.toMatchObject({ code: "IntegrityFailed" });
    expect(log).toEqual([
      "range-admit", "whole-admit", "whole-readback", "whole-rollback", "range-rollback",
    ]);
    await expect(receipts.accepted(identity)).resolves.toBeNull();
  });

  it("cancels between store commits, conditionally rolls both back, and exposes no receipt", async () => {
    const identity = await plan();
    const exactResources = await resources(true);
    const log: string[] = [];
    const controller = new AbortController();
    const stores = admissionStores(identity.storageProfile, { log, abortAfterWholeAdmission: controller });
    const receipts = createAdmissionReceiptStore(app(), subtle, { localCandidate: true, nextOperationId: () => "cancelled" });
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      ...exactResources,
      ...stores,
      receiptStore: receipts,
      subtle,
      signal: controller.signal,
    })).rejects.toMatchObject({ code: "Aborted" });
    expect(log).toEqual(["range-admit", "whole-admit", "whole-rollback", "range-rollback"]);
    await expect(receipts.accepted(identity)).resolves.toBeNull();
  });

  it("serializes two persistent instances and retains the first operation's accepted bytes", async () => {
    const identity = await plan(false);
    const exactResources = await resources(false);
    const factory = new IDBFactory();
    const locks = new TestAdmissionLocks();
    const owners = new Map<string, string>();
    const operations: string[] = [];
    const wholeStore = (): WholeResourceStore => ({
      mode: "persistent",
      storageProfile: identity.storageProfile,
      fetchAndAdmit: async () => new Response("unused"),
      fetchAndAdmitBatch: async (authorities, options) => {
        operations.push(options.operationId);
        const entries = authorities.map((authority) => {
          const disposition = owners.has(authority.canonicalUrl) ? "already-present" as const : "stored" as const;
          if (disposition === "stored") owners.set(authority.canonicalUrl, options.operationId);
          return Object.freeze({ authority, disposition });
        });
        return Object.freeze({ contractVersion: 1 as const, operationId: options.operationId, entries: Object.freeze(entries) });
      },
      rollbackAdmission: async (admission) => {
        let deleted = 0;
        for (const entry of admission.entries) {
          if (entry.disposition === "stored" && owners.get(entry.authority.canonicalUrl) === admission.operationId) {
            owners.delete(entry.authority.canonicalUrl);
            deleted += 1;
          }
        }
        return Object.freeze({ deleted, retainedAlreadyPresent: admission.entries.length - deleted, ownershipLost: 0 });
      },
      read: async (authority) => owners.has(authority.canonicalUrl)
        ? Object.freeze({ state: "hit" as const, response: new Response("verified"), byteLength: authority.byteSize })
        : Object.freeze({ state: "miss" as const }),
      readAccepted: async (authority) => owners.has(authority.canonicalUrl)
        ? Object.freeze({ state: "hit" as const, response: new Response("verified"), byteLength: authority.byteSize })
        : Object.freeze({ state: "miss" as const }),
      inventory: async () => Object.freeze({
        contractVersion: 1 as const,
        pair: identity.pair,
        verifiedEntries: owners.size,
        verifiedBytes: 0,
        missingEntries: 0,
        quarantinedEntries: 0,
        availableForDeclaredResources: true,
      }),
      close: () => undefined,
    });
    const firstStores = admissionStores(identity.storageProfile);
    const secondStores = admissionStores(identity.storageProfile);
    const firstReceipt = createAdmissionReceiptStore(app(), subtle, {
      indexedDB: factory, locks, nextOperationId: () => "winner-operation",
    });
    const secondReceipt = createAdmissionReceiptStore(app(), subtle, {
      indexedDB: factory, locks, nextOperationId: () => "loser-operation",
    });
    const admission = (receiptStore: ReturnType<typeof createAdmissionReceiptStore>, store: WholeResourceStore) =>
      coordinateVerifiedAdmission({
        plan: identity,
        ...exactResources,
        wholeStore: store,
        rangeStore: receiptStore === firstReceipt ? firstStores.rangeStore : secondStores.rangeStore,
        receiptStore,
        subtle,
        signal: new AbortController().signal,
      });

    const [winner, loser] = await Promise.allSettled([
      admission(firstReceipt, wholeStore()),
      admission(secondReceipt, wholeStore()),
    ]);

    expect(winner.status).toBe("fulfilled");
    expect(loser.status).toBe("fulfilled");
    expect(operations).toEqual(["winner-operation", "loser-operation"]);
    expect(owners.size).toBe(exactResources.wholeResources.length);
    expect(new Set(owners.values())).toEqual(new Set(["winner-operation"]));
    await expect(firstReceipt.accepted(identity)).resolves.not.toBeNull();
  });
});
