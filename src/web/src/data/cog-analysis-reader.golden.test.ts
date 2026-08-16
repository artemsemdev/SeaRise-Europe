// @vitest-environment node

import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReleaseManifestV2 } from "../contracts/generated/release-contract";
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

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function cloneReleaseContext(
  source: ReleaseContext,
  dataReleaseId: string,
  replacementBytes: Uint8Array,
): { readonly context: ReleaseContext; readonly rangeIntegrityBytes: Uint8Array } {
  const targetId = "projection-ssp2-45-2050-cog";
  const rangeId = "cog-range-integrity";
  const replacementSha256 = sha256(replacementBytes);
  const rangeIntegrity = JSON.parse(
    new TextDecoder().decode(fixtureBytes("analysis/cog-range-integrity.json")),
  ) as {
    dataReleaseId: string;
    artifacts: Array<{
      artifactId: string;
      byteSize: number;
      sha256: string;
      chunks: Array<{ start: number; endExclusive: number; sha256: string }>;
    }>;
  };
  rangeIntegrity.dataReleaseId = dataReleaseId;
  const rangeRecord = rangeIntegrity.artifacts.find((artifact) => artifact.artifactId === targetId);
  if (!rangeRecord) throw new Error("missing fixture range identity");
  rangeRecord.byteSize = replacementBytes.byteLength;
  rangeRecord.sha256 = replacementSha256;
  rangeRecord.chunks = [{
    start: 0,
    endExclusive: replacementBytes.byteLength,
    sha256: replacementSha256,
  }];
  const rangeIntegrityBytes = new TextEncoder().encode(`${JSON.stringify(rangeIntegrity)}\n`);
  const rangeIntegritySha256 = sha256(rangeIntegrityBytes);
  const releasePath = `releases/${dataReleaseId}`;
  const manifest = {
    ...source.manifest,
    dataReleaseId,
    publication: { ...source.manifest.publication, releasePath },
    artifacts: source.manifest.artifacts.map((artifact) => ({
      ...artifact,
      dataReleaseId,
      ...(artifact.artifactId === targetId
        ? { byteSize: replacementBytes.byteLength, sha256: replacementSha256 }
        : artifact.artifactId === rangeId
          ? { byteSize: rangeIntegrityBytes.byteLength, sha256: rangeIntegritySha256 }
          : {}),
    })),
  } as ReleaseManifestV2;
  const artifacts = Object.fromEntries(
    Object.values(source.artifacts).map((artifact) => {
      const next = {
        ...artifact,
        dataReleaseId,
        url: artifact.url.replace(source.dataReleaseId, dataReleaseId),
        ...(artifact.artifactId === targetId
          ? { byteSize: replacementBytes.byteLength, sha256: replacementSha256 }
          : artifact.artifactId === rangeId
            ? { byteSize: rangeIntegrityBytes.byteLength, sha256: rangeIntegritySha256 }
            : {}),
      } as ResolvedArtifact;
      return [next.artifactId, Object.freeze(next)];
    }),
  );
  return { context: new ReleaseContext({
    manifest,
    manifestUrl: source.manifestUrl.replace(source.dataReleaseId, dataReleaseId),
    disposition: source.disposition,
    artifacts,
    datasets: { ...source.datasets },
  }), rangeIntegrityBytes };
}

function rangeFetch(calls: RangeCall[]): typeof fetch {
  return async (input, init) => {
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
    const url = new URL(input instanceof Request ? input.url : input.toString());
    const path = fixtureArtifactPath(url);
    const bytes = fixtureBytes(path);
    if (path === "analysis/source-grid.json.gz" || path === "analysis/cog-range-integrity.json") {
      return new Response(responseBody(bytes), {
        status: 200,
        headers: { "content-length": String(bytes.byteLength) },
      });
    }
    if (init?.method === "HEAD") {
      return new Response(null, {
        status: 200,
        headers: {
          "accept-ranges": "bytes",
          "content-length": String(bytes.byteLength),
          etag: `"fixture-${bytes.byteLength}"`,
        },
      });
    }
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
        etag: `"fixture-${bytes.byteLength}"`,
      },
    });
  };
}

