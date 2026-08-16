import { describe, expect, it } from "vitest";
import { validateAppReleasePair } from "./keys";
import {
  OFFLINE_WORKER_PROTOCOL,
  connectionRequired,
  storageLimitReached,
  validateClientLease,
  validateClientToOfflineWorkerMessage,
  validateInteractionRequirements,
  validateOfflineTechnicalError,
  validateOfflineWorkerToClientMessage,
  validatePairLifecycle,
  validateRollbackRequest,
  validateRuntimeCapability,
  validateStorageBudget,
} from "./policy";

const A = "a".repeat(64);
const B = "b".repeat(64);
const pair = (build = "build-a", release = "release-a") => validateAppReleasePair({ contractVersion: 1, appBuildId: build, dataReleaseId: release });
const whole = (release = "release-a") => ({
  contractVersion: 1, authorityKind: "release-artifact", pair: pair("build-a", release), artifactId: "methodology",
  role: "methodology", canonicalUrl: `https://static.example/releases/${release}/docs/methodology.json`, path: "docs/methodology.json",
  mediaType: "application/json", byteSize: 256, sha256: A, etag: `"sha256-${A}"`,
} as const);
const range = {
  contractVersion: 1,
  authority: {
    contractVersion: 1, pair: pair(), artifactId: "projection-ssp2-45-2050", role: "projection-analysis-cog",
    canonicalUrl: "https://static.example/releases/release-a/layers/ssp2-45/2050.tif", path: "layers/ssp2-45/2050.tif",
    mediaType: "image/tiff; application=geotiff; profile=cloud-optimized", totalByteSize: 65536,
    artifactSha256: A, etag: `"sha256-${A}"`, integrityChunkSize: 65536,
  },
  interval: { start: 0, endExclusive: 65536 }, authorizedIntervalSha256: B,
} as const;
const budget = (override: Record<string, unknown> = {}) => ({
  contractVersion: 1, policyId: "measured-v1", maxTotalBytes: 1000, maxWholeResourceBytes: 300,
  maxRangeBytes: 700, maxWholeEntries: 20, maxRangeEntries: 100, highWatermarkBytes: 900,
  lowWatermarkBytes: 700, minQuotaReserveBytes: 100, maxQuotaFraction: 0.25,
  leaseTtlMs: 120_000, heartbeatMs: 30_000, retainedCompletePairs: 2, eviction: "unleased-lru", ...override,
});
const appAuthority = (disposition: "public-promoted" | "private-engineering" = "public-promoted", release = "release-b") => ({
  contractVersion: 1, appBuildId: "build-b", dataReleaseId: release,
  manifestUrl: `https://static.example/releases/${release}/manifest.json`, releaseDisposition: disposition, precacheSetSha256: A,
} as const);

describe("offline interaction and capability policy v1", () => {
  it("accepts same-pair whole and authorized range requirements", () => {
    const result = validateInteractionRequirements({
      contractVersion: 1, pair: pair(), subject: { kind: "assessment", scenario: "ssp2-45", horizon: 2050 },
      requirements: [{ kind: "whole", authority: whole() }, { kind: "range", identity: range }],
    });
    expect(result.requirements).toHaveLength(2);
  });

  it("rejects mixed releases and unsupported scenario selections", () => {
    expect(() => validateInteractionRequirements({
      contractVersion: 1, pair: pair(), subject: { kind: "assessment", scenario: "ssp2-45", horizon: 2050 },
      requirements: [{ kind: "whole", authority: whole("release-b") }],
    })).toThrow(/different app\/release/);
    expect(() => validateInteractionRequirements({ contractVersion: 1, pair: pair(), subject: { kind: "map", scenario: "ssp9", horizon: 2050 }, requirements: [] })).toThrow(/unsupported/);
  });

  it("keeps offline availability and update availability orthogonal", () => {
    const result = validateRuntimeCapability({
      contractVersion: 1,
      data: { state: "available-offline", pair: pair(), resourceCount: 2, byteCount: 512 },
      update: { state: "update-available", candidate: pair("build-b", "release-b") },
    });
    expect(result.data.state).toBe("available-offline");
    expect(result.update.state).toBe("update-available");
  });

  it("rejects a same-pair update and empty connection-required evidence", () => {
    expect(() => validateRuntimeCapability({ contractVersion: 1, data: { state: "online-complete", pair: pair() }, update: { state: "installing", candidate: pair() } })).toThrow(/must differ/);
    expect(() => validateRuntimeCapability({ contractVersion: 1, data: { state: "connection-required", pair: pair(), missing: [], retryable: true }, update: { state: "current" } })).toThrow(/identify missing/);
  });
});

