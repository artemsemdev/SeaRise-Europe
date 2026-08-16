import fixture from "../../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { EtagMismatch, ResolvedValueCache } from "pmtiles";
import { describe, expect, it, vi } from "vitest";
import { HORIZON_YEARS, SCENARIO_IDS } from "../../contracts/generated/release-contract";
import { ManifestRepository } from "../../data/manifest-repository";
import { resolveMapLayers } from "../../data/map-layer-resolver";
import {
  MAX_PMTILES_RANGE_BYTES,
  NetworkOnlyPmtilesSource,
  registerNetworkOnlyPmtiles,
} from "./pmtiles-network-source";

const origin = "https://fixture.example";
const releaseId = fixture.dataReleaseId;

async function releaseContext() {
  return new ManifestRepository({
    manifestUrl: `${origin}/releases/${releaseId}/manifest.json`,
    allowedOrigins: [origin],
    expectedDisposition: "synthetic-fixture",
    transport: async () => new Response(JSON.stringify(fixture), {
      headers: { "content-type": "application/json" },
    }),
  }).load(releaseId, new AbortController().signal);
}

function rangedResponse(request: Request, body?: Uint8Array, extraHeaders: HeadersInit = {}): Response {
  const match = /^bytes=(\d+)-(\d+)$/u.exec(request.headers.get("range") ?? "");
  if (!match) throw new Error("test request has no exact range");
  const start = Number(match[1]);
  const end = Number(match[2]);
  const bytes = body ?? new Uint8Array(end - start + 1).fill(0x2a);
  const responseBody = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  return new Response(responseBody, {
    status: 206,
    headers: {
      "accept-ranges": "bytes",
      "cache-control": "no-store",
      "content-length": String(bytes.byteLength),
      "content-range": `bytes ${start}-${end}/1000000`,
      "content-type": "application/vnd.pmtiles",
      etag: '"archive-a"',
      ...extraHeaders,
    },
  });
}

