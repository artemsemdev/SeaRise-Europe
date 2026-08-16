// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReleaseManifestV1 } from "../contracts/generated/release-contract";
import { ReleaseContext, type ResolvedArtifact } from "../domain/release";
import { CogAnalysisArtifactReader } from "./cog-analysis-reader";
import {
  fixtureArtifactPath,
  fixtureBytes,
  fixtureReleaseContext,
  responseBody,
} from "../test/release-fixture";

interface GoldenProjection {
  readonly scenario: "ssp1-26" | "ssp2-45" | "ssp5-85";
  readonly horizon: 2030 | 2050 | 2100;
  readonly lowerMillimetres: number;
  readonly centralMillimetres: number;
  readonly upperMillimetres: number;
}

interface AvailableGolden {
  readonly id: string;
  readonly state: "ProjectionAvailable";
  readonly coordinates: { readonly latitude: number; readonly longitude: number };
  readonly source: {
    readonly locationId: number;
    readonly latitude: number;
    readonly longitude: number;
    readonly distanceKilometres: number;
  };
  readonly projections: readonly GoldenProjection[];
}

const goldens = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../pipeline/science/evidence/ar6-lookup-goldens.json"),
    "utf8",
  ),
) as { readonly results: readonly (AvailableGolden | { readonly state: string })[] };
const available = goldens.results.filter(
  (result): result is AvailableGolden => result.state === "ProjectionAvailable",
);

interface RangeCall {
  readonly path: string;
  readonly start: number;
  readonly end: number;
  readonly size: number;
}

function cloneReleaseContext(
  source: ReleaseContext,
  dataReleaseId: string,
  replacement: ResolvedArtifact,
): ReleaseContext {
  const targetId = "projection-ssp2-45-2050-cog";
  const releasePath = `releases/${dataReleaseId}`;
  const manifest = {
    ...source.manifest,
    dataReleaseId,
    publication: { ...source.manifest.publication, releasePath },
    artifacts: source.manifest.artifacts.map((artifact) => ({
      ...artifact,
      dataReleaseId,
      ...(artifact.artifactId === targetId
        ? { byteSize: replacement.byteSize, sha256: replacement.sha256 }
        : {}),
    })),
  } as ReleaseManifestV1;
  const artifacts = Object.fromEntries(
    Object.values(source.artifacts).map((artifact) => {
      const next = {
        ...artifact,
        dataReleaseId,
        url: artifact.url.replace(source.dataReleaseId, dataReleaseId),
        ...(artifact.artifactId === targetId
          ? { byteSize: replacement.byteSize, sha256: replacement.sha256 }
          : {}),
      } as ResolvedArtifact;
      return [next.artifactId, Object.freeze(next)];
    }),
  );
  return new ReleaseContext({
    manifest,
    manifestUrl: source.manifestUrl.replace(source.dataReleaseId, dataReleaseId),
    disposition: source.disposition,
    artifacts,
    datasets: { ...source.datasets },
  });
}

function rangeFetch(calls: RangeCall[]): typeof fetch {
  return async (input, init) => {
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
    const url = new URL(input instanceof Request ? input.url : input.toString());
    const path = fixtureArtifactPath(url);
    const bytes = fixtureBytes(path);
    const range = new Headers(init?.headers).get("range");
    const match = /^bytes=(\d+)-(\d+)$/.exec(range ?? "");
    if (!match) throw new Error(`full-file request prohibited for ${path}`);
    const start = Number(match[1]);
    const requestedEnd = Number(match[2]);
    const end = Math.min(requestedEnd, bytes.byteLength - 1);
    const body = bytes.slice(start, end + 1);
    calls.push({ path, start, end, size: body.byteLength });
    return new Response(responseBody(body), {
      status: 206,
      headers: {
        "accept-ranges": "bytes",
        "content-length": String(body.byteLength),
        "content-range": `bytes ${start}-${end}/${bytes.byteLength}`,
        "content-type": "image/tiff",
      },
    });
  };
}

