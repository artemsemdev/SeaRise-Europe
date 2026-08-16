import { describe, expect, it } from "vitest";
import { validateAppReleasePair } from "./keys";
import {
  assertPersistentEligibility,
  canonicalResourceUrl,
  persistenceEligibility,
  sha256Hex,
  validateAppAuthority,
  validateByteInterval,
  validateRangeArtifactAuthority,
  validateRangeIdentity,
  validateVerifiedReleaseAuthority,
  validateWholeResourceAuthority,
} from "./v1";

const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);
const pair = (release = "release-a") => validateAppReleasePair({ contractVersion: 1, appBuildId: "build-a", dataReleaseId: release });
const authority = (disposition: "synthetic-fixture" | "private-engineering" | "public-promoted" = "synthetic-fixture", release = "release-a") => ({
  contractVersion: 1, appBuildId: "build-a", dataReleaseId: release,
  manifestUrl: `https://static.example/releases/${release}/manifest.json`,
  releaseDisposition: disposition, precacheSetSha256: A,
} as const);
const whole = (release = "release-a") => ({
  contractVersion: 1, authorityKind: "release-artifact", pair: pair(release), artifactId: "methodology",
  role: "methodology", canonicalUrl: `https://static.example/releases/${release}/docs/methodology.json`,
  path: "docs/methodology.json", mediaType: "application/json", byteSize: 256, sha256: B, etag: `"sha256-${B}"`,
} as const);
const rangeAuthority = (role: "projection-analysis-cog" | "projection-visual-pmtiles" = "projection-analysis-cog") => ({
  contractVersion: 1, pair: pair(), artifactId: `${role}-ssp2-45-2050`, role,
  canonicalUrl: `https://static.example/releases/release-a/layers/ssp2-45/2050.${role === "projection-analysis-cog" ? "tif" : "pmtiles"}`,
  path: `layers/ssp2-45/2050.${role === "projection-analysis-cog" ? "tif" : "pmtiles"}`,
  mediaType: role === "projection-analysis-cog" ? "image/tiff; application=geotiff; profile=cloud-optimized" : "application/vnd.pmtiles",
  totalByteSize: 131100, artifactSha256: C, etag: `"sha256-${C}"`, integrityChunkSize: 65536,
} as const);
const range = (role: "projection-analysis-cog" | "projection-visual-pmtiles" = "projection-analysis-cog") => ({
  contractVersion: 1, authority: rangeAuthority(role), interval: { start: 65536, endExclusive: 131072 }, authorizedIntervalSha256: B,
} as const);

describe("offline authority foundation v1", () => {
  it("validates exact app and verified manifest authorities", () => {
    expect(validateAppAuthority(authority()).precacheSetSha256).toBe(A);
    expect(validateVerifiedReleaseAuthority({ ...authority(), manifest: {
      canonicalUrl: authority().manifestUrl, byteSize: 4096, sha256: B, etag: `"sha256-${B}"`,
      methodologyVersion: "ar6-regional-projection-v1", dataProvenanceClass: "synthetic-fixture",
    }}).manifest.sha256).toBe(B);
  });

  it("rejects cross-release manifest receipts and additional properties", () => {
    expect(() => validateVerifiedReleaseAuthority({ ...authority(), manifest: {
      canonicalUrl: "https://static.example/releases/other/manifest.json", byteSize: 1, sha256: B, etag: null,
      methodologyVersion: "ar6-regional-projection-v1", dataProvenanceClass: "synthetic-fixture",
    }})).toThrow(/must equal/);
    expect(() => validateAppAuthority({ ...authority(), query: "Berlin" })).toThrow(/additional/);
  });

  it.each(["https://user:secret@static.example/a", "https://static.example/a?latitude=1", "https://static.example/a#selection", "file:///tmp/private-overlay"])("rejects non-canonical URL %s", (url) => {
    expect(() => canonicalResourceUrl(url)).toThrow();
  });

  it("keeps private-engineering and local candidates memory-only", () => {
    expect(persistenceEligibility(validateAppAuthority(authority("public-promoted")))).toMatchObject({ mode: "persistent" });
    const privateOnly = persistenceEligibility(validateAppAuthority(authority("private-engineering")));
    const candidateOnly = persistenceEligibility(validateAppAuthority(authority()), true);
    expect(privateOnly).toEqual({ mode: "memory-only", reason: "private-engineering" });
    expect(candidateOnly).toEqual({ mode: "memory-only", reason: "local-candidate" });
    expect(() => assertPersistentEligibility(privateOnly)).toThrow(/session memory only/);
    expect(() => assertPersistentEligibility(candidateOnly)).toThrow(/session memory only/);
  });

  it("requires lowercase SHA-256", () => {
    expect(sha256Hex(A)).toBe(A);
    expect(() => sha256Hex(A.toUpperCase())).toThrow();
  });

  it("allows only approved complete release resources with exact paths", () => {
    expect(validateWholeResourceAuthority(whole()).authorityKind).toBe("release-artifact");
    expect(() => validateWholeResourceAuthority({ ...whole(), role: "projection-analysis-cog" })).toThrow(/not approved/);
    expect(() => validateWholeResourceAuthority({ ...whole(), canonicalUrl: "https://static.example/releases/release-a/other.json" })).toThrow(/declared path/);
  });

  it("validates exact non-empty half-open intervals", () => {
    expect(validateByteInterval({ start: 0, endExclusive: 10 }, 10)).toEqual({ start: 0, endExclusive: 10 });
    expect(() => validateByteInterval({ start: 10, endExclusive: 10 }, 10)).toThrow(/non-empty/);
    expect(() => validateByteInterval({ start: 0, endExclusive: 11 }, 10)).toThrow(/exceeds/);
  });

  it("binds range authority to complete artifact digest and ETag", () => {
    expect(validateRangeArtifactAuthority(rangeAuthority()).artifactSha256).toBe(C);
    expect(() => validateRangeArtifactAuthority({ ...rangeAuthority(), etag: `"sha256-${A}"` })).toThrow(/bind/);
  });

  it.each(["projection-analysis-cog", "projection-visual-pmtiles"] as const)("requires an authorized complete chunk for %s", (role) => {
    expect(validateRangeIdentity(range(role)).authorizedIntervalSha256).toBe(B);
    expect(() => validateRangeIdentity({ ...range(role), authorizedIntervalSha256: undefined })).toThrow();
    expect(() => validateRangeIdentity({ ...range(role), interval: { start: 65536, endExclusive: 65552 } })).toThrow(/complete authorized/);
  });

  it("accepts the shorter final authorized chunk", () => {
    expect(validateRangeIdentity({ ...range(), interval: { start: 131072, endExclusive: 131100 } }).interval).toEqual({ start: 131072, endExclusive: 131100 });
  });
});
