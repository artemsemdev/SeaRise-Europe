import type { AppReleasePairV1 } from "./contracts/keys";
import {
  PairLifecycleStoreError,
  type LifecycleInventoryV1,
  type PairLifecycleStore,
  type RemovedPairV1,
} from "./pair-lifecycle-store";

export type ProductionRetentionStateV1 =
  | Readonly<{
    contractVersion: 1;
    state: "complete";
    activePair: AppReleasePairV1;
    previousPair: AppReleasePairV1 | null;
    removedPairs: readonly AppReleasePairV1[];
  }>
  | Readonly<{
    contractVersion: 1;
    state: "retryable-technical-failure";
    activePair: AppReleasePairV1;
    pendingPairs: readonly AppReleasePairV1[];
    removedPairs: readonly AppReleasePairV1[];
    retryable: true;
    reason: string;
  }>;

export interface ProductionRetentionStore {
  inventory(): Promise<LifecycleInventoryV1>;
  removeExactPair(pair: AppReleasePairV1): Promise<RemovedPairV1>;
}

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}

function completeIdentity(record: LifecycleInventoryV1["records"][number]): boolean {
  return record.acceptedIdentity.precacheSetSha256 !== null &&
    record.acceptedIdentity.resourcePlanSha256 !== null && record.acceptedIdentity.receiptSha256 !== null;
}

function pending(inventory: LifecycleInventoryV1): readonly AppReleasePairV1[] {
  return Object.freeze(inventory.records
    .filter(({ state }) => state === "cleanup-pending")
    .map(({ pair }) => pair));
}

/**
 * Runs only after the caller proves the exact fresh-boot controller and
 * admitted resource authority. Physical deletion remains guarded by the
 * lifecycle store's per-pair Web Lock, cleanup fence, stored leases, and
 * current-worker client census.
 */
export class ProductionRetentionCoordinator {
  readonly #store: ProductionRetentionStore;
  #state: ProductionRetentionStateV1 | null = null;

  constructor(store: ProductionRetentionStore | PairLifecycleStore) {
    this.#store = store;
  }

  state(): ProductionRetentionStateV1 | null {
    return this.#state;
  }

  async reconcile(activePair: AppReleasePairV1): Promise<ProductionRetentionStateV1> {
    const removedPairs: AppReleasePairV1[] = [];
    let inventory: LifecycleInventoryV1;
    try {
      inventory = await this.#store.inventory();
      const active = inventory.records.filter(({ state }) => state === "active");
      const previous = inventory.records.filter(({ state }) => state === "previous");
      if (inventory.corruptRecordCount !== 0 || active.length !== 1 ||
          !samePair(active[0]!.pair, activePair) || !completeIdentity(active[0]!) ||
          previous.length > 1 || previous.some((record) => !completeIdentity(record))) {
        throw new PairLifecycleStoreError(
          "CleanupBlocked",
          "Retention authority is incomplete, corrupt, or does not match the exact fresh-boot active pair.",
        );
      }

      for (const pair of pending(inventory)) {
        await this.#store.removeExactPair(pair);
        removedPairs.push(pair);
      }
      this.#state = Object.freeze({
        contractVersion: 1,
        state: "complete",
        activePair: active[0]!.pair,
        previousPair: previous[0]?.pair ?? null,
        removedPairs: Object.freeze(removedPairs),
      });
      return this.#state;
    } catch (error) {
      let pendingPairs: readonly AppReleasePairV1[] = [];
      try { pendingPairs = pending(await this.#store.inventory()); } catch { /* Preserve the first technical failure. */ }
      const reason = error instanceof Error ? error.message : "Production retention reconciliation failed.";
      this.#state = Object.freeze({
        contractVersion: 1,
        state: "retryable-technical-failure",
        activePair,
        pendingPairs,
        removedPairs: Object.freeze(removedPairs),
        retryable: true,
        reason,
      });
      return this.#state;
    }
  }
}
