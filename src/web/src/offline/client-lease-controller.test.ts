import { describe, expect, it, vi } from "vitest";

import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import type { ClientLeaseV1 } from "./contracts/policy";
import {
  ClientLeaseUnavailableError,
  createClientLeaseController,
  type ClientLeaseLifecyclePort,
  type ClientLeaseStorePort,
  type RepeatingTimerPort,
} from "./client-lease-controller";

const pair = (): AppReleasePairV1 => validateAppReleasePair({
  contractVersion: 1,
  appBuildId: "build-a",
  dataReleaseId: "release-a",
});

class LeaseStore implements ClientLeaseStorePort {
  readonly active = new Map<string, ClientLeaseV1>();
  readonly acquired: ClientLeaseV1[] = [];
  readonly released: ClientLeaseV1[] = [];
  readonly activated: ClientLeaseV1[] = [];

  async activateClientLease(lease: ClientLeaseV1): Promise<void> {
    this.activated.push(lease);
    this.active.set(lease.leaseId, lease);
  }

  async acquireLease(lease: ClientLeaseV1): Promise<void> {
    this.acquired.push(lease);
    this.active.set(lease.leaseId, lease);
  }

  async releaseLease(lease: ClientLeaseV1): Promise<void> {
    this.released.push(lease);
    this.active.delete(lease.leaseId);
  }

}

class Timer implements RepeatingTimerPort {
  readonly callbacks = new Map<number, () => void>();
  readonly intervals: number[] = [];
  #next = 1;

  set(callback: () => void, milliseconds: number): number {
    const id = this.#next++;
    this.callbacks.set(id, callback);
    this.intervals.push(milliseconds);
    return id;
  }

  clear(id: number): void { this.callbacks.delete(id); }

  tick(): void {
    for (const callback of [...this.callbacks.values()]) callback();
  }
}

class Lifecycle implements ClientLeaseLifecyclePort {
  readonly listeners = new Set<() => void>();
  addPageHideListener(listener: () => void): void { this.listeners.add(listener); }
  removePageHideListener(listener: () => void): void { this.listeners.delete(listener); }
  pageHide(): void { for (const listener of [...this.listeners]) listener(); }
}

