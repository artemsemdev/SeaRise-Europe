import { describe, expect, it } from "vitest";
import { RELEASE_DELIVERY_POLICY, assertVisualPmtilesStatus, releaseDeliveryPolicy } from "./release-delivery-policy.mjs";

const SHA = "a".repeat(64);
const projection = {
  artifactId: "projection-ssp2-45-2050-pmtiles",
  role: "projection-visual-pmtiles",
  path: "layers/ssp2-45/2050.pmtiles",
  mediaType: "application/vnd.pmtiles",
  byteSize: 624674,
  sha256: SHA,
};

describe("portable release HTTP delivery policy", () => {
  it("overrides generic immutable publication metadata for exact visual PMTiles", () => {
    expect(RELEASE_DELIVERY_POLICY.defaultCacheControl).toContain("immutable");
    expect(releaseDeliveryPolicy(projection.path, projection, projection.byteSize)).toEqual({
      cacheControl: "no-store",
      contentType: "application/vnd.pmtiles",
      etag: `"sha256-${SHA}"`,
      networkOnly: true,
    });
    for (const status of [200, 206, 416]) expect(() => assertVisualPmtilesStatus(status)).not.toThrow();
  });

  it("retains immutable delivery for analysis COGs and other release objects", () => {
    const cog = {
      artifactId: "projection-ssp2-45-2050-cog",
      role: "projection-analysis-cog",
      path: "layers/ssp2-45/2050.tif",
      mediaType: "image/tiff; application=geotiff; profile=cloud-optimized",
      byteSize: 42,
      sha256: SHA,
    };
    expect(releaseDeliveryPolicy(cog.path, cog, 42)).toMatchObject({
      cacheControl: "public, max-age=31536000, immutable",
      networkOnly: false,
    });
  });

  it.each([
    [{ ...projection, artifactId: "projection-ssp2-45-2100-pmtiles" }, projection.path],
    [{ ...projection, role: "projection-analysis-cog" }, projection.path],
    [{ ...projection, byteSize: 1 }, projection.path],
    [{ ...projection, mediaType: "application/octet-stream" }, projection.path],
  ])("fails closed on invalid PMTiles delivery authority %#", (artifact, path) => {
    expect(() => releaseDeliveryPolicy(path, artifact, projection.byteSize)).toThrow();
  });

  it("rejects non-contract PMTiles statuses", () => {
    expect(() => assertVisualPmtilesStatus(304)).toThrow(/not a PMTiles delivery status/);
  });
});
