// @vitest-environment node

import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";
import { validateAppReleasePair } from "./contracts/keys";
import {
  validateAppAuthority,
  validateRangeIdentity,
  validateWholeResourceAuthority,
  type RangeIdentityV1,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";
import {
  AdmissionReceiptError,
  assertAcceptedRangeResource,
  assertAcceptedWholeResource,
  coordinateVerifiedAdmission,
  createAdmissionPlanIdentity,
  createAdmissionReceiptStore,
} from "./admission-receipt";
import type { WholeResourceStore } from "./whole-resource-cache";
import type { RangeStore } from "./range-store";

const subtle = webcrypto.subtle as SubtleCrypto;
const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);
const pair = () => validateAppReleasePair({ contractVersion: 1, appBuildId: "build-a", dataReleaseId: "release-a" });
const app = (disposition: "synthetic-fixture" | "private-engineering" = "synthetic-fixture") => validateAppAuthority({
  contractVersion: 1,
  appBuildId: "build-a",
  dataReleaseId: "release-a",
  manifestUrl: "https://static.example/releases/release-a/manifest.json",
  releaseDisposition: disposition,
  precacheSetSha256: A,
});
const whole = (artifactId = "methodology", role = "methodology", path = "docs/methodology.json") =>
  validateWholeResourceAuthority({
    contractVersion: 1,
    authorityKind: "release-artifact",
    pair: pair(),
    artifactId,
    role,
    canonicalUrl: `https://static.example/releases/release-a/${path}`,
    path,
    mediaType: "application/json",
    byteSize: 5,
    sha256: B,
    etag: `"sha256-${B}"`,
  });
const range = (): RangeIdentityV1 => validateRangeIdentity({
  contractVersion: 1,
  authority: {
    contractVersion: 1,
    pair: pair(),
    artifactId: "projection-ssp2-45-2050-cog",
    role: "projection-analysis-cog",
    canonicalUrl: "https://static.example/releases/release-a/analysis/ssp2-45/2050.tif",
    path: "analysis/ssp2-45/2050.tif",
    mediaType: "image/tiff; application=geotiff; profile=cloud-optimized",
    totalByteSize: 4,
    artifactSha256: C,
    etag: `"sha256-${C}"`,
    integrityChunkSize: 4,
  },
  interval: { start: 0, endExclusive: 4 },
  authorizedIntervalSha256: A,
});

async function plan(wholeResources: readonly WholeResourceAuthorityV1[] = [whole()]) {
  return createAdmissionPlanIdentity({ pair: pair(), wholeResources, rangeResources: [range()], subtle });
}

