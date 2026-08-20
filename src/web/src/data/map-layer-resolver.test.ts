import fixture from "../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { describe, expect, it } from "vitest";
import { HORIZON_YEARS, SCENARIO_IDS, type ReleaseArtifactV2 } from "../contracts/generated/release-contract";
import { ReleaseContext, TechnicalFailure, type ResolvedArtifact } from "../domain/release";
import { ManifestRepository } from "./manifest-repository";
import { resolveMapLayers } from "./map-layer-resolver";

const releaseId = fixture.dataReleaseId;
const origin = "https://fixture.example";

async function releaseContext(): Promise<ReleaseContext> {
  return new ManifestRepository({
    manifestUrl: `${origin}/releases/${releaseId}/manifest.json`,
    allowedOrigins: [origin],
    expectedDisposition: "synthetic-fixture",
    transport: async () => new Response(JSON.stringify(fixture), {
      headers: { "content-type": "application/json" },
    }),
  }).load(releaseId, new AbortController().signal);
}

describe("visual map layer resolution", () => {
  it("resolves all nine selections to the matching immutable visual PMTiles", async () => {
    const context = await releaseContext();
    const resolved = SCENARIO_IDS.flatMap((scenario) =>
      HORIZON_YEARS.map((horizon) => resolveMapLayers(context, scenario, horizon)),
    );

    expect(resolved).toHaveLength(9);
    expect(new Set(resolved.map(({ projection }) => projection.artifactId))).toHaveLength(9);
    for (const { projection, attributionArtifactUrl } of resolved) {
      expect(projection.url).toBe(
        `${origin}/releases/${releaseId}/layers/${projection.scenario}/${projection.horizon}.pmtiles`,
      );
      expect(projection.visualOnly).toBe(true);
      expect(projection.valueProperties).toEqual({ lower: "lower_mm", central: "median_mm", upper: "upper_mm" });
      expect(attributionArtifactUrl).toBe(context.artifact(context.manifest.contractArtifacts.attribution).url);
    }
  });

  it("discovers optional release-scoped PMTiles and GeoJSON boundaries by role", async () => {
    const context = await releaseContext();
    const artifacts = { ...context.artifacts };
    const additions: readonly ResolvedArtifact[] = [
      {
        ...context.artifact(context.manifest.contractArtifacts.attribution),
        artifactId: "support-boundary-pmtiles",
        role: "support-boundary",
        mediaType: "application/vnd.pmtiles",
        scientificUse: "not-applicable",
        path: "boundaries/europe.pmtiles",
        url: `${origin}/releases/${releaseId}/boundaries/europe.pmtiles`,
      },
      {
        ...context.artifact(context.manifest.contractArtifacts.attribution),
        artifactId: "coastal-map",
        role: "coastal-boundary",
        mediaType: "application/geo+json",
        scientificUse: "not-applicable",
        path: "boundaries/coastal.geojson",
        url: `${origin}/releases/${releaseId}/boundaries/coastal.geojson`,
      },
    ] as readonly ResolvedArtifact[];
    for (const artifact of additions) artifacts[artifact.artifactId] = artifact;
    const enriched = new ReleaseContext({
      manifest: context.manifest,
      manifestUrl: context.manifestUrl,
      disposition: context.disposition,
      artifacts,
      datasets: { ...context.datasets },
    });

    expect(resolveMapLayers(enriched, "ssp2-45", 2050).boundaries).toEqual([
      expect.objectContaining({ kind: "coastal-boundary", sourceLayer: "coastal_boundary" }),
      expect.objectContaining({
        kind: "support-boundary",
        sourceLayer: "support_boundary",
        byteSize: additions[0].byteSize,
        sha256: additions[0].sha256,
      }),
    ]);
  });

  it("rejects a valid-looking boundary PMTiles path outside the exact candidate mapping", async () => {
    const context = await releaseContext();
    const artifacts = { ...context.artifacts };
    const forged = {
      ...context.artifact(context.manifest.contractArtifacts.attribution),
      artifactId: "support-map",
      role: "support-boundary",
      mediaType: "application/vnd.pmtiles",
      scientificUse: "not-applicable",
      path: "boundaries/europe.pmtiles",
      url: `${origin}/releases/${releaseId}/boundaries/europe.pmtiles`,
    } as ResolvedArtifact;
    artifacts[forged.artifactId] = forged;
    const invalid = new ReleaseContext({
      manifest: context.manifest,
      manifestUrl: context.manifestUrl,
      disposition: context.disposition,
      artifacts,
      datasets: { ...context.datasets },
    });

    expect(() => resolveMapLayers(invalid, "ssp2-45", 2050)).toThrowError(TechnicalFailure);
  });

  it("fails closed if the dataset visual reference is not visual-only PMTiles", async () => {
    const context = await releaseContext();
    const dataset = context.dataset("ssp2-45", 2050);
    const artifacts = { ...context.artifacts };
    artifacts[dataset.visualArtifactId] = {
      ...context.artifact(dataset.visualArtifactId),
      role: "projection-analysis-cog",
      mediaType: "image/tiff; application=geotiff; profile=cloud-optimized",
      scientificUse: "exact-lookup",
    } as unknown as ReleaseArtifactV2 & { readonly url: string };
    const invalid = new ReleaseContext({
      manifest: context.manifest,
      manifestUrl: context.manifestUrl,
      disposition: context.disposition,
      artifacts,
      datasets: { ...context.datasets },
    });

    expect(() => resolveMapLayers(invalid, "ssp2-45", 2050)).toThrowError(TechnicalFailure);
  });
});
