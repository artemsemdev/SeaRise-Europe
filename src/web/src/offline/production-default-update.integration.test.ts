// @vitest-environment-options { "url": "https://fixture.searise.invalid/" }
import { IDBFactory } from "fake-indexeddb";
import { webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createBrowserRuntime } from "../application/browser-runtime";
import { runtimeConfig } from "../config";
import { PairLifecycleStore } from "./pair-lifecycle-store";
import { createProductionUpdateCoordinator } from "./production-update-coordinator";
import type { CloseAndReopenIntentV1 } from "./update-coordinator";
import type { VerifiedResourceRouter } from "./verified-resource-router";
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
  it("completes active authority and reconciles armed intents across fresh boots", async () => {
    const context = await fixtureReleaseContext();
    const idb = new IDBFactory();
    const caches = new MemoryCaches();
    const locks = new ImmediateLocks();
    const currentPrecache = "a".repeat(64);
    const candidatePrecache = "b".repeat(64);
    const candidateA = validateAppReleasePair({ contractVersion: 1, appBuildId: "next-browser-build-a", dataReleaseId: "next-browser-release-a" });
    const candidateB = validateAppReleasePair({ contractVersion: 1, appBuildId: "next-browser-build-b", dataReleaseId: "next-browser-release-b" });
    const candidateC = validateAppReleasePair({ contractVersion: 1, appBuildId: "next-browser-build-c", dataReleaseId: "next-browser-release-c" });
    let waitingPair = candidateA;
    let waitingPrecache = candidatePrecache;
    const currentPair = validateAppReleasePair({
      contractVersion: 1, appBuildId: runtimeConfig.appBuildId, dataReleaseId: context.dataReleaseId,
    });
    const retiredPair = validateAppReleasePair({
      contractVersion: 1, appBuildId: "retired-browser-build", dataReleaseId: "retired-browser-release",
    });
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
      if (message.type === "request-client-census") {
        ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "client-census",
          messageToken: message.messageToken, targetPair: message.targetPair,
          observations: [{ clientId: "retired-tab", state: "inactive" }] });
        return;
      }
      ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "worker-identity", messageToken: message.messageToken,
        pair: currentPair, precacheSetSha256: currentPrecache });
    } };
    const waiting = { postMessage(message: Record<string, unknown>, ports: MessagePort[]) { ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "worker-identity", messageToken: message.messageToken, pair: waitingPair, precacheSetSha256: waitingPrecache }); } };
    const registration: { active: typeof active; waiting: typeof waiting | null } = { active, waiting: null };
    Object.assign(globalThis, { caches, indexedDB: idb });
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {
      ...webcrypto,
      randomUUID: webcrypto.randomUUID.bind(webcrypto),
      subtle: { digest: (algorithm: AlgorithmIdentifier, data: BufferSource) =>
        webcrypto.subtle.digest(algorithm, Buffer.from(new Uint8Array(data as ArrayBuffer))) },
    } });
    Object.defineProperty(navigator, "locks", { configurable: true, value: locks });
    const serviceWorkerBoundary = {
      register: vi.fn(async () => registration), ready: Promise.resolve(registration),
      getRegistration: vi.fn(async () => registration),
      addEventListener: vi.fn(),
      controller: active,
    };
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: serviceWorkerBoundary });
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

    const retiredLifecycle = new PairLifecycleStore({ indexedDB: idb, cacheStorage: caches as never });
    await retiredLifecycle.stage(retiredPair);
    await retiredLifecycle.completeBootstrap(retiredPair, "9".repeat(64));
    await retiredLifecycle.completeCore(retiredPair, {
      precacheSetSha256: "9".repeat(64),
      resourcePlanSha256: "8".repeat(64),
      receiptSha256: "7".repeat(64),
    });
    await retiredLifecycle.markCleanupPending(retiredPair);
    retiredLifecycle.close();

    const runtime = await createBrowserRuntime(context);
    await vi.waitFor(() => expect(runtime.capability?.getSnapshot()?.update.state).toBe("current"));
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
    const lifecycle = new PairLifecycleStore({ indexedDB: idb, cacheStorage: caches as never });
    const currentLifecycle = await lifecycle.read(currentPair);
    expect(currentLifecycle).toMatchObject({
      status: "found",
      record: { state: "active", acceptedIdentity: {
        precacheSetSha256: currentPrecache,
        resourcePlanSha256: expect.stringMatching(/^[0-9a-f]{64}$/u),
        receiptSha256: expect.stringMatching(/^[0-9a-f]{64}$/u),
      } },
    });
    await expect(runtime.resources.updateCoordinator?.inspectRetention?.()).resolves.toMatchObject({
      state: "complete", activePair: currentPair, removedPairs: [retiredPair],
    });
    await expect(lifecycle.read(retiredPair)).resolves.toEqual({ status: "missing" });
    registration.waiting = waiting;
    await runtime.capability?.retry();
    await vi.waitFor(() => expect(runtime.capability?.getSnapshot()?.update.state).toBe("update-available"));

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

    waitingPair = candidateA;
    waitingPrecache = candidatePrecache;
    await runtime.capability?.retry();
    await runtime.capability?.requestUpdateAction();
    await vi.waitFor(() => expect(runtime.capability?.getSnapshot()?.update.state).toBe("ready-to-activate"));
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"armed"');
    const naturallyArmed = localStorage.getItem("searise:update-intent:v1");
    if (!naturallyArmed) throw new Error("natural armed intent was unavailable");
    runtime.dispose();

    const candidateSnapshot = () => ({
      contractVersion: 1 as const,
      plan: { pair: candidateA, resourcePlanSha256: "f".repeat(64) },
      gate: { receiptSha256: "1".repeat(64) },
    });
    let admittedCandidate: ReturnType<typeof candidateSnapshot> | null = null;
    const candidateRouter = { current: () => admittedCandidate } as unknown as VerifiedResourceRouter;
    serviceWorkerBoundary.controller = waiting;
    registration.waiting = null;
    const successRuntime = createProductionUpdateCoordinator(candidateRouter, candidatePrecache);
    await Promise.all([successRuntime.inspect(), successRuntime.inspectRetention()]);
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"armed"');
    admittedCandidate = candidateSnapshot();
    const concurrent = await Promise.all([
      successRuntime.inspect(),
      successRuntime.inspect(),
      successRuntime.inspectRetention(),
    ]);
    expect(concurrent[0]).toEqual(concurrent[1]);
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"consumed"');
    await successRuntime.inspect();
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"consumed"');

    const waitingB = { postMessage(message: Record<string, unknown>, ports: MessagePort[]) {
      ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "worker-identity", messageToken: message.messageToken,
        pair: candidateB, precacheSetSha256: "c".repeat(64) });
    } };
    registration.waiting = waitingB;
    admittedCandidate = {
      ...candidateSnapshot(),
      plan: { pair: candidateA, resourcePlanSha256: "2".repeat(64) },
      gate: { receiptSha256: "3".repeat(64) },
    };
    const candidateBCapability = Object.freeze({
      contractVersion: 2 as const,
      subject: Object.freeze({ kind: "core" as const }),
      data: Object.freeze({ state: "online-complete" as const, pair: candidateA }),
      update: Object.freeze({ state: "update-available" as const, candidate: candidateB }),
    });
    const consumedRollover = successRuntime;
    await expect(consumedRollover.inspect()).resolves.toMatchObject({ state: "update-available" });
    await consumedRollover.requestAction(candidateBCapability);
    await expect(consumedRollover.inspect()).resolves.toMatchObject({ state: "ready-to-activate" });
    const secondArmed = localStorage.getItem("searise:update-intent:v1");
    expect(secondArmed).toContain('"state":"armed"');

    const secondRecord = JSON.parse(secondArmed ?? "null") as { intent: CloseAndReopenIntentV1 };
    admittedCandidate = candidateSnapshot();
    localStorage.setItem("searise:update-intent:v1", JSON.stringify({ intent: secondRecord.intent, state: "pending" }));
    const nonterminalRollover = createProductionUpdateCoordinator(candidateRouter, candidatePrecache);
    await expect(nonterminalRollover.inspect()).resolves.toMatchObject({ state: "update-available" });
    await nonterminalRollover.requestAction(candidateBCapability);
    await expect(nonterminalRollover.inspect()).resolves.toMatchObject({
      state: "failed", reason: expect.stringContaining("nonterminal durable update intent"),
    });
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"pending"');

    localStorage.setItem("searise:update-intent:v1", JSON.stringify({ intent: secondRecord.intent, state: "tombstoned" }));
    const terminalReplay = createProductionUpdateCoordinator(candidateRouter, candidatePrecache);
    await expect(terminalReplay.inspect()).resolves.toMatchObject({ state: "update-available" });
    await terminalReplay.requestAction(candidateBCapability);
    await expect(terminalReplay.inspect()).resolves.toMatchObject({
      state: "failed", reason: expect.stringContaining("terminal update candidate cannot be replayed"),
    });
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"tombstoned"');

    const waitingC = { postMessage(message: Record<string, unknown>, ports: MessagePort[]) {
      ports[0].postMessage({ protocol: "searise-offline-worker-v1", type: "worker-identity", messageToken: message.messageToken,
        pair: candidateC, precacheSetSha256: "d".repeat(64) });
    } };
    registration.waiting = waitingC;
    const candidateCCapability = Object.freeze({
      ...candidateBCapability,
      update: Object.freeze({ state: "update-available" as const, candidate: candidateC }),
    });
    const tombstonedRollover = createProductionUpdateCoordinator(candidateRouter, candidatePrecache);
    await expect(tombstonedRollover.inspect()).resolves.toMatchObject({ state: "update-available" });
    await tombstonedRollover.requestAction(candidateCCapability);
    await expect(tombstonedRollover.inspect()).resolves.toMatchObject({ state: "ready-to-activate" });
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"armed"');

    for (const corrupt of [
      "{malformed",
      JSON.stringify({ state: "armed" }),
      JSON.stringify({ state: "forged", intent: JSON.parse(naturallyArmed).intent }),
    ]) {
      localStorage.setItem("searise:update-intent:v1", corrupt);
      const corruptRuntime = createProductionUpdateCoordinator(candidateRouter, candidatePrecache);
      await expect(corruptRuntime.inspect()).resolves.toMatchObject({
        state: "failed", reason: expect.stringContaining("malformed"),
      });
      expect(localStorage.getItem("searise:update-intent:v1")).toBeNull();
    }

    localStorage.setItem("searise:update-intent:v1", naturallyArmed);
    serviceWorkerBoundary.controller = active;
    const mismatchRuntime = createProductionUpdateCoordinator(candidateRouter, candidatePrecache);
    await expect(mismatchRuntime.inspect()).resolves.toMatchObject({
      state: "failed", reason: expect.stringContaining("Controlling worker"),
    });
    expect(localStorage.getItem("searise:update-intent:v1")).toContain('"state":"tombstoned"');
    expect(localStorage.getItem("searise:update-intent:v1")).not.toContain('"state":"consumed"');
  });
});