describe("exact AR6 COG reader cross-runtime goldens", () => {
  const rangeCalls: RangeCall[] = [];

  beforeEach(() => {
    rangeCalls.length = 0;
    vi.stubGlobal("fetch", rangeFetch(rangeCalls));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("matches Python for every source identity and all nine scenario/horizon combinations", async () => {
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();

    for (const scenario of ["ssp1-26", "ssp2-45", "ssp5-85"] as const) {
      for (const horizon of [2030, 2050, 2100] as const) {
        for (const golden of available) {
          const expected = golden.projections.find(
            (projection) => projection.scenario === scenario && projection.horizon === horizon,
          );
          if (!expected) throw new Error(`missing golden ${golden.id}/${scenario}/${horizon}`);
          const actual = await reader.lookup(
            context,
            scenario,
            horizon,
            golden.coordinates,
            new AbortController().signal,
          );
          expect(actual.kind, golden.id).toBe("projection");
          if (actual.kind !== "projection") throw new Error("expected projection");
          expect(actual.source, golden.id).toEqual({
            locationId: golden.source.locationId,
            latitude: golden.source.latitude,
            longitude: golden.source.longitude,
            distanceKilometres: golden.source.distanceKilometres,
          });
          expect(
            [actual.lowerMillimetres, actual.medianMillimetres, actual.upperMillimetres],
            golden.id,
          ).toEqual([
            expected.lowerMillimetres,
            expected.centralMillimetres,
            expected.upperMillimetres,
          ]);
        }
      }
    }

    expect(new Set(rangeCalls.map((call) => call.path))).toEqual(
      new Set(
        ["ssp1-26", "ssp2-45", "ssp5-85"].flatMap((scenario) =>
          [2030, 2050, 2100].map((horizon) => `analysis/${scenario}/${horizon}.tif`),
        ),
      ),
    );
    expect(rangeCalls.every((call) => call.size < 65_536)).toBe(true);
  });

  it("does not reuse a decoded COG across immutable releases sharing one artifact ID", async () => {
    const firstContext = await fixtureReleaseContext();
    const replacement = firstContext.artifact("projection-ssp5-85-2100-cog");
    const secondReleaseId = "searise-europe-v1.0.1-20260816-release-isolation";
    const secondContext = cloneReleaseContext(firstContext, secondReleaseId, replacement);
    const originalBytes = fixtureBytes("analysis/ssp2-45/2050.tif");
    const replacementBytes = fixtureBytes("analysis/ssp5-85/2100.tif");
    const requestedReleases: string[] = [];
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      const bytes = url.pathname.includes(`/${secondReleaseId}/`)
        ? replacementBytes
        : originalBytes;
      requestedReleases.push(url.pathname);
      const match = /^bytes=(\d+)-(\d+)$/.exec(new Headers(init?.headers).get("range") ?? "");
      if (!match) throw new Error("range required");
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]), bytes.length - 1);
      const body = bytes.slice(start, end + 1);
      return new Response(responseBody(body), {
        status: 206,
        headers: { "content-range": `bytes ${start}-${end}/${bytes.length}` },
      });
    });
    const reader = new CogAnalysisArtifactReader();
    const coordinates = available[0].coordinates;

    const first = await reader.lookup(
      firstContext,
      "ssp2-45",
      2050,
      coordinates,
      new AbortController().signal,
    );
    const second = await reader.lookup(
      secondContext,
      "ssp2-45",
      2050,
      coordinates,
      new AbortController().signal,
    );
    const firstGolden = available[0].projections.find(
      (projection) => projection.scenario === "ssp2-45" && projection.horizon === 2050,
    );
    const secondGolden = available[0].projections.find(
      (projection) => projection.scenario === "ssp5-85" && projection.horizon === 2100,
    );
    if (!firstGolden || !secondGolden) throw new Error("release-isolation goldens are incomplete");

    expect(secondContext.dataset("ssp2-45", 2050).analysisArtifactId).toBe(
      firstContext.dataset("ssp2-45", 2050).analysisArtifactId,
    );
    expect(secondContext.artifact("projection-ssp2-45-2050-cog").sha256).not.toBe(
      firstContext.artifact("projection-ssp2-45-2050-cog").sha256,
    );

    expect(first).toMatchObject({
      kind: "projection",
      lowerMillimetres: firstGolden.lowerMillimetres,
      medianMillimetres: firstGolden.centralMillimetres,
      upperMillimetres: firstGolden.upperMillimetres,
    });
    expect(second).toMatchObject({
      kind: "projection",
      lowerMillimetres: secondGolden.lowerMillimetres,
      medianMillimetres: secondGolden.centralMillimetres,
      upperMillimetres: secondGolden.upperMillimetres,
    });
    expect(second).not.toEqual(first);
    expect(requestedReleases.some((path) => path.includes(`/${secondReleaseId}/`))).toBe(true);
  });

  it("returns source nodata without looking for a farther valid cell", async () => {
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();

    await expect(
      reader.lookup(
        context,
        "ssp2-45",
        2050,
        { latitude: 62, longitude: 44 },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      kind: "unavailable",
      reason: "source-value-nodata",
      source: { latitude: 62, longitude: 44 },
    });
  });

  it("maps a north-west grid edge through the declared transform without interpolation", async () => {
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();
    const actual = await reader.lookup(
      context,
      "ssp1-26",
      2030,
      { latitude: 75, longitude: -30 },
      new AbortController().signal,
    );

    expect(actual.source).toEqual({
      locationId: 1_001_503_300,
      latitude: 75,
      longitude: -30,
      distanceKilometres: 0,
    });
  });

  it("keeps cached local lookup p95 below the documented 100 ms gate", async () => {
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();
    const controller = new AbortController();
    await reader.lookup(context, "ssp2-45", 2050, available[0].coordinates, controller.signal);
    const durations: number[] = [];
    for (let index = 0; index < 100; index += 1) {
      const started = performance.now();
      await reader.lookup(context, "ssp2-45", 2050, available[0].coordinates, controller.signal);
      durations.push(performance.now() - started);
    }
    durations.sort((left, right) => left - right);
    expect(durations[Math.ceil(durations.length * 0.95) - 1]).toBeLessThan(100);
  });

  it("rejects a host that substitutes full responses for ranges", async () => {
    vi.stubGlobal("fetch", async (input: URL | RequestInfo) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      return new Response(responseBody(fixtureBytes(fixtureArtifactPath(url))), { status: 200 });
    });
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();

    await expect(
      reader.lookup(
        context,
        "ssp2-45",
        2050,
        available[0].coordinates,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: "RangeUnsupported" } });
  });

  it("turns an aborted range request into a technical cancellation", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();

    await expect(
      reader.lookup(context, "ssp2-45", 2050, available[0].coordinates, controller.signal),
    ).rejects.toMatchObject({ detail: { code: "Aborted" } });
  });

  it("keeps missing and corrupt ranges in technical failure states", async () => {
    const context = await fixtureReleaseContext();
    vi.stubGlobal("fetch", async () => new Response(null, { status: 416 }));
    await expect(
      new CogAnalysisArtifactReader().lookup(
        context,
        "ssp2-45",
        2050,
        available[0].coordinates,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: "FetchFailed" } });

    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      const bytes = Uint8Array.from(fixtureBytes(fixtureArtifactPath(url)));
      bytes[0] ^= 1;
      const match = /^bytes=(\d+)-(\d+)$/.exec(new Headers(init?.headers).get("range") ?? "");
      if (!match) throw new Error("range required");
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]), bytes.length - 1);
      const body = bytes.slice(start, end + 1);
      return new Response(responseBody(body), {
        status: 206,
        headers: { "content-range": `bytes ${start}-${end}/${bytes.length}` },
      });
    });
    await expect(
      new CogAnalysisArtifactReader().lookup(
        context,
        "ssp2-45",
        2050,
        available[0].coordinates,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: "DecodeFailed" } });
  });
});
