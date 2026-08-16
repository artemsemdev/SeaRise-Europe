// @vitest-environment node

import { describe, expect, it } from "vitest";
import { StaticGeographyClassifier, type GeographyTransport } from "./geography-classifier";
import { ReleaseContext, TechnicalFailure, type ResolvedArtifact } from "../domain/release";
import {
  FIXTURE_ORIGIN,
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

  it("keys boundary caches by the exact release artifact identities", async () => {
    const context = await fixtureReleaseContext();
    const artifacts = Object.fromEntries(Object.values(context.artifacts).map((artifact) => {
      const next = artifact.role === "support-boundary" || artifact.role === "coastal-boundary"
        ? Object.freeze({ ...artifact, url: artifact.url.replace(FIXTURE_ORIGIN, "https://mirror.searise.invalid") })
        : artifact;
      return [next.artifactId, next as ResolvedArtifact];
    }));
    const mirror = new ReleaseContext({
      manifest: context.manifest,
      manifestUrl: context.manifestUrl,
      disposition: context.disposition,
      artifacts,
      datasets: { ...context.datasets },
    });
    const calls: string[] = [];
    const classifier = new StaticGeographyClassifier({
      transport: async (input) => {
        calls.push(input.origin);
        const path = input.pathname.split(`/${context.dataReleaseId}/`)[1];
        return new Response(responseBody(fixtureBytes(path)), { status: 200 });
      },
    });

    await classifier.classify(context, { latitude: 51.9244, longitude: 4.4777 }, new AbortController().signal);
    await classifier.classify(mirror, { latitude: 51.9244, longitude: 4.4777 }, new AbortController().signal);

    expect(calls).toHaveLength(4);
    expect(new Set(calls)).toEqual(new Set([FIXTURE_ORIGIN, "https://mirror.searise.invalid"]));
  });

  it("does not let an aborted caller poison a shared boundary load", async () => {
    const context = await fixtureReleaseContext();
    const calls: string[] = [];
    const resourceSignals: AbortSignal[] = [];
    const firstController = new AbortController();
    const classifier = new StaticGeographyClassifier({
      transport: async (input, init) => {
        resourceSignals.push(init.signal);
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 10));
        return fixtureTransport(calls)(input, init);
      },
    });
    const first = classifier.classify(
      context,
      { latitude: 51.9244, longitude: 4.4777 },
      firstController.signal,
    );
    const second = classifier.classify(
      context,
      { latitude: 51.9244, longitude: 4.4777 },
      new AbortController().signal,
    );
    firstController.abort("superseded");

    await expect(first).rejects.toMatchObject({ detail: { code: "Aborted" } });
    expect(resourceSignals.every((signal) => !signal.aborted)).toBe(true);
    await expect(second).resolves.toBe("InEuropeAndCoastalZone");
    expect(calls).toHaveLength(2);
  });

  it("cancels the shared boundary transport only after every caller aborts", async () => {
    const context = await fixtureReleaseContext();
    const resourceSignals: AbortSignal[] = [];
    const classifier = new StaticGeographyClassifier({
      transport: async (_input, init) => {
        resourceSignals.push(init.signal);
        return new Promise<Response>((_resolve, reject) => {
          if (init.signal.aborted) {
            reject(new DOMException("aborted", "AbortError"));
            return;
          }
          init.signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        });
      },
    });
    const firstController = new AbortController();
    const secondController = new AbortController();
    const first = classifier.classify(
      context,
      { latitude: 51.9244, longitude: 4.4777 },
      firstController.signal,
    );
    const second = classifier.classify(
      context,
      { latitude: 51.9244, longitude: 4.4777 },
      secondController.signal,
    );
    await Promise.resolve();

    firstController.abort("first cancelled");
    await expect(first).rejects.toMatchObject({ detail: { code: "Aborted" } });
    expect(resourceSignals).toHaveLength(2);
    expect(new Set(resourceSignals).size).toBe(1);
    expect(resourceSignals[0].aborted).toBe(false);

    secondController.abort("second cancelled");
    await expect(second).rejects.toMatchObject({ detail: { code: "Aborted" } });
    expect(resourceSignals[0].aborted).toBe(true);
  });

  it("normalizes artifact-body failures without exposing transport exceptions", async () => {
    const context = await fixtureReleaseContext();
    const classifier = new StaticGeographyClassifier({
      transport: async () => {
        const response = new Response(null, { status: 200 });
        Object.defineProperty(response, "arrayBuffer", {
          value: async () => {
            throw new Error("private transport implementation detail");
          },
        });
        return response;
      },
    });

    const failure = await classifier
      .classify(context, { latitude: 51.9244, longitude: 4.4777 }, new AbortController().signal)
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(TechnicalFailure);
    expect(failure).toMatchObject({ detail: { code: "FetchFailed", recoverable: true } });
    expect((failure as Error).message).not.toContain("private transport implementation detail");
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
