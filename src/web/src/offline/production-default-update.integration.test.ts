// @vitest-environment-options { "url": "https://fixture.searise.invalid/" }
import { IDBFactory } from "fake-indexeddb";
import { webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createBrowserRuntime } from "../application/browser-runtime";
import { runtimeConfig } from "../config";
import { PairLifecycleStore } from "./pair-lifecycle-store";
import { validateAppReleasePair } from "./contracts/keys";
import { fixtureArtifactPath, fixtureBytes, fixtureReleaseContext, responseBody } from "../test/release-fixture";

class MemoryCache {
  readonly values = new Map<string, Response>();
  async match(input: RequestInfo | URL) { return this.values.get(String(input))?.clone(); }
  async put(input: RequestInfo | URL, response: Response) { this.values.set(String(input), response.clone()); }
  async delete(input: RequestInfo | URL) { return this.values.delete(String(input)); }
  async keys() { return [...this.values.keys()].map((url) => new Request(url)); }
}
class MemoryCaches {
  readonly values = new Map<string, MemoryCache>();
  async open(name: string) { const value = this.values.get(name) ?? new MemoryCache(); this.values.set(name, value); return value; }
  async keys() { return [...this.values.keys()]; }
  async delete(name: string) { return this.values.delete(name); }
}
class ImmediateLocks {
  async request<T>(_name: string, options: unknown, callback?: () => T | Promise<T>): Promise<T> {
    return await (callback ?? options as () => T | Promise<T>)();
  }
}

const original = {
  caches: globalThis.caches,
  indexedDB: globalThis.indexedDB,
  fetch: globalThis.fetch,
  messageChannel: globalThis.MessageChannel,
  crypto: globalThis.crypto,
};

afterEach(() => {
  vi.restoreAllMocks();
  Object.assign(globalThis, { caches: original.caches, indexedDB: original.indexedDB, fetch: original.fetch, MessageChannel: original.messageChannel });
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: original.crypto });
  localStorage.clear();
});

