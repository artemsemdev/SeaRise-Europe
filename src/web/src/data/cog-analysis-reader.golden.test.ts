// @vitest-environment node

import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReleaseManifestV2 } from "../contracts/generated/release-contract";
import {
  ReleaseContext,
  type GeographyClassification,
  type ResolvedArtifact,
  type Selection,
} from "../domain/release";
import { AssessmentEngine } from "../domain/scientific-lookup";
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

type OutcomeState =
  | "ProjectionAvailable"
  | "DataUnavailable"
  | "OutOfScope"
  | "UnsupportedGeography";

interface OutcomeParityCase {
  readonly id: string;
  readonly coordinates: { readonly latitude: number; readonly longitude: number };
  readonly geographyClassification: GeographyClassification;
  readonly expected: {
    readonly resultState: OutcomeState;
    readonly reason: string;
    readonly source?: {
      readonly locationId: number;
      readonly latitude: number;
      readonly longitude: number;
      readonly distanceKilometres: number;
    };
    readonly projectionMillimetres?: {
      readonly lower: number;
      readonly median: number;
      readonly upper: number;
    };
  };
  readonly nodataEvidence?: {
    readonly kind: "committed-cog-cell";
    readonly storedNodata: -32768;
    readonly bandValues: readonly [-32768, -32768, -32768];
  };
}

interface OutcomeParityFixture {
  readonly fixtureRole: "authoritative-adr-024-behavior-golden";
  readonly dataProvenanceClass: "synthetic-fixture";
  readonly release: { readonly dataReleaseId: string };
  readonly selection: {
    readonly scenario: "ssp2-45";
    readonly horizon: 2050;
  };
  readonly contract: {
    readonly resultStates: readonly OutcomeState[];
    readonly requiredQuantiles: readonly number[];
    readonly locationSelection: string;
    readonly maximumDistanceKilometres: number;
    readonly distanceLimitInclusive: boolean;
    readonly prohibitedOperations: readonly string[];
  };
  readonly cases: readonly OutcomeParityCase[];
}

const outcomeParity = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../pipeline/science/evidence/ar6-four-outcome-parity-v1.json"),
    "utf8",
  ),
) as OutcomeParityFixture;

