import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import { validateClientLease, type ClientLeaseV1 } from "./contracts/policy";

export const CLIENT_LEASE_TTL_MS = 120_000;
export const CLIENT_LEASE_HEARTBEAT_MS = 30_000;

export interface ClientLeaseStorePort {
  activateClientLease(lease: ClientLeaseV1): Promise<void>;
  acquireLease(lease: ClientLeaseV1): Promise<void>;
  releaseLease(lease: ClientLeaseV1): Promise<void>;
}

export interface RepeatingTimerPort {
  set(callback: () => void, milliseconds: number): number;
  clear(id: number): void;
}

export interface ClientLeaseLifecyclePort {
  addPageHideListener(listener: () => void): void;
  removePageHideListener(listener: () => void): void;
}

export interface ClientLeaseControllerOptions {
  readonly pair: AppReleasePairV1;
  readonly store: ClientLeaseStorePort;
  readonly timer?: RepeatingTimerPort;
  readonly lifecycle?: ClientLeaseLifecyclePort;
  readonly now?: () => number;
  readonly randomUUID?: () => string;
  readonly persistence?: "persistent" | "memory-only";
  readonly onHeartbeatFailure?: (error: unknown) => void;
}

export interface ClientLeaseController {
  readonly mode: "persistent" | "memory-only";
  start(): Promise<void>;
  close(): Promise<void>;
  settled(): Promise<void>;
  assertActive(): void;
}

export class ClientLeaseUnavailableError extends Error {
  constructor(message = "The persistent client lease is not active.") {
    super(message);
    this.name = "ClientLeaseUnavailableError";
  }
}

function browserTimer(): RepeatingTimerPort {
  return {
    set: (callback, milliseconds) => globalThis.setInterval(callback, milliseconds) as unknown as number,
    clear: (id) => globalThis.clearInterval(id),
  };
}

function browserLifecycle(): ClientLeaseLifecyclePort {
  return {
    addPageHideListener: (listener) => globalThis.addEventListener("pagehide", listener),
    removePageHideListener: (listener) => globalThis.removeEventListener("pagehide", listener),
  };
}

function exactLease(pair: AppReleasePairV1, leaseId: string, now: number): ClientLeaseV1 {
  if (!Number.isSafeInteger(now) || now < 0 || now > Number.MAX_SAFE_INTEGER - CLIENT_LEASE_TTL_MS) {
    throw new TypeError("Client lease clock is invalid.");
  }
  return validateClientLease({
    contractVersion: 1,
    leaseId,
    pair,
    expiresAtEpochMs: now + CLIENT_LEASE_TTL_MS,
    state: "active",
  });
}

export function createClientLeaseController(options: ClientLeaseControllerOptions): ClientLeaseController {
  const mode = options.persistence ?? "persistent";
  if (mode === "memory-only") {
    return Object.freeze({
      mode,
      start: async () => undefined,
      close: async () => undefined,
      settled: async () => undefined,
      assertActive: () => undefined,
    });
  }

  const pair = validateAppReleasePair(options.pair);
  const timer = options.timer ?? browserTimer();
  const lifecycle = options.lifecycle ?? browserLifecycle();
  const now = options.now ?? Date.now;
  const randomUUID = options.randomUUID ?? (() => globalThis.crypto.randomUUID());
  let state: "new" | "starting" | "active" | "failed" | "closing" | "closed" = "new";
  let generation = 0;
  let interval: number | undefined;
  let lease: ClientLeaseV1 | undefined;
  let tail = Promise.resolve();
  let startPromise: Promise<void> | undefined;
  let closePromise: Promise<void> | undefined;
  let closeRequested = false;

  const reportFailure = (error: unknown): void => { options.onHeartbeatFailure?.(error); };
  const pageHide = (): void => { void close().catch(reportFailure); };

  const enqueue = (operation: () => Promise<void>): Promise<void> => {
    const next = tail.then(operation, operation);
    tail = next.catch(() => undefined);
    return next;
  };

  const renew = (): void => {
    if (state !== "active" || !lease) return;
    const expectedGeneration = generation;
    const current = lease;
    void enqueue(async () => {
      if (state !== "active" || generation !== expectedGeneration) return;
      const next = exactLease(pair, current.leaseId, now());
      try {
        await options.store.acquireLease(next);
        if (state === "active" && generation === expectedGeneration) lease = next;
      } catch (error) {
        if (state === "active" && generation === expectedGeneration) {
          state = "failed";
          generation += 1;
          if (interval !== undefined) {
            try { timer.clear(interval); } catch (timerError) { reportFailure(timerError); }
          }
          interval = undefined;
        }
        reportFailure(error);
      }
    });
  };

  const start = async (): Promise<void> => {
    if (state === "active") return;
    if (state === "starting" && startPromise) return startPromise;
    if (state !== "new") throw new ClientLeaseUnavailableError("A stopped client lease controller cannot be restarted.");
    state = "starting";
    const nextLease = exactLease(pair, `client-${randomUUID()}`, now());
    startPromise = (async () => {
      try {
        await options.store.activateClientLease(nextLease);
        lease = nextLease;
        if (closeRequested) return;
        state = "active";
        lifecycle.addPageHideListener(pageHide);
        interval = timer.set(renew, CLIENT_LEASE_HEARTBEAT_MS);
      } catch (error) {
        state = "failed";
        throw error;
      }
    })();
    return startPromise;
  };

  const close = async (): Promise<void> => {
    closeRequested = true;
    if (closePromise) return closePromise;
    if (state === "closed") return tail;
    if (state === "new") {
      state = "closed";
      return;
    }
    closePromise = (async () => {
      await startPromise?.catch(() => undefined);
      state = "closing";
      generation += 1;
      try { lifecycle.removePageHideListener(pageHide); } catch (error) { reportFailure(error); }
      if (interval !== undefined) {
        try { timer.clear(interval); } catch (error) { reportFailure(error); }
      }
      interval = undefined;
      const current = lease;
      await enqueue(async () => {
        try {
          if (current) await options.store.releaseLease(current);
        } finally {
          lease = undefined;
          state = "closed";
        }
      });
    })();
    return closePromise;
  };

  return Object.freeze({
    mode,
    start,
    close,
    settled: async () => {
      if (closePromise) {
        await closePromise.catch(() => undefined);
        return;
      }
      await startPromise?.catch(() => undefined);
      await tail;
    },
    assertActive: () => {
      if (state !== "active") throw new ClientLeaseUnavailableError();
    },
  });
}
