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
const rangeAuthority = () => ({
  contractVersion: 1, pair: pair(), artifactId: "projection-ssp2-45-2050-cog", role: "projection-analysis-cog",
  canonicalUrl: "https://static.example/releases/release-a/analysis/ssp2-45/2050.tif",
  path: "analysis/ssp2-45/2050.tif",
  mediaType: "image/tiff; application=geotiff; profile=cloud-optimized",
  totalByteSize: 131100, artifactSha256: C, etag: `"sha256-${C}"`, integrityChunkSize: 65536,
} as const);
const range = () => ({
  contractVersion: 1, authority: rangeAuthority(), interval: { start: 65536, endExclusive: 131072 }, authorizedIntervalSha256: B,
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

  it.each([
    "https://static.example/releases/release-a-prefix/manifest.json",
    "https://static.example/releases/prefix-release-a/manifest.json",
    "https://static.example/releases/%72elease-a/manifest.json",
    "https://static.example/releases/release-a%2Fshadow/manifest.json",
    "https://static.example/releases/release-a%252Fshadow/manifest.json",
  ])("rejects ambiguous release scope %s", (manifestUrl) => {
    expect(() => validateAppAuthority({ ...authority(), manifestUrl })).toThrow(
      /exact dataReleaseId path segment/,
    );
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
    expect(() => validateRangeArtifactAuthority({
      ...rangeAuthority(),
      role: "projection-visual-pmtiles",
      canonicalUrl: "https://static.example/releases/release-a/layers/ssp2-45/2050.pmtiles",
      path: "layers/ssp2-45/2050.pmtiles",
      mediaType: "application/vnd.pmtiles",
    })).toThrow(/integrity-authorized analysis COGs/);
  });

  it.each([
    ["PMTiles artifact ID", { artifactId: "projection-ssp2-45-2050-pmtiles" }],
    ["PMTiles path", {
      canonicalUrl: "https://static.example/releases/release-a/layers/ssp2-45/2050.pmtiles",
      path: "layers/ssp2-45/2050.pmtiles",
    }],
    ["PMTiles media type", { mediaType: "application/vnd.pmtiles" }],
    ["mismatched scenario", {
      canonicalUrl: "https://static.example/releases/release-a/analysis/ssp5-85/2050.tif",
      path: "analysis/ssp5-85/2050.tif",
    }],
  ])("rejects role-labelled COG authority with substituted %s", (_name, mutation) => {
    expect(() => validateRangeArtifactAuthority({ ...rangeAuthority(), ...mutation })).toThrow(
      /exact analysis COG identity, path, and media type/,
    );
  });

  it("requires an authorized complete chunk for an analysis COG", () => {
    expect(validateRangeIdentity(range()).authorizedIntervalSha256).toBe(B);
    expect(() => validateRangeIdentity({ ...range(), authorizedIntervalSha256: undefined })).toThrow();
    expect(() => validateRangeIdentity({ ...range(), interval: { start: 65536, endExclusive: 65552 } })).toThrow(/complete authorized/);
  });

  it("accepts the shorter final authorized chunk", () => {
    expect(validateRangeIdentity({ ...range(), interval: { start: 131072, endExclusive: 131100 } }).interval).toEqual({ start: 131072, endExclusive: 131100 });
  });
});