describe("production default update composition", () => {
  it("refuses mixed and corrupt candidates before arming exact default-factory authority", async () => {
    const context = await fixtureReleaseContext();
    const idb = new IDBFactory();
    const caches = new MemoryCaches();
    const locks = new ImmediateLocks();
    const currentPrecache = "a".repeat(64);
    const candidatePrecache = "b".repeat(64);
    const candidateA = validateAppReleasePair({ contractVersion: 1, appBuildId: "next-browser-build-a", dataReleaseId: "next-browser-release-a" });
    const candidateB = validateAppReleasePair({ contractVersion: 1, appBuildId: "next-browser-build-b", dataReleaseId: "next-browser-release-b" });
    let waitingPair = candidateA;
    let waitingPrecache = candidatePrecache;
    const currentPair = { contractVersion: 1 as const, appBuildId: runtimeConfig.appBuildId, dataReleaseId: context.dataReleaseId };
    const active = { postMessage(message: Record<string, unknown>, ports: MessagePort[]) {
      if (message.type === "acquire-lease" || message.type === "heartbeat-lease") {
        ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "lease-state", messageToken: message.messageToken,
          lease: { contractVersion: 1, leaseId: message.leaseId, pair: currentPair, expiresAtEpochMs: Date.now() + 120_000, state: "active" } });
        return;
      }
      if (message.type === "release-lease") {
        ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "lease-released", messageToken: message.messageToken,
          pair: currentPair, leaseId: message.leaseId });
        return;
      }
      ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "worker-identity", messageToken: message.messageToken,
        pair: currentPair, precacheSetSha256: currentPrecache });
    } };
    const waiting = { postMessage(message: Record<string, unknown>, ports: MessagePort[]) { ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "worker-identity", messageToken: message.messageToken, pair: waitingPair, precacheSetSha256: waitingPrecache }); } };
    const registration = { active, waiting };
    Object.assign(globalThis, { caches, indexedDB: idb });
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {
      ...webcrypto,
      randomUUID: webcrypto.randomUUID.bind(webcrypto),
      subtle: { digest: (algorithm: AlgorithmIdentifier, data: BufferSource) =>
        webcrypto.subtle.digest(algorithm, Buffer.from(new Uint8Array(data as ArrayBuffer))) },
    } });
    Object.defineProperty(navigator, "locks", { configurable: true, value: locks });
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: {
      register: vi.fn(async () => registration), ready: Promise.resolve(registration),
      getRegistration: vi.fn(async () => registration),
      addEventListener: vi.fn(),
    } });
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const bytes = fixtureBytes(fixtureArtifactPath(url));
      const artifact = Object.values(context.artifacts).find((value) => value.url === url.href);
      const authorityHeaders = {
        "content-type": artifact?.mediaType ?? "application/octet-stream",
        etag: `"sha256-${artifact?.sha256 ?? "0".repeat(64)}"`,
        "cache-control": "public, max-age=31536000, immutable",
      };
      const range = new Headers(init.headers).get("range");
      if (range) {
        const [, start, end] = /^bytes=(\d+)-(\d+)$/u.exec(range) ?? [];
        const body = bytes.slice(Number(start), Number(end) + 1);
        const response = new Response(responseBody(body), { status: 206, headers: { ...authorityHeaders, "accept-ranges": "bytes", "content-range": `bytes ${start}-${end}/${bytes.byteLength}`, "content-length": String(body.byteLength) } });
        Object.defineProperty(response, "url", { value: url.href });
        return response;
      }
      const response = new Response(responseBody(bytes), { status: 200, headers: { ...authorityHeaders, "content-length": String(bytes.byteLength) } });
      Object.defineProperty(response, "url", { value: url.href });
      return response;
    });

    const runtime = await createBrowserRuntime(context);
    await vi.waitFor(() => expect(runtime.capability?.getSnapshot()?.update.state).toBe("update-available"));
    const methodology = context.artifact(context.manifest.contractArtifacts.methodology);
    await runtime.searchArtifactTransport(new URL(methodology.url), {
      signal: new AbortController().signal,
      headers: { Accept: methodology.mediaType },
    });
    const subject = Object.freeze({ kind: "assessment" as const, scenario: "ssp2-45" as const, horizon: 2050 as const });
    const interaction = runtime.capability?.beginInteraction(subject);
    await runtime.controller.select({
      dataReleaseId: context.dataReleaseId, scenario: "ssp2-45", horizon: 2050,
      location: { kind: "coordinate", coordinates: { latitude: 36.72, longitude: -4.42 } },
    });
    if (interaction) await runtime.capability?.confirmInteractionAvailable(interaction);

    // The UI advertised A, but the exact waiting worker changed to B before
    // action. The production coordinator must reject the mixed pair before
    // any durable transition record exists.
    waitingPair = candidateB;
    await runtime.capability?.requestUpdateAction();
    await vi.waitFor(() => expect(runtime.capability?.getSnapshot()?.update.state).toBe("failed"));
    expect(runtime.capability?.getSnapshot()?.update).toMatchObject({
      state: "failed", reason: expect.stringContaining("does not match the requested candidate"),
    });
    expect(localStorage.getItem("searise:update-intent:v1")).toBeNull();

    const lifecycle = new PairLifecycleStore({ indexedDB: idb, cacheStorage: caches as never });
    await lifecycle.stage(candidateB);
    await lifecycle.completeBootstrap(candidateB, "e".repeat(64));
    await lifecycle.completeCore(candidateB, { precacheSetSha256: "e".repeat(64), resourcePlanSha256: "c".repeat(64), receiptSha256: "d".repeat(64) });
    await runtime.capability?.retry();
    await runtime.capability?.requestUpdateAction();
    expect(runtime.capability?.getSnapshot()?.update).toMatchObject({
      state: "failed", reason: expect.stringContaining("accepted resource authority disagree"),
    });
    expect(localStorage.getItem("searise:update-intent:v1")).toBeNull();

    await lifecycle.stage(candidateA);
    await lifecycle.completeBootstrap(candidateA, candidatePrecache);
    await lifecycle.completeCore(candidateA, { precacheSetSha256: candidatePrecache, resourcePlanSha256: "f".repeat(64), receiptSha256: "1".repeat(64) });
    waitingPair = candidateA;
    waitingPrecache = candidatePrecache;
    await runtime.capability?.retry();
    await runtime.capability?.requestUpdateAction();
    await vi.waitFor(() => expect(runtime.capability?.getSnapshot()?.update.state).toBe("ready-to-activate"));
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"armed"');
    runtime.dispose();
  });
});
