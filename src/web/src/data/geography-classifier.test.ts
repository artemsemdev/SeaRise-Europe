// @vitest-environment node

import { describe, expect, it } from "vitest";
import { StaticGeographyClassifier, type GeographyTransport } from "./geography-classifier";
import { TechnicalFailure } from "../domain/release";
import {
  fixtureArtifactPath,
  fixtureBytes,
  fixtureReleaseContext,
  responseBody,
} from "../test/release-fixture";

function fixtureTransport(paths: string[]): GeographyTransport {
  return async (input, init) => {
    if (init.signal.aborted) throw new DOMException("aborted", "AbortError");
    const path = fixtureArtifactPath(input);
    paths.push(path);
    return new Response(responseBody(fixtureBytes(path)), {
      status: 200,
      headers: { "content-type": "application/vnd.apache.parquet" },
    });
  };
}

describe("release-scoped geography classification", () => {
  it.each([
    [51.9244, 4.4777, "InEuropeAndCoastalZone"],
    [52.52, 13.405, "InEuropeOutsideCoastalZone"],
    [40.7128, -74.006, "OutsideEurope"],
    [54.93643, 10.684168, "InEuropeOutsideCoastalZone"],
  ] as const)("classifies %.6f, %.6f with covers semantics", async (latitude, longitude, expected) => {
    const context = await fixtureReleaseContext();
    const calls: string[] = [];
    const classifier = new StaticGeographyClassifier({ transport: fixtureTransport(calls) });

    await expect(
      classifier.classify(context, { latitude, longitude }, new AbortController().signal),
    ).resolves.toBe(expected);
    expect(calls.sort()).toEqual([
      "boundaries/coastal-analysis-zone.parquet",
      "boundaries/europe.parquet",
    ]);
  });

  it("caches only the immutable decoded release boundaries", async () => {
    const context = await fixtureReleaseContext();
    const calls: string[] = [];
    const classifier = new StaticGeographyClassifier({ transport: fixtureTransport(calls) });

    await classifier.classify(context, { latitude: 51.9244, longitude: 4.4777 }, new AbortController().signal);
    await classifier.classify(context, { latitude: 52.52, longitude: 13.405 }, new AbortController().signal);

    expect(calls).toHaveLength(2);
  });

  it("reports corrupt boundary bytes as an integrity failure, never a scientific outcome", async () => {
    const context = await fixtureReleaseContext();
    const classifier = new StaticGeographyClassifier({
      transport: async (input) => {
        const bytes = fixtureBytes(fixtureArtifactPath(input));
        const corrupt = Uint8Array.from(bytes);
        corrupt[0] ^= 1;
        return new Response(responseBody(corrupt), { status: 200 });
      },
    });

    const failure = await classifier
      .classify(context, { latitude: 51.9244, longitude: 4.4777 }, new AbortController().signal)
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(TechnicalFailure);
    expect((failure as TechnicalFailure).detail.code).toBe("IntegrityFailed");
  });
});
