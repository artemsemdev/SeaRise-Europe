import { describe, expect, it } from "vitest";
import {
  OFFLINE_CACHE_PREFIX,
  OFFLINE_RANGE_DATABASE,
  appBuildId,
  cacheNamespaces,
  offlineDataReleaseId,
  validateAppReleasePair,
} from "./keys";

describe("offline cache identity v1", () => {
  it("creates deterministic app/release-isolated namespaces", () => {
    const pair = validateAppReleasePair({
      contractVersion: 1,
      appBuildId: "build-abc123",
      dataReleaseId: "release-2026.08",
    });
    expect(cacheNamespaces(pair)).toEqual({
      pairKey: "build-abc123::release-2026.08",
      shell: `${OFFLINE_CACHE_PREFIX}:shell:build-abc123::release-2026.08`,
      release: `${OFFLINE_CACHE_PREFIX}:release:build-abc123::release-2026.08`,
      rangeDatabase: OFFLINE_RANGE_DATABASE,
    });
  });

  it("changes every resource namespace when either authority changes", () => {
    const first = cacheNamespaces(validateAppReleasePair({ contractVersion: 1, appBuildId: "a", dataReleaseId: "one" }));
    const nextBuild = cacheNamespaces(validateAppReleasePair({ contractVersion: 1, appBuildId: "b", dataReleaseId: "one" }));
    const nextRelease = cacheNamespaces(validateAppReleasePair({ contractVersion: 1, appBuildId: "a", dataReleaseId: "two" }));
    expect(new Set([first.shell, nextBuild.shell, nextRelease.shell])).toHaveLength(3);
    expect(new Set([first.release, nextBuild.release, nextRelease.release])).toHaveLength(3);
  });

  it.each(["", "a:b", " space", "é", "x".repeat(129)])("rejects unsafe authority id %j", (value) => {
    expect(() => appBuildId(value)).toThrow();
    expect(() => offlineDataReleaseId(value)).toThrow();
  });

  it("rejects unsupported versions and additional fields", () => {
    expect(() => validateAppReleasePair({ contractVersion: 2, appBuildId: "a", dataReleaseId: "b" })).toThrow();
    expect(() => validateAppReleasePair({ contractVersion: 1, appBuildId: "a", dataReleaseId: "b", query: "private" })).toThrow();
  });
});
