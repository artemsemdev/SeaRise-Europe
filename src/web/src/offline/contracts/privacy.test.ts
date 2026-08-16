import { describe, expect, it } from "vitest";
import { validateAppReleasePair } from "./keys";
import { PERSISTENCE_EXCLUSIONS_V1, validatePersistedOfflineRecord } from "./privacy";

const DIGEST = "d".repeat(64);
const pair = validateAppReleasePair({ contractVersion: 1, appBuildId: "build-a", dataReleaseId: "release-a" });

const whole = {
  contractVersion: 1,
  authorityKind: "app-asset",
  pair,
  resourceId: "assets/app.js",
  canonicalUrl: "https://static.example/assets/app.js",
  path: "assets/app.js",
  mediaType: "text/javascript",
  byteSize: 12,
  sha256: DIGEST,
} as const;

const range = {
  contractVersion: 1,
  authority: {
    contractVersion: 1,
    pair,
    artifactId: "projection-ssp2-45-2050-cog",
    role: "projection-analysis-cog",
    canonicalUrl: "https://static.example/releases/release-a/analysis/ssp2-45/2050.tif",
    path: "analysis/ssp2-45/2050.tif",
    mediaType: "image/tiff; application=geotiff; profile=cloud-optimized",
    totalByteSize: 65536,
    artifactSha256: DIGEST,
    etag: `"sha256-${DIGEST}"`,
    integrityChunkSize: 65536,
  },
  interval: { start: 0, endExclusive: 65536 },
  authorizedIntervalSha256: DIGEST,
} as const;

describe("offline persistence privacy contract v1", () => {
  it("accepts only exact verified whole-resource records", () => {
    expect(validatePersistedOfflineRecord({
      recordType: "whole-resource",
      authority: whole,
      state: "verified",
      byteLength: 12,
      lastAccessSequence: 7,
    }).recordType).toBe("whole-resource");
    expect(() => validatePersistedOfflineRecord({
      recordType: "whole-resource",
      authority: whole,
      state: "verified",
      byteLength: 11,
      lastAccessSequence: 7,
    })).toThrow(/length/);
  });

  it("accepts only exact verified range records with matching byte lengths", () => {
    expect(validatePersistedOfflineRecord({
      recordType: "range",
      identity: range,
      state: "verified",
      byteLength: 65536,
      lastAccessSequence: 8,
    }).recordType).toBe("range");
    expect(() => validatePersistedOfflineRecord({
      recordType: "range",
      identity: range,
      state: "verified",
      byteLength: 16,
      lastAccessSequence: 8,
    })).toThrow(/length/);
  });

  it("rejects a persisted range whose COG role hides PMTiles identity", () => {
    expect(() => validatePersistedOfflineRecord({
      recordType: "range",
      identity: {
        ...range,
        authority: {
          ...range.authority,
          artifactId: "projection-ssp2-45-2050-pmtiles",
          canonicalUrl: "https://static.example/releases/release-a/layers/ssp2-45/2050.pmtiles",
          path: "layers/ssp2-45/2050.pmtiles",
          mediaType: "application/vnd.pmtiles",
        },
      },
      state: "verified",
      byteLength: 65536,
      lastAccessSequence: 8,
    })).toThrow(/exact analysis COG identity, path, and media type/);
  });

  it.each(PERSISTENCE_EXCLUSIONS_V1)("rejects excluded additional property %s", (property) => {
    expect(() => validatePersistedOfflineRecord({
      recordType: "whole-resource",
      authority: whole,
      state: "verified",
      byteLength: 12,
      lastAccessSequence: 7,
      [property]: "private sentinel",
    })).toThrow(/additional/);
  });

  it("rejects query-bearing nested authority URLs", () => {
    expect(() => validatePersistedOfflineRecord({
      recordType: "whole-resource",
      authority: { ...whole, canonicalUrl: `${whole.canonicalUrl}?query=Berlin` },
      state: "verified",
      byteLength: 12,
      lastAccessSequence: 7,
    })).toThrow(/query/);
  });

  it("persists lease authority without browser client identifiers", () => {
    const record = validatePersistedOfflineRecord({
      recordType: "lease",
      lease: { contractVersion: 1, leaseId: "lease-1", pair, expiresAtEpochMs: 1_800_000_000_000, state: "active" },
    });
    expect(record).not.toHaveProperty("clientId");
    expect(() => validatePersistedOfflineRecord({ ...record, clientId: "browser-client" })).toThrow(/additional/);
  });
});
