import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import type { GeographyClassification, Selection } from "./release";
import {
  AssessmentEngine,
  EARTH_MEAN_RADIUS_KILOMETRES,
  MAXIMUM_SOURCE_DISTANCE_KILOMETRES,
  haversineKilometres,
  mapAssessmentResult,
  selectNearestSourceGridLocation,
  type AnalysisArtifactReader,
  type AnalysisReadResult,
  type GeographyClassifier,
} from "./scientific-lookup";
import { fixtureReleaseContext } from "../test/release-fixture";

const projection: AnalysisReadResult = Object.freeze({
  kind: "projection",
  source: {
    locationId: 1_003_800_040,
    latitude: 52,
    longitude: 4,
    distanceKilometres: 33.792469,
  },
  lowerMillimetres: 133,
  medianMillimetres: 226,
  upperMillimetres: 331,
  baseline: "1995-2014 mean",
  sourceRelease: "20210809",
  sourceMemberSha256: "3f31aadb53b7962a729a839cd58e841f171e72575f9e2b802399be6656aa8cb8",
  nativeResolutionDegrees: 1,
});

function selection(
  dataReleaseId: string,
  coordinates = { latitude: 51.9244, longitude: 4.4777 },
): Selection {
  return {
    dataReleaseId,
    scenario: "ssp2-45",
    horizon: 2050,
    location: { kind: "coordinate", coordinates },
  };
}

function fixedGeography(classification: GeographyClassification): GeographyClassifier {
  return { classify: async () => classification };
}

function fixedAnalysis(result: AnalysisReadResult = projection): AnalysisArtifactReader {
  return { lookup: async () => result };
}

describe("ADR-024 assessment engine", () => {
  it.each([
    ["OutsideEurope", "UnsupportedGeography"],
    ["InEuropeOutsideCoastalZone", "OutOfScope"],
    ["InEuropeAndCoastalZone", "ProjectionAvailable"],
  ] as const)("maps %s exhaustively to %s", async (classification, expected) => {
    const context = await fixtureReleaseContext();
    const engine = new AssessmentEngine({
      geography: fixedGeography(classification),
      analysis: fixedAnalysis(),
    });

    const evaluation = await engine.evaluate(
      context,
      selection(context.dataReleaseId),
      new AbortController().signal,
    );
    expect(evaluation.result.resultState).toBe(expected);
    expect(evaluation.result).toMatchObject({
      dataReleaseId: context.dataReleaseId,
      scenario: "ssp2-45",
      horizon: 2050,
      analysisArtifactId: "projection-ssp2-45-2050-cog",
      visualArtifactId: "projection-ssp2-45-2050-pmtiles",
    });
  });

  it("maps source gaps to DataUnavailable without changing release selection", async () => {
    const context = await fixtureReleaseContext();
    const engine = new AssessmentEngine({
      geography: fixedGeography("InEuropeAndCoastalZone"),
      analysis: fixedAnalysis({
        kind: "unavailable",
        reason: "source-value-nodata",
        source: projection.source,
      }),
    });

    await expect(
      engine.evaluate(context, selection(context.dataReleaseId), new AbortController().signal),
    ).resolves.toMatchObject({
      result: {
        resultState: "DataUnavailable",
        reason: "source-value-nodata",
        dataReleaseId: context.dataReleaseId,
        scenario: "ssp2-45",
        horizon: 2050,
      },
    });
  });

  it("short-circuits both scope outcomes before any analysis-artifact read", async () => {
    const context = await fixtureReleaseContext();
    const lookup = vi.fn<AnalysisArtifactReader["lookup"]>();
    for (const classification of ["OutsideEurope", "InEuropeOutsideCoastalZone"] as const) {
      const engine = new AssessmentEngine({
        geography: fixedGeography(classification),
        analysis: { lookup },
      });
      await engine.evaluate(context, selection(context.dataReleaseId), new AbortController().signal);
    }
    expect(lookup).not.toHaveBeenCalled();
  });

  it("never allows stale work to replace the current result", async () => {
    const context = await fixtureReleaseContext();
    let releaseFirst: ((value: GeographyClassification) => void) | undefined;
    let call = 0;
    const geography: GeographyClassifier = {
      classify: async () => {
        call += 1;
        if (call === 1) {
          return new Promise((resolve) => {
            releaseFirst = resolve;
          });
        }
        return "InEuropeOutsideCoastalZone";
      },
    };
    const engine = new AssessmentEngine({ geography, analysis: fixedAnalysis() });
    const first = engine.evaluate(
      context,
      selection(context.dataReleaseId),
      new AbortController().signal,
    );
    const second = await engine.evaluate(
      context,
      selection(context.dataReleaseId, { latitude: 52.52, longitude: 13.405 }),
      new AbortController().signal,
    );
    releaseFirst?.("InEuropeAndCoastalZone");

    expect(second.result.resultState).toBe("OutOfScope");
    await expect(first).rejects.toMatchObject({ detail: { code: "Aborted" } });
  });

  it("rejects invalid coordinates as a technical validation failure", async () => {
    const context = await fixtureReleaseContext();
    const engine = new AssessmentEngine({
      geography: fixedGeography("OutsideEurope"),
      analysis: fixedAnalysis(),
    });

    await expect(
      engine.evaluate(
        context,
        selection(context.dataReleaseId, { latitude: Number.NaN, longitude: 0 }),
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: "SchemaInvalid" } });
  });

  it("publishes metres by exact 0.001 scaling with the source likely range", async () => {
    const context = await fixtureReleaseContext();
    const dataset = context.dataset("ssp2-45", 2050);
    const analysis = context.artifact(dataset.analysisArtifactId);
    const visual = context.artifact(dataset.visualArtifactId);
    const identity = {
      dataReleaseId: context.dataReleaseId,
      methodologyVersion: context.methodologyVersion,
      scenario: "ssp2-45" as const,
      horizon: 2050 as const,
      analysisArtifactId: analysis.artifactId,
      analysisArtifactSha256: analysis.sha256,
      visualArtifactId: visual.artifactId,
      visualArtifactSha256: visual.sha256,
      visualArtifactUrl: visual.url,
    };

    expect(mapAssessmentResult(identity, "InEuropeAndCoastalZone", projection)).toMatchObject({
      resultState: "ProjectionAvailable",
      lowerMetres: 0.133,
      medianMetres: 0.226,
      upperMetres: 0.331,
      units: "m",
      confidence: "medium",
      baseline: "1995-2014 mean",
    });
  });
});

