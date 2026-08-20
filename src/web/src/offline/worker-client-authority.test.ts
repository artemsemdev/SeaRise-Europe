// @vitest-environment node

import { describe, expect, it } from "vitest";
import { createWorkerClientAuthority } from "./worker-client-authority";
import { OFFLINE_WORKER_PROTOCOL } from "./contracts/policy";
import { validateAppReleasePair } from "./contracts/keys";

const pair = validateAppReleasePair({ contractVersion: 1, appBuildId: "build-a", dataReleaseId: "release-a" });

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

class Container {
  listener?: (event: { data: unknown; source: unknown; ports: readonly MessagePort[] }) => void;
  addEventListener(_type: "message", listener: typeof this.listener): void { this.listener = listener; }
}

describe("window service-worker client authority port", () => {
  it("round-trips exact lease and census authority and answers only the exact worker challenge", async () => {
    const container = new Container(); let expiry = 121_000;
    const worker = {
      postMessage(message: unknown, transfer: Transferable[]) {
        const request = message as Record<string, unknown>;
        const port = transfer[0] as unknown as Port;
        if (request.type === "release-lease") port.postMessage({
          protocol: OFFLINE_WORKER_PROTOCOL, type: "lease-released",
          messageToken: request.messageToken, pair, leaseId: request.leaseId,
        });
        else if (request.type === "request-client-census") port.postMessage({
          protocol: OFFLINE_WORKER_PROTOCOL, type: "client-census",
          messageToken: request.messageToken, targetPair: request.targetPair,
          observations: [{ clientId: "source-a", state: "inactive" }],
        });
        else port.postMessage({
          protocol: OFFLINE_WORKER_PROTOCOL, type: "lease-state", messageToken: request.messageToken,
          lease: { contractVersion: 1, leaseId: request.leaseId, pair, expiresAtEpochMs: expiry, state: "active" },
        });
      },
    };
    const authority = createWorkerClientAuthority(worker, container, {
      randomUUID: () => "request-one", createChannel: channel,
      setTimer: () => 1, clearTimer: () => undefined,
    });
    authority.attachObservation(() => ({ state: "active", pair, leaseId: "lease-a" }));
    await expect(authority.activateClientLease({ pair, leaseId: "lease-a" })).resolves.toMatchObject({ expiresAtEpochMs: 121_000 });
    expiry = 151_000;
    await expect(authority.acquireLease({ pair, leaseId: "lease-a" })).resolves.toMatchObject({ expiresAtEpochMs: 151_000 });
    await expect(authority.releaseLease({ pair, leaseId: "lease-a" })).resolves.toBeUndefined();
    await expect(authority.observe(pair, new AbortController().signal)).resolves.toEqual([{ clientId: "source-a", state: "inactive" }]);

    const challenge = channel();
    let response: unknown;
    challenge.port1.onmessage = ({ data }) => { response = data; };
    container.listener?.({
      source: worker,
      ports: [challenge.port2],
      data: { protocol: OFFLINE_WORKER_PROTOCOL, type: "lease-challenge", messageToken: "challenge-one", targetPair: pair },
    });
    await new Promise<void>((resolve) => queueMicrotask(() => resolve()));
    expect(response).toMatchObject({ type: "lease-challenge-response", state: "active", leaseId: "lease-a" });

    response = undefined;
    container.listener?.({
      source: {}, ports: [challenge.port2],
      data: { protocol: OFFLINE_WORKER_PROTOCOL, type: "lease-challenge", messageToken: "challenge-two", targetPair: pair },
    });
    await new Promise<void>((resolve) => queueMicrotask(() => resolve()));
    expect(response).toBeUndefined();
  });
});