describe("network-only visual PMTiles source", () => {
  it("uses one exact no-store range request for every one of the nine visual identities", async () => {
    const context = await releaseContext();
    const requests: Request[] = [];
    const fetch = vi.fn(async (request: Request) => {
      requests.push(request);
      return rangedResponse(request);
    });
    const layers = SCENARIO_IDS.flatMap((scenario) =>
      HORIZON_YEARS.map((horizon) => resolveMapLayers(context, scenario, horizon).projection),
    );

    for (const [index, layer] of layers.entries()) {
      const result = await new NetworkOnlyPmtilesSource(layer, {
        headers: { "x-visual-request": "release-map" },
        fetch,
      }).getBytes(index * 32, 32);
      expect(new Uint8Array(result.data)).toEqual(new Uint8Array(32).fill(0x2a));
      expect(result.cacheControl).toBe("no-store");
    }

    expect(layers).toHaveLength(9);
    expect(new Set(requests.map(({ url }) => url))).toEqual(new Set(layers.map(({ url }) => url)));
    for (const request of requests) {
      expect(request.method).toBe("GET");
      expect(request.cache).toBe("no-store");
      expect(request.credentials).toBe("omit");
      expect(request.redirect).toBe("error");
      expect(request.referrerPolicy).toBe("no-referrer");
      expect(request.headers.get("accept")).toBe("application/vnd.pmtiles");
      expect(request.headers.get("range")).toMatch(/^bytes=\d+-\d+$/);
      expect(request.headers.get("x-visual-request")).toBe("release-map");
      expect(request.headers.has("if-match")).toBe(false);
    }
  });

  it("registers supported custom Source instances once per exact URL with one bounded metadata cache", async () => {
    const context = await releaseContext();
    const layers = SCENARIO_IDS.flatMap((scenario) =>
      HORIZON_YEARS.map((horizon) => resolveMapLayers(context, scenario, horizon).projection),
    );
    const archives = new Map<string, ReturnType<typeof registerNetworkOnlyPmtiles>>();
    const protocol = {
      add: vi.fn((archive: ReturnType<typeof registerNetworkOnlyPmtiles>) => {
        archives.set(archive.source.getKey(), archive);
      }),
      get: vi.fn((url: string) => archives.get(url)),
    };
    const metadataCache = new ResolvedValueCache(64);

    for (const layer of layers) registerNetworkOnlyPmtiles(protocol, metadataCache, layer);
    registerNetworkOnlyPmtiles(protocol, metadataCache, layers[0]);

    expect(archives.size).toBe(9);
    expect(protocol.add).toHaveBeenCalledTimes(9);
    expect(metadataCache.maxCacheEntries).toBe(64);
    for (const archive of archives.values()) {
      expect(archive.source).toBeInstanceOf(NetworkOnlyPmtilesSource);
      expect(archive.cache).toBe(metadataCache);
      expect("cache" in archive.source).toBe(false);
    }

    expect(() => registerNetworkOnlyPmtiles(
      protocol,
      metadataCache,
      { ...layers[0], visualOnly: false as true },
    )).toThrow(/visual-only/);
    expect(() => registerNetworkOnlyPmtiles(
      protocol,
      metadataCache,
      { ...layers[0], artifactId: "projection-ssp2-45-2050-pmtiles" },
    )).toThrow(/identity/);
    expect(protocol.add).toHaveBeenCalledTimes(9);
  });

  it("preserves abort signals, exact bodies, strong ETags, and the short-archive retry", async () => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const controller = new AbortController();
    const requests: Request[] = [];
    const fetch = vi.fn(async (request: Request) => {
      requests.push(request);
      if (requests.length === 1) {
        return new Response(null, {
          status: 416,
          headers: {
            "cache-control": "no-store",
            "content-range": "bytes */8",
            "content-type": "application/vnd.pmtiles",
          },
        });
      }
      return rangedResponse(request, new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7]), { etag: '"archive-b"' });
    });

    const result = await new NetworkOnlyPmtilesSource(layer, { fetch }).getBytes(
      0,
      16_384,
      controller.signal,
    );

    expect(requests.map((request) => request.headers.get("range"))).toEqual([
      "bytes=0-16383",
      "bytes=0-7",
    ]);
    expect(requests.every((request) => request.cache === "no-store")).toBe(true);
    controller.abort();
    expect(requests.every((request) => request.signal.aborted)).toBe(true);
    expect(new Uint8Array(result.data)).toEqual(new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7]));
    expect(result.etag).toBe('"archive-b"');
  });

  it.each([
    ["missing no-store", { "cache-control": "public, max-age=31536000, immutable" }, /no-store/],
    ["wrong media type", { "content-type": "application/octet-stream" }, /media type/],
    ["wrong interval", { "content-range": "bytes 1-4/1000000" }, /exact requested interval/],
    ["missing range support", { "accept-ranges": "none" }, /exact requested interval/],
  ])("rejects %s without admitting visual bytes", async (_name, headers, expected) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request, undefined, headers),
    });
    await expect(source.getBytes(0, 4)).rejects.toThrow(expected);
  });

  it("rejects ETag drift and unsafe URL/range authority", async () => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request),
    });
    await expect(source.getBytes(0, 4, undefined, '"archive-other"')).rejects.toBeInstanceOf(EtagMismatch);
    await expect(source.getBytes(0, MAX_PMTILES_RANGE_BYTES + 1)).rejects.toThrow(/at most/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, visualOnly: false as true })).toThrow(/visual-only/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, url: `${layer.url}?selection=private` })).toThrow(/exact release path/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, url: layer.url.replace(`/${releaseId}/`, "/other-release/") })).toThrow(/exact release path/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, url: layer.url.replace("2050.pmtiles", "%ZZ.pmtiles") })).toThrow(TypeError);
    expect(() => new NetworkOnlyPmtilesSource(layer, { headers: { Range: "bytes=0-1" } })).toThrow(/override/);
  });
});
