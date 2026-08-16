import { runtimeConfig } from "../config";
import { verifiedArtifactBytes } from "../data/artifact-integrity";
import { TechnicalFailure, type ReleaseContext } from "../domain/release";
import { validateOfflineWorkerToClientMessage, OFFLINE_WORKER_PROTOCOL } from "./contracts/policy";
import { validateAppAuthority } from "./contracts/v1";
import { browserAdmissionLockPort, createAdmissionReceiptStore } from "./admission-receipt";
import { createVerifiedReleaseResourcePlan } from "./release-resource-plan";
import { createRangeStore } from "./range-store";
import { validateStorageBudget } from "./contracts/policy";
import { MemoryWholeResourceCache, WholeResourceCache } from "./whole-resource-cache";
import { VerifiedResourceRouter } from "./verified-resource-router";

const RANGE_BUDGET_BYTES = 96 * 1024 * 1024;
const WHOLE_BUDGET_BYTES = 64 * 1024 * 1024;
const WORKER_IDENTITY_TIMEOUT_MS = 10_000;

function technical(message: string, recoverable = false): TechnicalFailure {
  return new TechnicalFailure({
    kind: "technical-error",
    code: "UnsupportedBrowser",
    message,
    recoverable,
  });
}

function rangeIntegrityBootstrapArtifact(context: ReleaseContext) {
  const artifact = context.artifact(context.manifest.contractArtifacts.rangeIntegrityIndex);
  const expectedUrl = new URL(
    "analysis/cog-range-integrity.json",
    new URL("./", context.manifestUrl),
  ).href;
  if (
    artifact.role !== "range-integrity-index" ||
    artifact.path !== "analysis/cog-range-integrity.json" ||
    artifact.mediaType !== "application/json" ||
    artifact.url !== expectedUrl ||
    artifact.dataReleaseId !== context.dataReleaseId
  ) {
    throw new TechnicalFailure({
      kind: "technical-error",
      code: "IntegrityFailed",
      message: "The range-integrity bootstrap does not match the exact release authority.",
      recoverable: false,
    });
  }
  return artifact;
}