function admissionStores(options: Readonly<{
  log?: string[];
  failWholeAdmission?: boolean;
  failWholeReadback?: boolean;
  abortAfterWholeAdmission?: AbortController;
}> = {}): { wholeStore: WholeResourceStore; rangeStore: RangeStore } {
  const wholeStore = {
    mode: "memory-only" as const,
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
      contractVersion: 1 as const, pair: pair(), verifiedEntries: 1, verifiedBytes: 5,
      missingEntries: 0, quarantinedEntries: 0, availableForDeclaredResources: true,
    }),
    close: () => undefined,
  } satisfies WholeResourceStore;
  const rangeStore = {
    mode: "memory-only" as const,
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
    readExactOrContaining: async () => {
      options.log?.push("range-readback");
      return new ArrayBuffer(4);
    },
    readAccepted: async () => new ArrayBuffer(4),
    acquireLease: async () => undefined,
    releaseLease: async () => undefined,
    setProtectedPairs: async () => undefined,
    inventory: async () => Object.freeze({
      mode: "memory-only" as const, payloadBytes: 4, entryCount: 1,
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
    operationId?: string;
    expectedPreviousReceiptSha256?: string | null;
    signal?: AbortSignal;
  }> = {},
) {
  const stores = admissionStores();
  return coordinateVerifiedAdmission({
    plan: identity,
    operationId: options.operationId ?? "operation-1",
    expectedPreviousReceiptSha256: options.expectedPreviousReceiptSha256 ?? null,
    wholeResources: options.wholeResources ?? [whole()],
    rangeWrites: [{ identity: range(), bytes: new ArrayBuffer(4) }],
    ...stores,
    receiptStore,
    subtle,
    signal: options.signal ?? new AbortController().signal,
  });
}

describe("verified coordinated-admission receipt v1", () => {
  it("derives one deterministic, order-independent exact resource-plan identity", async () => {
    const attribution = whole("attribution", "source-attribution", "docs/attribution.json");
    const first = await plan([whole(), attribution]);
    const second = await plan([attribution, whole()]);
    expect(first).toEqual(second);
    expect(first.wholeResources).toHaveLength(2);
    expect(first.rangeResources).toHaveLength(1);
    expect(first.resourcePlanSha256).toMatch(/^[0-9a-f]{64}$/u);
  });

  it("rejects duplicate, cross-pair, forged and PMTiles-shaped authorities", async () => {
    await expect(createAdmissionPlanIdentity({
      pair: pair(), wholeResources: [whole(), whole()], rangeResources: [], subtle,
    })).rejects.toMatchObject({ code: "AuthorityRejected" });
    const foreign = { ...whole(), pair: validateAppReleasePair({
      contractVersion: 1, appBuildId: "build-b", dataReleaseId: "release-a",
    }) } as WholeResourceAuthorityV1;
    await expect(createAdmissionPlanIdentity({
      pair: pair(), wholeResources: [foreign], rangeResources: [], subtle,
    })).rejects.toBeInstanceOf(AdmissionReceiptError);
    await expect(createAdmissionPlanIdentity({
      pair: pair(),
      wholeResources: [{ ...whole(), path: "layers/2050.pmtiles", mediaType: "application/vnd.pmtiles" } as WholeResourceAuthorityV1],
      rangeResources: [],
      subtle,
    })).rejects.toBeDefined();
  });

  it("publishes a memory-only receipt last and issues non-forgeable exact read gates", async () => {
    const identity = await plan();
    const store = createAdmissionReceiptStore(app("private-engineering"), subtle);
    const { gate } = await admit(identity, store);
    expect(store.mode).toBe("memory-only");
    await expect(assertAcceptedWholeResource(gate, whole(), subtle)).resolves.toBeUndefined();
    await expect(assertAcceptedRangeResource(gate, range(), subtle)).resolves.toBeUndefined();
    await expect(assertAcceptedWholeResource({ ...gate }, whole(), subtle)).rejects.toMatchObject({
      code: "AuthorityRejected",
    });
    await expect(store.publishLast({
      contractVersion: 1,
      plan: identity,
      operationId: "forged",
      expectedPreviousReceiptSha256: null,
    }, new AbortController().signal)).rejects.toMatchObject({ code: "AuthorityRejected" });
  });

  it("preserves the prior accepted receipt across cancellation and compare-and-swap conflict", async () => {
    const firstPlan = await plan();
    const secondPlan = await plan([whole(), whole("attribution", "source-attribution", "docs/attribution.json")]);
    const store = createAdmissionReceiptStore(app("private-engineering"), subtle);
    const first = await admit(firstPlan, store);
    const aborted = new AbortController();
    aborted.abort();
    await expect(admit(secondPlan, store, {
      wholeResources: [whole(), whole("attribution", "source-attribution", "docs/attribution.json")],
      operationId: "operation-2",
      signal: aborted.signal,
    })).rejects.toMatchObject({
      code: "Aborted",
    });
    await expect(admit(firstPlan, store, {
      operationId: "operation-2",
      expectedPreviousReceiptSha256: "f".repeat(64),
    })).rejects.toMatchObject({
      code: "Conflict",
    });
    await expect(store.accepted(firstPlan)).resolves.toMatchObject({ receiptSha256: first.gate.receiptSha256 });
    await expect(store.accepted(secondPlan)).resolves.toBeNull();
  });

  it("persists and revalidates an exact receipt across store instances", async () => {
    const factory = new IDBFactory();
    const identity = await plan();
    const firstStore = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory });
    const published = await admit(identity, firstStore);
    firstStore.close();
    const reopened = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory });
    await expect(reopened.accepted(identity)).resolves.toMatchObject({ receiptSha256: published.gate.receiptSha256 });
    reopened.close();
  });

  it("treats tampered persisted receipt bytes as absent authority", async () => {
    const factory = new IDBFactory();
    const identity = await plan();
    const store = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory });
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
    const reopened = createAdmissionReceiptStore(app(), subtle, { indexedDB: factory });
    await expect(reopened.accepted(identity)).resolves.toBeNull();
    reopened.close();
  });

  it("deletes only the exact current receipt and cannot delete through a copied gate", async () => {
    const identity = await plan();
    const store = createAdmissionReceiptStore(app("private-engineering"), subtle);
    const { gate } = await admit(identity, store);
    await expect(store.deleteIfCurrent({ ...gate })).rejects.toMatchObject({ code: "AuthorityRejected" });
    await expect(store.deleteIfCurrent(gate)).resolves.toBe(true);
    await expect(store.accepted(identity)).resolves.toBeNull();
  });

  it("stores only resource authority aggregates and no scientific or personal state", async () => {
    const identity = await plan();
    const store = createAdmissionReceiptStore(app("private-engineering"), subtle);
    const { gate } = await admit(identity, store);
    expect(JSON.stringify({ identity, gate })).not.toMatch(
      /ProjectionAvailable|DataUnavailable|OutOfScope|UnsupportedGeography|latitude|longitude|query|placeId/u,
    );
  });

  it("publishes the verified receipt strictly after both admissions and exact readback", async () => {
    const identity = await plan();
    const log: string[] = [];
    const stores = admissionStores({ log });
    const receipts = createAdmissionReceiptStore(app("private-engineering"), subtle);
    const loggedReceipts = {
      mode: receipts.mode,
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
      operationId: "ordered-operation",
      expectedPreviousReceiptSha256: null,
      wholeResources: [whole()],
      rangeWrites: [{ identity: range(), bytes: new ArrayBuffer(4) }],
      ...stores,
      receiptStore: loggedReceipts,
      subtle,
      signal: new AbortController().signal,
    });
    expect(log).toEqual([
      "range-admit", "whole-admit", "whole-readback", "range-readback", "receipt-publish",
    ]);
  });

  it("rolls back range ownership when whole admission fails and publishes no receipt", async () => {
    const identity = await plan();
    const log: string[] = [];
    const stores = admissionStores({ log, failWholeAdmission: true });
    const receipts = createAdmissionReceiptStore(app("private-engineering"), subtle);
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      operationId: "failed-operation",
      expectedPreviousReceiptSha256: null,
      wholeResources: [whole()],
      rangeWrites: [{ identity: range(), bytes: new ArrayBuffer(4) }],
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
    const log: string[] = [];
    const stores = admissionStores({ log, failWholeReadback: true });
    const receipts = createAdmissionReceiptStore(app("private-engineering"), subtle);
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      operationId: "readback-failure",
      expectedPreviousReceiptSha256: null,
      wholeResources: [whole()],
      rangeWrites: [{ identity: range(), bytes: new ArrayBuffer(4) }],
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
    const log: string[] = [];
    const controller = new AbortController();
    const stores = admissionStores({ log, abortAfterWholeAdmission: controller });
    const receipts = createAdmissionReceiptStore(app("private-engineering"), subtle);
    await expect(coordinateVerifiedAdmission({
      plan: identity,
      operationId: "cancelled-operation",
      expectedPreviousReceiptSha256: null,
      wholeResources: [whole()],
      rangeWrites: [{ identity: range(), bytes: new ArrayBuffer(4) }],
      ...stores,
      receiptStore: receipts,
      subtle,
      signal: controller.signal,
    })).rejects.toMatchObject({ code: "Aborted" });
    expect(log).toEqual(["range-admit", "whole-admit", "whole-rollback", "range-rollback"]);
    await expect(receipts.accepted(identity)).resolves.toBeNull();
  });
});
