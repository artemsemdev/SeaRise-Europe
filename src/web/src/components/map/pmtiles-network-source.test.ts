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

interface ResponseAuthority {
  readonly byteSize: number;
  readonly sha256: string;
}

function requestAuthority(request: Request): ResponseAuthority {
  const prefix = `/releases/${releaseId}/`;
  const pathname = new URL(request.url).pathname;
  const artifact = fixture.artifacts.find((candidate) => candidate.path === pathname.slice(prefix.length));
  if (!pathname.startsWith(prefix) || !artifact) throw new Error("test request has no fixture authority");
  return artifact;
}

function expectedEtag(authority: ResponseAuthority): string {
  return `"sha256-${authority.sha256}"`;
}

function rangedResponse(
  request: Request,
  body?: Uint8Array,
  extraHeaders: HeadersInit = {},
  authority: ResponseAuthority = requestAuthority(request),
): Response {
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
      "content-range": `bytes ${start}-${end}/${authority.byteSize}`,
      "content-type": "application/vnd.pmtiles",
      etag: expectedEtag(authority),
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
    const projection = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const layer = { ...projection, byteSize: 8, sha256: "a".repeat(64) };
    const etag = expectedEtag(layer);
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
            etag,
          },
        });
      }
      return rangedResponse(request, new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7]), {
        "content-range": "bytes 0-7/8",
      }, layer);
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
    expect(result.etag).toBe(etag);
  });

  it.each([
    ["a missing response ETag", null],
    ["a weak response ETag", "weak"],
    ["a different strong response ETag", `"sha256-${"b".repeat(64)}"`],
  ])("fails closed on %s when a prior strong ETag exists", async (_name, responseEtag) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const priorEtag = expectedEtag(layer);
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => {
        const response = rangedResponse(request);
        if (responseEtag === null) response.headers.delete("etag");
        else response.headers.set("etag", responseEtag === "weak" ? `W/${priorEtag}` : responseEtag);
        return response;
      },
    });
    await expect(source.getBytes(0, 4, undefined, priorEtag)).rejects.toBeInstanceOf(EtagMismatch);
  });

  it.each([
    ["a different total", "bytes 0-7/9", "8"],
    ["a different interval", "bytes 0-6/8", "7"],
    ["a different body length", "bytes 0-7/8", "7"],
  ])("rejects a short-archive retry with %s", async (_name, contentRange, declaredLength) => {
    const projection = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const layer = { ...projection, byteSize: 8, sha256: "a".repeat(64) };
    let calls = 0;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => {
        calls += 1;
        if (calls === 1) {
          return new Response(null, { status: 416, headers: {
            "cache-control": "no-store",
            "content-range": "bytes */8",
            "content-type": "application/vnd.pmtiles",
            etag: expectedEtag(layer),
          } });
        }
        return rangedResponse(request, new Uint8Array(8), {
          "content-length": declaredLength,
          "content-range": contentRange,
        }, layer);
      },
    });
    await expect(source.getBytes(0, 16_384)).rejects.toThrow(/range|length/i);
  });

  it.each([
    ["missing", null],
    ["weak", "weak"],
    ["different", `"sha256-${"b".repeat(64)}"`],
  ])("rejects a %s 416 ETag before retry", async (_name, responseEtag) => {
    const projection = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const layer = { ...projection, byteSize: 8, sha256: "a".repeat(64) };
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async () => new Response(null, {
        status: 416,
        headers: {
          "cache-control": "no-store",
          "content-range": "bytes */8",
          "content-type": "application/vnd.pmtiles",
          ...(responseEtag === null ? {} : {
            etag: responseEtag === "weak" ? `W/${expectedEtag(layer)}` : responseEtag,
          }),
        },
      }),
    });
    await expect(source.getBytes(0, 16_384)).rejects.toThrow(/short-archive length/);
  });

  it.each([
    ["missing", null],
    ["wrong", "application/octet-stream"],
  ])("rejects a 416 response with %s PMTiles media type", async (_name, mediaType) => {
    const projection = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const layer = { ...projection, byteSize: 8, sha256: "a".repeat(64) };
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async () => new Response(null, {
        status: 416,
        headers: {
          "cache-control": "no-store",
          "content-range": "bytes */8",
          etag: expectedEtag(layer),
          ...(mediaType === null ? {} : { "content-type": mediaType }),
        },
      }),
    });
    await expect(source.getBytes(0, 16_384)).rejects.toThrow(/media type/);
  });

  it.each([
    ["missing", null, new Uint8Array([1])],
    ["zero", "0", new Uint8Array()],
  ])("rejects %s Content-Length before accepting a 206 body", async (_name, declaredLength, bytes) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => {
        const response = rangedResponse(request, bytes, {
          "content-range": "bytes 0-0/1",
        });
        if (declaredLength === null) response.headers.delete("content-length");
        else response.headers.set("content-length", declaredLength);
        return response;
      },
    });
    await expect(source.getBytes(0, 1)).rejects.toThrow(
      declaredLength === null ? /missing Content-Length/ : /positive safe integer/,
    );
  });

  it("rejects a zero Content-Length before accepting a 200 body", async () => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async () => new Response(new Uint8Array(), {
        status: 200,
        headers: {
          "cache-control": "no-store",
          "content-length": "0",
          "content-type": "application/vnd.pmtiles",
          etag: expectedEtag(layer),
        },
      }),
    });
    await expect(source.getBytes(0, 4)).rejects.toThrow(/positive safe integer/);
  });

  it("accepts the exact one-byte range edge bytes 0-0/1", async () => {
    const projection = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const layer = { ...projection, byteSize: 1, sha256: "a".repeat(64) };
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request, new Uint8Array([0x2a]), {}, layer),
    });
    expect(new Uint8Array((await source.getBytes(0, 1)).data)).toEqual(new Uint8Array([0x2a]));
  });

  it.each(["", "1e3", "0x10", "9007199254740992"])(
    "rejects non-canonical Content-Length %j",
    async (declaredLength) => {
      const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
      const source = new NetworkOnlyPmtilesSource(layer, {
        fetch: async (request) => rangedResponse(request, new Uint8Array(4), {
          "content-length": declaredLength,
        }),
      });
      await expect(source.getBytes(0, 4)).rejects.toThrow(/Content-Length/);
    },
  );

  it.each([
    ["no-store=false", /no-store/],
    ['extension="no-store, public"', /no-store/],
    ['extension="unterminated, no-store', /malformed/],
  ])("rejects a misleading Cache-Control value %s", async (cacheControl, expected) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request, undefined, { "cache-control": cacheControl }),
    });
    await expect(source.getBytes(0, 4)).rejects.toThrow(expected);
  });

  it("accepts no-store after a quoted extension containing a comma", async () => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request, undefined, {
        "cache-control": 'extension="private, max-age=1", no-store',
      }),
    });
    expect((await source.getBytes(0, 4)).cacheControl).toContain("no-store");
  });

  it.each([
    ["missing no-store", { "cache-control": "public, max-age=31536000, immutable" }, /no-store/],
    ["wrong media type", { "content-type": "application/octet-stream" }, /media type/],
    ["wrong interval", { "content-range": "bytes 1-4/1" }, /exact requested interval/],
    ["wrong authoritative total", { "content-range": "bytes 0-3/1" }, /exact requested interval/],
    ["non-decimal total", { "content-range": "bytes 0-3/1e3" }, /exact requested interval/],
    ["missing Content-Range", { "content-range": "" }, /exact requested interval/],
    ["missing range support", { "accept-ranges": "none" }, /exact requested interval/],
  ])("rejects %s without admitting visual bytes", async (_name, headers, expected) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request, undefined, headers),
    });
    await expect(source.getBytes(0, 4)).rejects.toThrow(expected);
  });

  it.each([204, 500])("rejects unexpected HTTP %s before response identity admission", async (status) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async () => new Response(null, { status, headers: { "cache-control": "no-store" } }),
    });
    await expect(source.getBytes(0, 4)).rejects.toThrow(new RegExp(`HTTP ${status}`));
  });

  it.each([
    ["a redirected response", true, ""],
    ["a different final URL", false, `${origin}/releases/${releaseId}/layers/ssp2-45/2100.pmtiles`],
  ])("rejects %s", async (_name, redirected, finalUrl) => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => {
        const response = rangedResponse(request);
        Object.defineProperty(response, "redirected", { value: redirected });
        Object.defineProperty(response, "url", { value: finalUrl });
        return response;
      },
    });
    await expect(source.getBytes(0, 4)).rejects.toThrow(/escaped its exact release URL/);
  });

  it("rejects ETag drift and unsafe URL/range authority", async () => {
    const layer = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const source = new NetworkOnlyPmtilesSource(layer, {
      fetch: async (request) => rangedResponse(request),
    });
    await expect(source.getBytes(0, 4, undefined, `"sha256-${"f".repeat(64)}"`)).rejects.toBeInstanceOf(EtagMismatch);
    await expect(source.getBytes(0, MAX_PMTILES_RANGE_BYTES + 1)).rejects.toThrow(/at most/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, visualOnly: false as true })).toThrow(/visual-only/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, url: `${layer.url}?selection=private` })).toThrow(/exact release path/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, url: layer.url.replace(`/${releaseId}/`, "/other-release/") })).toThrow(/exact release path/);
    expect(() => new NetworkOnlyPmtilesSource({ ...layer, url: layer.url.replace("2050.pmtiles", "%ZZ.pmtiles") })).toThrow(TypeError);
    expect(() => new NetworkOnlyPmtilesSource(layer, { headers: { Range: "bytes=0-1" } })).toThrow(/override/);
  });

  it("binds boundary PMTiles to the exact candidate artifact mapping", async () => {
    const base = resolveMapLayers(await releaseContext(), "ssp2-45", 2050).projection;
    const support = {
      kind: "support-boundary" as const,
      dataReleaseId: base.dataReleaseId,
      artifactId: "support-boundary-pmtiles",
      byteSize: base.byteSize,
      sha256: base.sha256,
      url: `${origin}/releases/${releaseId}/boundaries/europe.pmtiles`,
      visualOnly: true as const,
    };
    expect(new NetworkOnlyPmtilesSource(support).getKey()).toBe(support.url);
    expect(() => new NetworkOnlyPmtilesSource({ ...support, artifactId: "support-map" })).toThrow(/candidate artifact/);
    expect(() => new NetworkOnlyPmtilesSource({
      ...support,
      url: `${origin}/releases/${releaseId}/boundaries/coastal-analysis-zone.pmtiles`,
    })).toThrow(/candidate artifact/);
  });
});