interface RangeCall {
  readonly path: string;
  readonly start: number;
  readonly end: number;
  readonly size: number;
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function etag(bytes: Uint8Array): string {
  return `"sha256-${sha256(bytes)}"`;
}

function canonicalRangeChunks(bytes: Uint8Array) {
  const chunks = [];
  for (let start = 0; start < bytes.byteLength; start += 65_536) {
    const endExclusive = Math.min(start + 65_536, bytes.byteLength);
    chunks.push({ start, endExclusive, sha256: sha256(bytes.slice(start, endExclusive)) });
  }
  return chunks;
}

function relocateMainTiffTile(bytes: Uint8Array): Uint8Array {
  const source = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (source.getUint16(0, true) !== 0x4949 || source.getUint16(2, true) !== 42) {
    throw new Error("expected a little-endian classic TIFF fixture");
  }
  const directoryOffset = source.getUint32(4, true);
  const entryCount = source.getUint16(directoryOffset, true);
  let tileOffsetEntry: number | undefined;
  let tileByteCount: number | undefined;
  for (let index = 0; index < entryCount; index += 1) {
    const entry = directoryOffset + 2 + index * 12;
    const tag = source.getUint16(entry, true);
    if (source.getUint16(entry + 2, true) !== 4 || source.getUint32(entry + 4, true) !== 1) continue;
    if (tag === 324) tileOffsetEntry = entry;
    if (tag === 325) tileByteCount = source.getUint32(entry + 8, true);
  }
  if (tileOffsetEntry === undefined || tileByteCount === undefined) {
    throw new Error("expected one LONG TileOffsets and TileByteCounts value");
  }
  const originalOffset = source.getUint32(tileOffsetEntry + 8, true);
  const relocatedOffset = (Math.ceil(bytes.byteLength / 65_536) + 1) * 65_536;
  const relocated = new Uint8Array(relocatedOffset + tileByteCount);
  relocated.set(bytes);
  relocated.set(bytes.slice(originalOffset, originalOffset + tileByteCount), relocatedOffset);
  new DataView(relocated.buffer).setUint32(tileOffsetEntry + 8, relocatedOffset, true);
  return relocated;
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
  rangeRecord.chunks = canonicalRangeChunks(replacementBytes);
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

function clonedRangeFetch(
  releaseId: string,
  replacementBytes: Uint8Array,
  rangeIntegrityBytes: Uint8Array,
  waitForRelocatedRange: (signal: AbortSignal) => Promise<void>,
): typeof fetch {
  return async (input, init) => {
    const signal = init?.signal;
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    const url = new URL(input instanceof Request ? input.url : input.toString());
    const path = url.pathname.split(`/${releaseId}/`)[1];
    if (!path) throw new Error(`unexpected cloned release URL ${url.href}`);
    const bytes = path === "analysis/source-grid.json.gz"
      ? fixtureBytes(path)
      : path === "analysis/cog-range-integrity.json"
        ? rangeIntegrityBytes
        : replacementBytes;
    if (path === "analysis/source-grid.json.gz" || path === "analysis/cog-range-integrity.json") {
      return new Response(responseBody(bytes), { status: 200 });
    }
    if (init?.method === "HEAD") {
      return new Response(null, { status: 200, headers: {
        "accept-ranges": "bytes", "content-length": String(bytes.byteLength), etag: etag(bytes),
      } });
    }
    const match = /^bytes=(\d+)-(\d+)$/.exec(new Headers(init?.headers).get("range") ?? "");
    if (!match) throw new Error("range required");
    const start = Number(match[1]);
    const end = Math.min(Number(match[2]), bytes.byteLength - 1);
    if (start >= 2 * 65_536) await waitForRelocatedRange(signal ?? new AbortController().signal);
    const body = bytes.slice(start, end + 1);
    return new Response(responseBody(body), { status: 206, headers: {
      "accept-ranges": "bytes",
      "content-length": String(body.byteLength),
      "content-range": `bytes ${start}-${end}/${bytes.byteLength}`,
      etag: etag(bytes),
    } });
  };
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
          etag: etag(bytes),
        },
      });
    }
    if (new Headers(init?.headers).get("if-match") !== etag(bytes)) {
      throw new Error(`missing exact If-Match identity for ${path}`);
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
        etag: etag(bytes),
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

  it("matches Python for all and only the four ADR-024 outcomes using a real COG nodata cell", async () => {
    expect(outcomeParity.fixtureRole).toBe("authoritative-adr-024-behavior-golden");
    expect(outcomeParity.dataProvenanceClass).toBe("synthetic-fixture");
    expect(outcomeParity.contract).toEqual({
      resultStates: [
        "ProjectionAvailable",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
      ],
      requiredQuantiles: [0.167, 0.5, 0.833],
      locationSelection: "nearest-source-grid-location",
      maximumDistanceKilometres: 100,
      distanceLimitInclusive: true,
      prohibitedOperations: [
        "interpolation",
        "terrain-comparison",
        "binary-exposure-classification",
        "pmtiles-as-science",
      ],
    });

    const context = await fixtureReleaseContext();
    expect(context.dataReleaseId).toBe(outcomeParity.release.dataReleaseId);
    const reader = new CogAnalysisArtifactReader();
    const actualStates = new Set<OutcomeState>();
    for (const golden of outcomeParity.cases) {
      const engine = new AssessmentEngine({
        geography: { classify: async () => golden.geographyClassification },
        analysis: reader,
      });
      const selection: Selection = {
        dataReleaseId: context.dataReleaseId,
        scenario: outcomeParity.selection.scenario,
        horizon: outcomeParity.selection.horizon,
        location: { kind: "coordinate", coordinates: golden.coordinates },
      };
      const evaluation = await engine.evaluate(
        context,
        selection,
        new AbortController().signal,
      );
      actualStates.add(evaluation.result.resultState);
      expect(evaluation.result, golden.id).toMatchObject({
        resultState: golden.expected.resultState,
        reason: golden.expected.reason,
        ...(golden.expected.source ? { source: golden.expected.source } : {}),
      });
      if (golden.expected.projectionMillimetres) {
        expect(evaluation.result, golden.id).toMatchObject({
          lowerMillimetres: golden.expected.projectionMillimetres.lower,
          medianMillimetres: golden.expected.projectionMillimetres.median,
          upperMillimetres: golden.expected.projectionMillimetres.upper,
        });
      }
      if (golden.nodataEvidence) {
        expect(golden.nodataEvidence).toMatchObject({
          kind: "committed-cog-cell",
          storedNodata: -32768,
          bandValues: [-32768, -32768, -32768],
        });
        expect(evaluation.result.resultState, golden.id).toBe("DataUnavailable");
      }
    }

    expect(actualStates).toEqual(new Set(outcomeParity.contract.resultStates));
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
    expect(rangeCalls.every((call) => call.size <= 65_536)).toBe(true);
    const multichunkPath = "analysis/ssp2-45/2050.tif";
    const multichunkCalls = rangeCalls.filter((call) => call.path === multichunkPath);
    const multichunkSize = fixtureBytes(multichunkPath).byteLength;
    expect(multichunkSize).toBeGreaterThan(2 * 65_536);
    expect(multichunkCalls.some((call) => call.size === 65_536)).toBe(true);
    expect(multichunkCalls.reduce((total, call) => total + call.size, 0)).toBeLessThan(
      multichunkSize,
    );
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
          "accept-ranges": "bytes", "content-length": String(bytes.length), etag: etag(bytes),
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
          etag: etag(bytes),
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

  it("applies the unrounded inclusive 100 km limit in the actual COG reader", async () => {
    const context = await fixtureReleaseContext();
    const reader = new CogAnalysisArtifactReader();
    const exactLatitude = 75 + (100 / 6_371.0088) * (180 / Math.PI);
    const beyondLatitude = 75 + (100.001 / 6_371.0088) * (180 / Math.PI);

    await expect(
      reader.lookup(
        context,
        "ssp1-26",
        2030,
        { latitude: exactLatitude, longitude: -30 },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ kind: "projection", source: { distanceKilometres: 100 } });
    await expect(
      reader.lookup(
        context,
        "ssp1-26",
        2030,
        { latitude: beyondLatitude, longitude: -30 },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      kind: "unavailable",
      reason: "source-location-too-distant",
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

  it.each([
    ["missing HEAD ETag", "head", null, "RangeUnsupported"],
    ["mismatched HEAD ETag", "head", '"sha256-wrong"', "IntegrityFailed"],
    ["missing range ETag", "range", null, "RangeUnsupported"],
    ["changed range ETag", "range", '"sha256-changed"', "IntegrityFailed"],
  ] as const)("fails closed for %s", async (_label, stage, replacement, expectedCode) => {
    const base = rangeFetch([]);
    vi.stubGlobal("fetch", async (input: URL | RequestInfo, init?: RequestInit) => {
      const response = await base(input, init);
      const isTarget = stage === "head"
        ? init?.method === "HEAD"
        : new Headers(init?.headers).has("range");
      if (!isTarget) return response;
      const headers = new Headers(response.headers);
      if (replacement === null) headers.delete("etag");
      else headers.set("etag", replacement);
      return new Response(init?.method === "HEAD" ? null : await response.arrayBuffer(), {
        status: response.status,
        headers,
      });
    });
    const context = await fixtureReleaseContext();

    await expect(
      new CogAnalysisArtifactReader().lookup(
        context,
        "ssp2-45",
        2050,
        available[0].coordinates,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: expectedCode } });
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

  it("aborts an uncached post-open range transport when its last caller cancels", async () => {
    const source = await fixtureReleaseContext();
    const releaseId = "searise-europe-v1.0.1-20260816-post-open-abort";
    const relocated = relocateMainTiffTile(fixtureBytes("analysis/ssp2-45/2050.tif"));
    const cloned = cloneReleaseContext(source, releaseId, relocated);
    let resolveStarted!: () => void;
    const started = new Promise<void>((resolve) => { resolveStarted = resolve; });
    let transportSignal: AbortSignal | undefined;
    const fetcher = clonedRangeFetch(
      releaseId,
      relocated,
      cloned.rangeIntegrityBytes,
      (signal) => {
        transportSignal = signal;
        resolveStarted();
        return new Promise((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        });
      },
    );
    const reader = new CogAnalysisArtifactReader({ fetch: fetcher });
    await expect(
      reader.lookup(
        cloned.context,
        "ssp2-45",
        2050,
        { latitude: 90, longitude: -30 },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ kind: "unavailable", reason: "source-location-too-distant" });

    const controller = new AbortController();
    const lookup = reader.lookup(
      cloned.context,
      "ssp2-45",
      2050,
      available[0].coordinates,
      controller.signal,
    );
    await started;
    expect(transportSignal?.aborted).toBe(false);
    controller.abort("superseded");

    await expect(lookup).rejects.toMatchObject({ detail: { code: "Aborted" } });
    expect(transportSignal?.aborted).toBe(true);
  });

  it("keeps an uncached post-open range alive for a remaining shared caller", async () => {
    const source = await fixtureReleaseContext();
    const releaseId = "searise-europe-v1.0.1-20260816-post-open-shared";
    const relocated = relocateMainTiffTile(fixtureBytes("analysis/ssp2-45/2050.tif"));
    const cloned = cloneReleaseContext(source, releaseId, relocated);
    let resolveStarted!: () => void;
    const started = new Promise<void>((resolve) => { resolveStarted = resolve; });
    let releaseRange!: () => void;
    const rangeGate = new Promise<void>((resolve) => { releaseRange = resolve; });
    let transportSignal: AbortSignal | undefined;
    const reader = new CogAnalysisArtifactReader({
      fetch: clonedRangeFetch(
        releaseId,
        relocated,
        cloned.rangeIntegrityBytes,
        (signal) => {
          transportSignal = signal;
          resolveStarted();
          return rangeGate;
        },
      ),
    });
    await reader.lookup(
      cloned.context,
      "ssp2-45",
      2050,
      { latitude: 90, longitude: -30 },
      new AbortController().signal,
    );
    const firstController = new AbortController();
    const first = reader.lookup(
      cloned.context,
      "ssp2-45",
      2050,
      available[0].coordinates,
      firstController.signal,
    );
    const second = reader.lookup(
      cloned.context,
      "ssp2-45",
      2050,
      available[0].coordinates,
      new AbortController().signal,
    );
    await started;
    firstController.abort("superseded");
    await expect(first).rejects.toMatchObject({ detail: { code: "Aborted" } });
    expect(transportSignal?.aborted).toBe(false);
    releaseRange();

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
          etag: etag(fixtureBytes(fixtureArtifactPath(url))),
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
