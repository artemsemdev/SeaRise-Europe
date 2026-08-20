// @vitest-environment node

import { describe, expect, it } from "vitest";
import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import type {
  LifecycleInventoryV1,
  PairLifecycleRecordV1,
  RemovedPairV1,
} from "./pair-lifecycle-store";
import {
  ProductionRetentionCoordinator,
  type ProductionRetentionStore,
} from "./production-retention-coordinator";

const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);

function pair(index: string): AppReleasePairV1 {
  return validateAppReleasePair({ contractVersion: 1, appBuildId: `build-${index}`, dataReleaseId: `release-${index}` });
}

function record(value: AppReleasePairV1, state: PairLifecycleRecordV1["state"]): PairLifecycleRecordV1 {
  const complete = ["core-complete", "active", "previous", "cleanup-pending"].includes(state);
  return Object.freeze({
    contractVersion: 1,
    pair: value,
    state,
    acceptedIdentity: Object.freeze({
      precacheSetSha256: complete ? A : null,
      resourcePlanSha256: complete ? B : null,
      receiptSha256: complete ? C : null,
    }),
    lastFailure: null,
  });
}

class RetentionStore implements ProductionRetentionStore {
  records: PairLifecycleRecordV1[];
  corruptRecordCount = 0;
  readonly attempts: string[] = [];
  failOnce = new Set<string>();

  constructor(records: PairLifecycleRecordV1[]) {
    this.records = records;
  }

  async inventory(): Promise<LifecycleInventoryV1> {
    return Object.freeze({
      contractVersion: 1,
      records: Object.freeze([...this.records]),
      corruptRecordCount: this.corruptRecordCount,
    });
  }

  async removeExactPair(target: AppReleasePairV1): Promise<RemovedPairV1> {
    this.attempts.push(target.appBuildId);
    if (this.failOnce.delete(target.appBuildId)) throw new Error("Client census is temporarily unresponsive.");
    this.records = this.records.filter(({ pair: value }) => value.appBuildId !== target.appBuildId);
    return Object.freeze({
      contractVersion: 1,
      pair: target,
      state: "removed",
      removed: Object.freeze({ receiptRecords: 0, authorityRecords: 0, cacheNamespaces: 0, rangeRecords: 0 }),
    });
  }
}

describe("production retention coordinator", () => {
  it("removes only A after A/B/C rotation and preserves exact C active plus B recovery", async () => {
    const first = pair("a");
    const previous = pair("b");
    const active = pair("c");
    const store = new RetentionStore([
      record(first, "cleanup-pending"),
      record(previous, "previous"),
      record(active, "active"),
    ]);

    await expect(new ProductionRetentionCoordinator(store).reconcile(active)).resolves.toEqual({
      contractVersion: 1,
      state: "complete",
      activePair: active,
      previousPair: previous,
      removedPairs: [first],
    });
    expect(store.records).toEqual([record(previous, "previous"), record(active, "active")]);
  });

  it("fails closed for mismatched, corrupt, or incomplete active authority", async () => {
    const active = pair("active");
    const pending = pair("pending");
    const store = new RetentionStore([record(pending, "cleanup-pending"), record(active, "active")]);
    store.corruptRecordCount = 1;

    await expect(new ProductionRetentionCoordinator(store).reconcile(pair("other"))).resolves.toMatchObject({
      state: "retryable-technical-failure",
      activePair: pair("other"),
      pendingPairs: [pending],
      removedPairs: [],
      retryable: true,
      reason: expect.stringContaining("incomplete, corrupt, or does not match"),
    });
    expect(store.attempts).toEqual([]);
  });

  it("reports partial deletion honestly and retries remaining pairs idempotently", async () => {
    const first = pair("a");
    const second = pair("b");
    const active = pair("d");
    const store = new RetentionStore([
      record(first, "cleanup-pending"), record(second, "cleanup-pending"), record(active, "active"),
    ]);
    store.failOnce.add(second.appBuildId);
    const coordinator = new ProductionRetentionCoordinator(store);

    await expect(coordinator.reconcile(active)).resolves.toMatchObject({
      state: "retryable-technical-failure",
      pendingPairs: [second],
      removedPairs: [first],
      retryable: true,
      reason: "Client census is temporarily unresponsive.",
    });
    await expect(coordinator.reconcile(active)).resolves.toMatchObject({
      state: "complete", removedPairs: [second], previousPair: null,
    });
    await expect(coordinator.reconcile(active)).resolves.toMatchObject({
      state: "complete", removedPairs: [], previousPair: null,
    });
    expect(store.attempts).toEqual([first.appBuildId, second.appBuildId, second.appBuildId]);
  });
});
