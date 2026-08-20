// @vitest-environment node

import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";
import { OFFLINE_RANGE_DATABASE, OFFLINE_RANGE_DATABASE_VERSION } from "./pair-cleanup-fence";
import { OFFLINE_WORKER_PROTOCOL } from "./contracts/policy";
import {
  createServiceWorkerClientAuthority,
  SERVICE_WORKER_AUTHORITY_PROTOCOL,
  SERVICE_WORKER_RANGE_DATABASE,
  SERVICE_WORKER_RANGE_DATABASE_VERSION,
} from "./service-worker-client-authority";

const pair = (build = "build-a", release = "release-a") => ({
  contractVersion: 1 as const, appBuildId: build, dataReleaseId: release,
});

class Port {
  peer?: Port;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  postMessage(data: unknown): void { queueMicrotask(() => this.peer?.onmessage?.({ data })); }
  close(): void { /* test port */ }
}
function channel(): MessageChannel {
  const port1 = new Port(); const port2 = new Port(); port1.peer = port2; port2.peer = port1;
  return { port1, port2 } as unknown as MessageChannel;
}

class Client {
  readonly type = "window";
  constructor(readonly id: string, readonly response: (message: Record<string, unknown>) => unknown | undefined) {}
  postMessage(message: unknown, transfer: Transferable[]): void {
    const value = this.response(message as Record<string, unknown>);
    if (value !== undefined) (transfer[0] as unknown as Port).postMessage(value);
  }
}

class Clients {
  values: Client[] = [];
  after?: Client[];
  calls = 0;
  async matchAll(): Promise<readonly Client[]> {
    this.calls += 1;
    return this.calls === 2 && this.after ? this.after : this.values;
  }
}

function leaseMessage(type: "acquire-lease" | "heartbeat-lease" | "release-lease", leaseId = "lease-a") {
  return { protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: `${type}-one`, leaseId, pair: pair() };
}