function hexadecimal(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function privateSessionAuthority(subtle: SubtleCrypto): Promise<string> {
  const payload = new TextEncoder().encode(JSON.stringify({
    authorityKind: "private-candidate-session",
    appBuildId: runtimeConfig.appBuildId,
    dataReleaseId: runtimeConfig.dataReleaseId,
  }));
  return hexadecimal(await subtle.digest("SHA-256", payload));
}

async function workerPrecacheAuthority(signal: AbortSignal): Promise<string> {
  if (signal.aborted) throw technical("Build identity verification was cancelled.", true);
  if (!("serviceWorker" in navigator)) {
    throw technical("A verified service worker is required for persistent release routing.");
  }
  await navigator.serviceWorker.register("/service-worker.js", {
    scope: "/",
    type: "module",
    updateViaCache: "none",
  });
  const registration = await navigator.serviceWorker.ready;
  const worker = registration.active;
  if (!worker) throw technical("The verified service worker is not active yet.", true);
  const token = `identity-${crypto.randomUUID()}`;
  const channel = new MessageChannel();
  const response = await new Promise<unknown>((resolve, reject) => {
    const settle = (operation: () => void): void => {
      signal.removeEventListener("abort", abort);
      clearTimeout(timeout);
      channel.port1.close();
      operation();
    };
    const abort = () => settle(() => reject(technical("Build identity verification was cancelled.", true)));
    const timeout = setTimeout(
      () => settle(() => reject(technical("The verified service worker did not report its build identity.", true))),
      WORKER_IDENTITY_TIMEOUT_MS,
    );
    signal.addEventListener("abort", abort, { once: true });
    channel.port1.onmessage = ({ data }) => {
      settle(() => resolve(data));
    };
    worker.postMessage({
      protocol: OFFLINE_WORKER_PROTOCOL,
      type: "inspect-identity",
      messageToken: token,
      pair: {
        contractVersion: 1,
        appBuildId: runtimeConfig.appBuildId,
        dataReleaseId: runtimeConfig.dataReleaseId,
      },
    }, [channel.port2]);
  });
  const message = validateOfflineWorkerToClientMessage(response);
  if (
    message.type !== "worker-identity" || message.messageToken !== token ||
    message.pair.appBuildId !== runtimeConfig.appBuildId ||
    message.pair.dataReleaseId !== runtimeConfig.dataReleaseId
  ) {
    throw technical("The application and verified service worker identities disagree.");
  }
  return message.precacheSetSha256;
}

export async function createProductionResourceRouter(
  context: ReleaseContext,
  signal: AbortSignal,
): Promise<VerifiedResourceRouter> {
  if (!globalThis.crypto?.subtle || !globalThis.crypto.randomUUID) {
    throw technical("Web Crypto is required for verified release routing.");
  }
  const subtle = globalThis.crypto.subtle;
  const localCandidate = runtimeConfig.releaseDisposition === "private-engineering";
  if (!localCandidate && (!("caches" in globalThis) || !("indexedDB" in globalThis) || !("locks" in navigator))) {
    throw technical("Persistent release routing requires Cache Storage, IndexedDB, and Web Locks.");
  }
  const precacheSetSha256 = localCandidate
    ? await privateSessionAuthority(subtle)
    : await workerPrecacheAuthority(signal);
  const appAuthority = validateAppAuthority({
    contractVersion: 1,
    appBuildId: runtimeConfig.appBuildId,
    dataReleaseId: context.dataReleaseId,
    manifestUrl: context.manifestUrl,
    releaseDisposition: context.disposition,
    precacheSetSha256,
  });
  // For a controlled persistent build, this exact path is a sealed member of
  // the build-bound service-worker precache. A warm offline reload therefore
  // receives verified bytes without a network fallback. Private Candidate
  // mode has no worker and performs the same manifest-bound read into memory.
  const rangeIndexArtifact = rangeIntegrityBootstrapArtifact(context);
  const rangeIntegrityBytes = await verifiedArtifactBytes(
    rangeIndexArtifact,
    signal,
    (input, init) => fetch(input, {
      signal: init.signal,
      headers: init.headers,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
    }),
  );
  const releasePlan = await createVerifiedReleaseResourcePlan({
    context,
    appAuthority,
    rangeIntegrityBytes,
    localCandidate,
  });
  const budget = validateStorageBudget({
    contractVersion: 1,
    policyId: "phase-2-browser-v1",
    maxTotalBytes: RANGE_BUDGET_BYTES + WHOLE_BUDGET_BYTES,
    maxWholeResourceBytes: WHOLE_BUDGET_BYTES,
    maxRangeBytes: RANGE_BUDGET_BYTES,
    maxWholeEntries: 64,
    maxRangeEntries: 512,
    highWatermarkBytes: 144 * 1024 * 1024,
    lowWatermarkBytes: 128 * 1024 * 1024,
    minQuotaReserveBytes: 64 * 1024 * 1024,
    maxQuotaFraction: 0.25,
    leaseTtlMs: 120_000,
    heartbeatMs: 30_000,
    retainedCompletePairs: 2,
    eviction: "unleased-lru",
  });
  let sequence = 0;
  const nextOperationId = (): string => `runtime-${crypto.randomUUID()}-${++sequence}`;
  const dependencies = {
    applicationOrigin: window.location.origin,
    digest: (algorithm: "SHA-256", bytes: ArrayBuffer) => subtle.digest(algorithm, bytes),
    fetchResource: (url: string, init: RequestInit) => fetch(url, init),
    nextOperationId,
  };
  const wholeStore = localCandidate
    ? new MemoryWholeResourceCache(appAuthority, dependencies, {
        localCandidate: true,
        maxBytes: WHOLE_BUDGET_BYTES,
        maxEntries: 64,
      })
    : new WholeResourceCache(appAuthority, { ...dependencies, cacheStorage: caches });
  const rangeStore = createRangeStore(appAuthority, budget, {
    ...(localCandidate ? {} : { indexedDB }),
    subtle,
  }, { catalog: releasePlan.rangeCatalog, localCandidate });
  const receiptStore = createAdmissionReceiptStore(appAuthority, subtle, {
    ...(localCandidate ? {} : {
      indexedDB,
      locks: browserAdmissionLockPort(navigator.locks),
    }),
    localCandidate,
  });
  return new VerifiedResourceRouter({
    releasePlan,
    wholeStore,
    rangeStore,
    receiptStore,
    subtle,
    fetchRange: fetch.bind(globalThis),
  });
}