function deferred(): Readonly<{ promise: Promise<void>; resolve: () => void }> {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("production client lease controller", () => {
  it("acquires immediately, protects the active pair, and renews every 30 seconds with a 120 second TTL", async () => {
    const store = new LeaseStore();
    const timer = new Timer();
    let now = 1_000;
    const controller = createClientLeaseController({
      pair: pair(), store, timer, lifecycle: new Lifecycle(),
      now: () => now, randomUUID: () => "11111111-1111-4111-8111-111111111111",
    });

    await controller.start();
    expect(store.activated).toEqual([expect.objectContaining({
      leaseId: "client-11111111-1111-4111-8111-111111111111",
      expiresAtEpochMs: 121_000,
    })]);
    expect(store.acquired).toEqual([]);
    expect(timer.intervals).toEqual([30_000]);

    now = 31_000;
    timer.tick();
    await controller.settled();
    expect(store.acquired.at(-1)).toEqual(expect.objectContaining({ expiresAtEpochMs: 151_000 }));
  });

  it("isolates two tabs and releases only the tab that closes", async () => {
    const store = new LeaseStore();
    const firstLifecycle = new Lifecycle();
    const first = createClientLeaseController({
      pair: pair(), store, timer: new Timer(), lifecycle: firstLifecycle,
      now: () => 1_000, randomUUID: () => "11111111-1111-4111-8111-111111111111",
    });
    const second = createClientLeaseController({
      pair: pair(), store, timer: new Timer(), lifecycle: new Lifecycle(),
      now: () => 1_000, randomUUID: () => "22222222-2222-4222-8222-222222222222",
    });

    await Promise.all([first.start(), second.start()]);
    expect([...store.active.keys()]).toEqual([
      "client-11111111-1111-4111-8111-111111111111",
      "client-22222222-2222-4222-8222-222222222222",
    ]);

    firstLifecycle.pageHide();
    await first.settled();
    expect([...store.active.keys()]).toEqual(["client-22222222-2222-4222-8222-222222222222"]);
  });

  it("coalesces concurrent starts and releases a lease acquired while close is pending", async () => {
    const store = new LeaseStore();
    const activation = deferred();
    const original = store.activateClientLease.bind(store);
    vi.spyOn(store, "activateClientLease").mockImplementation(async (lease) => {
      await activation.promise;
      await original(lease);
    });
    const controller = createClientLeaseController({
      pair: pair(), store, timer: new Timer(), lifecycle: new Lifecycle(),
      now: () => 1_000, randomUUID: () => "11111111-1111-4111-8111-111111111111",
    });

    const first = controller.start();
    const second = controller.start();
    const closing = controller.close();
    activation.resolve();
    await Promise.all([first, second, closing]);

    expect(store.activated).toHaveLength(1);
    expect(store.released).toHaveLength(1);
    expect(store.active.size).toBe(0);
    expect(() => controller.assertActive()).toThrow(ClientLeaseUnavailableError);
  });

  it("does not let an in-flight heartbeat reacquire after orderly close", async () => {
    const store = new LeaseStore();
    const timer = new Timer();
    const pending = deferred();
    const started = deferred();
    const acquire = vi.spyOn(store, "acquireLease");
    acquire.mockImplementationOnce(async (lease) => {
      started.resolve();
      await pending.promise;
      store.active.set(lease.leaseId, lease);
    });
    const controller = createClientLeaseController({
      pair: pair(), store, timer, lifecycle: new Lifecycle(),
      now: () => 1_000, randomUUID: () => "11111111-1111-4111-8111-111111111111",
    });

    await controller.start();
    timer.tick();
    await started.promise;
    const closing = controller.close();
    pending.resolve();
    await closing;
    expect(store.active).toEqual(new Map());
    expect(store.released).toHaveLength(1);
  });

  it("reports a pagehide release failure without creating an unhandled lifecycle rejection", async () => {
    const store = new LeaseStore();
    const lifecycle = new Lifecycle();
    const onHeartbeatFailure = vi.fn();
    vi.spyOn(store, "releaseLease").mockRejectedValue(new Error("release failed"));
    const controller = createClientLeaseController({
      pair: pair(), store, timer: new Timer(), lifecycle,
      now: () => 1_000, randomUUID: () => "11111111-1111-4111-8111-111111111111",
      onHeartbeatFailure,
    });

    await controller.start();
    lifecycle.pageHide();
    await controller.settled();
    await vi.waitFor(() => expect(onHeartbeatFailure).toHaveBeenCalledWith(expect.any(Error)));
  });

  it("fails closed after one heartbeat renewal failure and still permits orderly release", async () => {
    const store = new LeaseStore();
    const timer = new Timer();
    const lifecycle = new Lifecycle();
    const onHeartbeatFailure = vi.fn();
    vi.spyOn(store, "acquireLease").mockRejectedValue(new Error("renewal failed"));
    const controller = createClientLeaseController({
      pair: pair(), store, timer, lifecycle,
      now: () => 1_000, randomUUID: () => "11111111-1111-4111-8111-111111111111",
      onHeartbeatFailure,
    });

    await controller.start();
    timer.tick();
    await controller.settled();
    expect(() => controller.assertActive()).toThrow(ClientLeaseUnavailableError);
    expect(timer.callbacks.size).toBe(0);
    lifecycle.pageHide();
    await vi.waitFor(() => expect(store.released).toHaveLength(1));
    expect(onHeartbeatFailure).toHaveBeenCalledWith(expect.any(Error));
  });

  it("performs no storage, timer, lifecycle, or UUID work for local Candidate mode", async () => {
    const store = new LeaseStore();
    const timer = new Timer();
    const lifecycle = new Lifecycle();
    const randomUUID = vi.fn(() => "11111111-1111-4111-8111-111111111111");
    const controller = createClientLeaseController({
      pair: pair(), store, timer, lifecycle, now: () => 1_000, randomUUID,
      persistence: "memory-only",
    });

    await controller.start();
    await controller.close();
    expect(store.acquired).toEqual([]);
    expect(store.released).toEqual([]);
    expect(store.activated).toEqual([]);
    expect(timer.callbacks.size).toBe(0);
    expect(lifecycle.listeners.size).toBe(0);
    expect(randomUUID).not.toHaveBeenCalled();
  });

  it("fails startup closed and leaves no timer when active-pair protection or initial acquisition fails", async () => {
    const timer = new Timer();
    const acquisitionFailure = new LeaseStore();
    vi.spyOn(acquisitionFailure, "activateClientLease").mockRejectedValue(new Error("blocked"));
    await expect(createClientLeaseController({
      pair: pair(), store: acquisitionFailure, timer, lifecycle: new Lifecycle(),
      now: () => 1_000, randomUUID: () => "22222222-2222-4222-8222-222222222222",
    }).start()).rejects.toThrow("blocked");
    expect(timer.callbacks.size).toBe(0);
  });
});