describe("source-bound service-worker client authority", () => {
  it("keeps duplicated worker protocol and database schema constants exact", () => {
    expect(SERVICE_WORKER_AUTHORITY_PROTOCOL).toBe(OFFLINE_WORKER_PROTOCOL);
    expect(SERVICE_WORKER_RANGE_DATABASE).toBe(OFFLINE_RANGE_DATABASE);
    expect(SERVICE_WORKER_RANGE_DATABASE_VERSION).toBe(OFFLINE_RANGE_DATABASE_VERSION);
  });

  it("atomically acquires, renews, and releases only for the exact event.source.id", async () => {
    const indexedDB = new IDBFactory(); const clients = new Clients(); let now = 1_000;
    const authority = createServiceWorkerClientAuthority(pair(), {
      indexedDB, clients, now: () => now, randomUUID: () => "challenge-one", createChannel: channel,
    });
    const sourceA = { id: "source-a", type: "window" };
    const sourceB = { id: "source-b", type: "window" };
    await expect(authority.message(leaseMessage("acquire-lease"), sourceA, 1)).resolves.toMatchObject({
      type: "lease-state", lease: { leaseId: "lease-a", expiresAtEpochMs: 121_000 },
    });
    await expect(authority.message(leaseMessage("heartbeat-lease"), sourceB, 1)).resolves.toMatchObject({
      type: "lease-refused", reason: "lease-mismatch",
    });
    now = 31_000;
    await expect(authority.message(leaseMessage("heartbeat-lease"), sourceA, 1)).resolves.toMatchObject({
      type: "lease-state", lease: { expiresAtEpochMs: 151_000 },
    });
    await expect(authority.message(leaseMessage("release-lease"), sourceB, 1)).resolves.toMatchObject({
      type: "lease-refused", reason: "lease-mismatch",
    });
    await expect(authority.message(leaseMessage("release-lease"), sourceA, 1)).resolves.toMatchObject({
      type: "lease-released", leaseId: "lease-a",
    });
  });

  it("refuses missing sources, extra ports, mismatched pairs, and cleanup-fenced activation", async () => {
    const indexedDB = new IDBFactory(); const authority = createServiceWorkerClientAuthority(pair(), {
      indexedDB, clients: new Clients(), now: () => 1_000, createChannel: channel,
    });
    await expect(authority.message(leaseMessage("acquire-lease"), null, 1)).resolves.toMatchObject({ reason: "source-unavailable" });
    await expect(authority.message(leaseMessage("acquire-lease"), { id: "source-a", type: "window" }, 2)).resolves.toMatchObject({ reason: "source-unavailable" });
    await expect(authority.message({ ...leaseMessage("acquire-lease"), pair: pair("other", "other") }, { id: "source-a", type: "window" }, 1)).resolves.toMatchObject({ reason: "pair-mismatch" });

    const first = await authority.message(leaseMessage("acquire-lease"), { id: "source-a", type: "window" }, 1);
    expect(first).toMatchObject({ type: "lease-state" });
    await authority.message(leaseMessage("release-lease"), { id: "source-a", type: "window" }, 1);
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const opened = indexedDB.open(OFFLINE_RANGE_DATABASE, OFFLINE_RANGE_DATABASE_VERSION);
      opened.onsuccess = () => resolve(opened.result); opened.onerror = () => reject(opened.error);
    });
    const tx = database.transaction("cleanup-fences", "readwrite");
    tx.objectStore("cleanup-fences").put({ pairKey: "build-a::release-a", pair: pair(), state: "cleanup-pending", createdAtEpochMs: 1_000 });
    await new Promise<void>((resolve) => { tx.oncomplete = () => resolve(); });
    database.close();
    await expect(authority.message(leaseMessage("acquire-lease", "lease-b"), { id: "source-a", type: "window" }, 1)).resolves.toMatchObject({ reason: "cleanup-pending" });
  });

  it("challenges a stable two-client census and binds active claims to durable source records", async () => {
    const indexedDB = new IDBFactory(); const clients = new Clients();
    const active = (message: Record<string, unknown>) => ({
      protocol: OFFLINE_WORKER_PROTOCOL, type: "lease-challenge-response",
      messageToken: message.messageToken, state: "active", pair: pair(), leaseId: "lease-a",
    });
    clients.values = [new Client("source-a", active), new Client("source-b", (message) => ({
      protocol: OFFLINE_WORKER_PROTOCOL, type: "lease-challenge-response",
      messageToken: message.messageToken, state: "inactive",
    }))];
    const authority = createServiceWorkerClientAuthority(pair(), {
      indexedDB, clients, now: () => 1_000, randomUUID: () => "challenge-one", createChannel: channel,
      setTimer: () => 1, clearTimer: () => undefined,
    });
    await authority.message(leaseMessage("acquire-lease"), { id: "source-a", type: "window" }, 1);
    await expect(authority.message({
      protocol: OFFLINE_WORKER_PROTOCOL, type: "request-client-census",
      messageToken: "census-one", targetPair: pair(),
    }, { id: "source-a", type: "window" }, 1)).resolves.toMatchObject({
      type: "client-census",
      observations: [{ clientId: "source-a", state: "active" }, { clientId: "source-b", state: "inactive" }],
    });
  });

  it("fails census closed when a client is unresponsive or the client set changes", async () => {
    const indexedDB = new IDBFactory(); const clients = new Clients();
    clients.values = [new Client("source-a", () => undefined)];
    const authority = createServiceWorkerClientAuthority(pair(), {
      indexedDB, clients, now: () => 1_000, randomUUID: () => "challenge-one", createChannel: channel,
      setTimer: (callback) => { queueMicrotask(callback); return 1; }, clearTimer: () => undefined,
    });
    await authority.message(leaseMessage("acquire-lease"), { id: "source-a", type: "window" }, 1);
    const request = { protocol: OFFLINE_WORKER_PROTOCOL, type: "request-client-census", messageToken: "census-one", targetPair: pair() };
    await expect(authority.message(request, { id: "source-a", type: "window" }, 1)).resolves.toMatchObject({
      type: "client-census", observations: [{ state: "unresponsive" }],
    });

    clients.calls = 0;
    clients.after = [clients.values[0]!, new Client("source-b", () => undefined)];
    await expect(authority.message(request, { id: "source-a", type: "window" }, 1)).resolves.toMatchObject({
      type: "census-refused", reason: "client-set-changed",
    });
  });
});