describe("nearest native AR6 source-grid selection", () => {
  const source = { locationId: 20, latitude: 0, longitude: 0 };
  const boundaryLatitude =
    (MAXIMUM_SOURCE_DISTANCE_KILOMETRES / EARTH_MEAN_RADIUS_KILOMETRES) *
    (180 / Math.PI);

  it("keeps the unrounded inclusive 100 km boundary available", () => {
    const exact = selectNearestSourceGridLocation([source], {
      latitude: boundaryLatitude,
      longitude: 0,
    });
    const beyond = selectNearestSourceGridLocation([source], {
      latitude:
        ((MAXIMUM_SOURCE_DISTANCE_KILOMETRES + 0.001) /
          EARTH_MEAN_RADIUS_KILOMETRES) *
        (180 / Math.PI),
      longitude: 0,
    });

    expect(exact.unroundedDistanceKilometres).toBeLessThanOrEqual(100);
    expect(beyond.unroundedDistanceKilometres).toBeGreaterThan(100);
  });

  it("uses the lowest location ID for an exact tie, including negative longitude", () => {
    const selected = selectNearestSourceGridLocation(
      [
        { locationId: 20, latitude: 0, longitude: -0.5 },
        { locationId: 10, latitude: 0, longitude: 0.5 },
      ],
      { latitude: 0, longitude: 0 },
    );
    expect(selected.candidate.locationId).toBe(10);
  });

  it("always selects the distance minimum and then the lowest ID", () => {
    fc.assert(
      fc.property(
        fc.record({
          latitude: fc.double({ min: -89, max: 89, noNaN: true, noDefaultInfinity: true }),
          longitude: fc.double({ min: -180, max: 180, noNaN: true, noDefaultInfinity: true }),
        }),
        fc.uniqueArray(
          fc.record({
            locationId: fc.integer({ min: 1, max: 10_000 }),
            latitude: fc.double({ min: -90, max: 90, noNaN: true, noDefaultInfinity: true }),
            longitude: fc.double({ min: -180, max: 180, noNaN: true, noDefaultInfinity: true }),
          }),
          { minLength: 1, maxLength: 20, selector: (candidate) => candidate.locationId },
        ),
        (coordinates, candidates) => {
          const expected = candidates
            .map((candidate) => ({
              candidate,
              distance: haversineKilometres(coordinates, candidate),
            }))
            .sort(
              (left, right) =>
                left.distance - right.distance ||
                left.candidate.locationId - right.candidate.locationId,
            )[0];
          const actual = selectNearestSourceGridLocation(candidates, coordinates);

          expect(actual.candidate.locationId).toBe(expected.candidate.locationId);
          expect(actual.unroundedDistanceKilometres).toBe(expected.distance);
        },
      ),
      { numRuns: 500 },
    );
  });
});