describe("exact AR6 COG reader cross-runtime goldens", () => {
  it("uses the exact production source-grid contract and authoritative regional IDs", () => {
    const document = JSON.parse(
      gunzipSync(fixtureBytes("analysis/source-grid.json.gz")).toString("utf8"),
    ) as { releaseContractId: string; locationIds: unknown[] };

    expect(document.releaseContractId).toBe("ar6-europe-regional-release-v1");
    expect(document.locationIds).toHaveLength(76 * 46);
  });

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

  it("rejects scenario/horizon substitution even when release and range hashes bind the wrong COG bytes", async () => {
    const firstContext = await fixtureReleaseContext();
    const secondReleaseId = "searise-europe-v1.0.1-20260816-release-isolation";
    const replacementBytes = fixtureBytes("analysis/ssp5-85/2100.tif");
    const cloned = cloneReleaseContext(firstContext, secondReleaseId, replacementBytes);
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      const path = url.pathname.split(`/${secondReleaseId}/`)[1];
      const bytes = path === "analysis/source-grid.json.gz"
        ? fixtureBytes(path)
        : path === "analysis/cog-range-integrity.json"
          ? cloned.rangeIntegrityBytes
          : replacementBytes;
      if (path === "analysis/source-grid.json.gz" || path === "analysis/cog-range-integrity.json") {
        return new Response(responseBody(bytes), { status: 200 });
      }
      if (init?.method === "HEAD") {
        return new Response(null, { status: 200, headers: {
          "accept-ranges": "bytes", "content-length": String(bytes.length), etag: '"replacement"',
        } });
      }
      const match = /^bytes=(\d+)-(\d+)$/.exec(new Headers(init?.headers).get("range") ?? "");
      if (!match) throw new Error("range required");
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]), bytes.length - 1);
      const body = bytes.slice(start, end + 1);
      return new Response(responseBody(body), {
        status: 206,
        headers: {
          "accept-ranges": "bytes",
          "content-length": String(body.length),
          "content-range": `bytes ${start}-${end}/${bytes.length}`,
        },
      });
    });
    const reader = new CogAnalysisArtifactReader();

    await expect(reader.lookup(
      cloned.context,
      "ssp2-45",
      2050,
      available[0].coordinates,
      new AbortController().signal,
    )).rejects.toMatchObject({ detail: { code: "IntegrityFailed" } });
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
    const base = rangeFetch([]);
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (new Headers(init?.headers).has("range")) {
        return new Response(responseBody(fixtureBytes(fixtureArtifactPath(url))), { status: 200 });
      }
      return base(input, init);
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
    const base = rangeFetch([]);
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      if (new Headers(init?.headers).has("range")) {
        controller.abort();
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 5));
      }
      return base(input, init);
    });
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();

    await expect(
      reader.lookup(context, "ssp2-45", 2050, available[0].coordinates, controller.signal),
    ).rejects.toMatchObject({ detail: { code: "Aborted" } });
  });

  it("keeps a shared range resource alive when an earlier caller is superseded", async () => {
    const firstController = new AbortController();
    const base = rangeFetch([]);
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      if (new Headers(init?.headers).has("range")) {
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 10));
      }
      return base(input, init);
    });
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();
    const first = reader.lookup(
      context,
      "ssp2-45",
      2050,
      available[0].coordinates,
      firstController.signal,
    );
    const second = reader.lookup(
      context,
      "ssp2-45",
      2050,
      available[0].coordinates,
      new AbortController().signal,
    );
    firstController.abort("superseded");

    await expect(first).rejects.toMatchObject({ detail: { code: "Aborted" } });
    await expect(second).resolves.toMatchObject({ kind: "projection" });
  });

  it("keeps missing and corrupt ranges in technical failure states", async () => {
    const context = await fixtureReleaseContext();
    const base = rangeFetch([]);
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) =>
      new Headers(init?.headers).has("range") ? new Response(null, { status: 416 }) : base(input, init));
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
      if (!new Headers(init?.headers).has("range")) return base(input, init);
      const bytes = Uint8Array.from(fixtureBytes(fixtureArtifactPath(url)));
      bytes[0] ^= 1;
      const match = /^bytes=(\d+)-(\d+)$/.exec(new Headers(init?.headers).get("range") ?? "");
      if (!match) throw new Error("range required");
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]), bytes.length - 1);
      const body = bytes.slice(start, end + 1);
      return new Response(responseBody(body), {
        status: 206,
        headers: {
          "accept-ranges": "bytes",
          "content-length": String(body.length),
          "content-range": `bytes ${start}-${end}/${bytes.length}`,
        },
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
    ).rejects.toMatchObject({ detail: { code: "IntegrityFailed" } });
  });
});