describe("offline storage and lifecycle policy v1", () => {
  it("accepts an exact measured bounded policy", () => {
    expect(validateStorageBudget(budget()).retainedCompletePairs).toBe(2);
  });

  it.each([
    { lowWatermarkBytes: 900 }, { highWatermarkBytes: 1001 }, { maxWholeResourceBytes: 301 },
    { maxQuotaFraction: 0 }, { maxQuotaFraction: 1.1 }, { heartbeatMs: 60_000 },
    { retainedCompletePairs: 3 }, { eviction: "fifo" },
  ])("rejects unsafe budget override %j", (override) => {
    expect(() => validateStorageBudget(budget(override))).toThrow();
  });

  it("enforces receipt-last pair lifecycle", () => {
    expect(validatePairLifecycle({ contractVersion: 1, pair: pair(), state: "staging", completenessReceiptSha256: null }).state).toBe("staging");
    expect(() => validatePairLifecycle({ contractVersion: 1, pair: pair(), state: "active", completenessReceiptSha256: null })).toThrow(/require/);
    expect(() => validatePairLifecycle({ contractVersion: 1, pair: pair(), state: "staging", completenessReceiptSha256: A })).toThrow(/cannot/);
  });

  it("requires rollback to target a different pair", () => {
    expect(validateRollbackRequest({ contractVersion: 1, currentPair: pair(), targetPair: pair("build-old", "release-old"), confirmationToken: "confirm-1" }).targetPair.dataReleaseId).toBe("release-old");
    expect(() => validateRollbackRequest({ contractVersion: 1, currentPair: pair(), targetPair: pair(), confirmationToken: "confirm-1" })).toThrow(/must differ/);
  });
});

describe("offline worker, lease, and technical protocol v1", () => {
  it("validates leases and exact client messages", () => {
    const lease = validateClientLease({ contractVersion: 1, leaseId: "lease-1", pair: pair(), expiresAtEpochMs: 1_800_000_000_000, state: "active" });
    expect(lease.state).toBe("active");
    const message = { protocol: OFFLINE_WORKER_PROTOCOL, type: "acquire-lease", messageToken: "request-1", leaseId: "lease-1", pair: pair() };
    expect(validateClientToOfflineWorkerMessage(message).type).toBe("acquire-lease");
    expect(() => validateClientToOfflineWorkerMessage({ ...message, query: "private-sentinel" })).toThrow(/additional/);
    const identity = { protocol: OFFLINE_WORKER_PROTOCOL, type: "inspect-identity", messageToken: "identity-1", pair: pair() };
    expect(validateClientToOfflineWorkerMessage(identity).type).toBe("inspect-identity");
    expect(() => validateClientToOfflineWorkerMessage({ ...identity, query: "private-sentinel" })).toThrow(/additional/);
  });

  it("rejects wrong protocol, private update persistence, and same-pair updates", () => {
    expect(() => validateClientToOfflineWorkerMessage({ protocol: "v2", type: "request-cleanup", messageToken: "one", pair: pair() })).toThrow(/unsupported/);
    const update = { protocol: OFFLINE_WORKER_PROTOCOL, type: "prepare-update", messageToken: "one", currentPair: pair(), candidate: appAuthority() };
    expect(validateClientToOfflineWorkerMessage(update).type).toBe("prepare-update");
    expect(() => validateClientToOfflineWorkerMessage({ ...update, candidate: appAuthority("private-engineering") })).toThrow(/session memory only/);
    expect(() => validateClientToOfflineWorkerMessage({ ...update, candidate: { ...appAuthority(), appBuildId: "build-a", dataReleaseId: "release-a", manifestUrl: "https://static.example/releases/release-a/manifest.json" } })).toThrow(/must differ/);
  });

  it("validates worker responses and protects the cleanup pair", () => {
    const response = validateOfflineWorkerToClientMessage({
      protocol: OFFLINE_WORKER_PROTOCOL, type: "cleanup-result", messageToken: "one", pair: pair(),
      deletedPairs: [pair("build-old", "release-old")], freedBytes: 123,
    });
    expect(response.type).toBe("cleanup-result");
    expect(() => validateOfflineWorkerToClientMessage({ protocol: OFFLINE_WORKER_PROTOCOL, type: "cleanup-result", messageToken: "one", pair: pair(), deletedPairs: [pair()], freedBytes: 123 })).toThrow(/protected/);
    expect(validateOfflineWorkerToClientMessage({ protocol: OFFLINE_WORKER_PROTOCOL, type: "worker-identity", messageToken: "identity-1", pair: pair(), precacheSetSha256: A }).type).toBe("worker-identity");
    expect(validateOfflineWorkerToClientMessage({ protocol: OFFLINE_WORKER_PROTOCOL, type: "activation-deferred", messageToken: "activate-1", candidatePair: pair(), reason: "update-coordinator-not-installed" }).type).toBe("activation-deferred");
    expect(() => validateOfflineWorkerToClientMessage({ protocol: OFFLINE_WORKER_PROTOCOL, type: "activation-deferred", messageToken: "activate-1", candidatePair: pair(), reason: "later", query: "private-sentinel" })).toThrow(/additional/);
  });

  it("defines structured technical failures outside scientific outcomes", () => {
    const connection = connectionRequired(pair(), [{ kind: "range", identity: "chunk-1" }]);
    const storage = storageLimitReached(pair());
    expect(validateOfflineTechnicalError(connection).code).toBe("ConnectionRequired");
    expect(validateOfflineTechnicalError(storage).code).toBe("StorageLimitReached");
    expect([connection.code, storage.code]).not.toContain("DataUnavailable");
    expect(() => connectionRequired(pair(), [])).toThrow(/at least one/);
  });
});
