import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import { validateClientLease, type ClientLeaseV1 } from "./contracts/policy";

export const CLIENT_LEASE_TTL_MS = 120_000;
export const CLIENT_LEASE_HEARTBEAT_MS = 30_000;

export interface ClientLeaseStorePort {
  activateClientLease(identity: ClientLeaseIdentityV1): Promise<ClientLeaseV1>;
  acquireLease(identity: ClientLeaseIdentityV1): Promise<ClientLeaseV1>;
  releaseLease(identity: ClientLeaseIdentityV1): Promise<void>;
}

export interface ClientLeaseIdentityV1 {
  readonly pair: AppReleasePairV1;
  readonly leaseId: string;
}

export interface RepeatingTimerPort {
  set(callback: () => void, milliseconds: number): number;
  clear(id: number): void;
}

export interface ClientLeaseLifecyclePort {
  addPageHideListener(listener: (event: Readonly<{ persisted: boolean }>) => void): void;
  removePageHideListener(listener: (event: Readonly<{ persisted: boolean }>) => void): void;
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
  observation(): Readonly<{ state: "inactive" } | { state: "active"; pair: AppReleasePairV1; leaseId: string }>;
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
    addPageHideListener: (listener) => globalThis.addEventListener("pagehide", listener as unknown as EventListener),
    removePageHideListener: (listener) => globalThis.removeEventListener("pagehide", listener as unknown as EventListener),
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
      observation: () => Object.freeze({ state: "inactive" as const }),
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
  const pageHide = ({ persisted }: Readonly<{ persisted: boolean }>): void => {
    if (!persisted) void close().catch(reportFailure);
  };

  const failClosed = (error: unknown): void => {
    if (state !== "active") return;
    state = "failed";
    generation += 1;
    if (interval !== undefined) {
      try { timer.clear(interval); } catch (timerError) { reportFailure(timerError); }
    }
    interval = undefined;
    reportFailure(error);
  };

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
      try {
        const timestamp = now();
        if (!Number.isSafeInteger(timestamp) || timestamp >= current.expiresAtEpochMs) {
          failClosed(new ClientLeaseUnavailableError("The persistent client lease expired before renewal."));
          return;
        }
        const next = validateClientLease(await options.store.acquireLease({ pair, leaseId: current.leaseId }));
        const acceptedAt = now();
        if (next.leaseId !== current.leaseId || next.pair.appBuildId !== pair.appBuildId ||
            next.pair.dataReleaseId !== pair.dataReleaseId || next.expiresAtEpochMs <= acceptedAt ||
            next.expiresAtEpochMs > acceptedAt + CLIENT_LEASE_TTL_MS) {
          throw new ClientLeaseUnavailableError("The worker returned an invalid lease renewal.");
        }
        if (state === "active" && generation === expectedGeneration) lease = next;
      } catch (error) {
        if (state === "active" && generation === expectedGeneration) failClosed(error);
      }
    });
  };

  const start = async (): Promise<void> => {
    if (state === "active") return;
    if (state === "starting" && startPromise) return startPromise;
    if (state !== "new") throw new ClientLeaseUnavailableError("A stopped client lease controller cannot be restarted.");
    state = "starting";
    const timestamp = now();
    const leaseId = exactLease(pair, `client-${randomUUID()}`, timestamp).leaseId;
    startPromise = (async () => {
      try {
        const activated = validateClientLease(await options.store.activateClientLease({ pair, leaseId }));
        const acceptedAt = now();
        if (activated.leaseId !== leaseId || activated.pair.appBuildId !== pair.appBuildId ||
            activated.pair.dataReleaseId !== pair.dataReleaseId || activated.expiresAtEpochMs <= acceptedAt ||
            activated.expiresAtEpochMs > acceptedAt + CLIENT_LEASE_TTL_MS) {
          throw new ClientLeaseUnavailableError("The worker returned an invalid initial lease.");
        }
        lease = activated;
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
          if (current) await options.store.releaseLease({ pair, leaseId: current.leaseId });
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
      if (state === "active" && lease) {
        let timestamp: number;
        try { timestamp = now(); } catch (error) {
          failClosed(error);
          throw new ClientLeaseUnavailableError("The persistent client lease clock failed.");
        }
        if (Number.isSafeInteger(timestamp) && timestamp < lease.expiresAtEpochMs) return;
        failClosed(new ClientLeaseUnavailableError("The persistent client lease expired."));
      }
      throw new ClientLeaseUnavailableError();
    },
    observation: () => {
      try {
        if (state === "active" && lease) {
          const timestamp = now();
          if (Number.isSafeInteger(timestamp) && timestamp < lease.expiresAtEpochMs) {
            return Object.freeze({ state: "active" as const, pair, leaseId: lease.leaseId });
          }
        }
      } catch { /* Fail closed below. */ }
      return Object.freeze({ state: "inactive" as const });
    },
  });
}
