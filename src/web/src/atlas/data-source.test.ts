import { unzlibSync } from "fflate";
import { describe, expect, it, vi } from "vitest";
import { validateAtlasCatalog } from "./browser-data-contract";
import { createAtlasDataSource, DEFAULT_ATLAS_EDITION } from "./create-data-source";
import { AtlasDataSourceError } from "./data-source";
import { createFixtureAtlasDataSource } from "./fixture-data-source";
import { createRealLocalAtlasDataSource } from "./http-data-source";
import {
  SYNTHETIC_ATLAS_CATALOG,
  SYNTHETIC_ATLAS_PLACES,
  searchSyntheticAtlasPlaces,
  syntheticAtlasInspectionAt,
} from "./synthetic-fixture";

const VENICE = SYNTHETIC_ATLAS_PLACES[0];

function tileForCoordinate(longitude: number, latitude: number, z: number) {
  const scale = 2 ** z;
  const latitudeRadians = latitude * Math.PI / 180;
  return {
    z,
    x: Math.floor((longitude + 180) / 360 * scale),
    y: Math.floor((1 - Math.asinh(Math.tan(latitudeRadians)) / Math.PI) / 2 * scale),
  };
}

function pngPixels(data: ArrayBuffer): Readonly<{ width: number; height: number; opaquePixels: number }> {
  const bytes = new Uint8Array(data);
  expect([...bytes.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
  const view = new DataView(data);
  const width = view.getUint32(16, false);
  const height = view.getUint32(20, false);
  let offset = 8;
  const compressed: Uint8Array[] = [];
  while (offset < bytes.length) {
    const length = view.getUint32(offset, false);
    const type = new TextDecoder().decode(bytes.subarray(offset + 4, offset + 8));
    if (type === "IDAT") compressed.push(bytes.slice(offset + 8, offset + 8 + length));
    offset += 12 + length;
  }
  const joined = new Uint8Array(compressed.reduce((total, chunk) => total + chunk.length, 0));
  let compressedOffset = 0;
  for (const chunk of compressed) {
    joined.set(chunk, compressedOffset);
    compressedOffset += chunk.length;
  }
  const scanlines = unzlibSync(joined);
  let opaquePixels = 0;
  for (let row = 0; row < height; row += 1) {
    const rowOffset = row * (1 + width * 4);
    expect(scanlines[rowOffset]).toBe(0);
    for (let column = 0; column < width; column += 1) {
      if (scanlines[rowOffset + 1 + column * 4 + 3] > 0) opaquePixels += 1;
    }
  }
  return Object.freeze({ width, height, opaquePixels });
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

describe("fixture atlas data source", () => {
  it("is the explicit default and performs no fetch", async () => {
    const originalFetch = globalThis.fetch;
    const unexpected = vi.fn(() => Promise.reject(new Error("network must not be used")));
    globalThis.fetch = unexpected as typeof fetch;
    try {
      const source = createAtlasDataSource();
      expect(DEFAULT_ATLAS_EDITION).toBe("synthetic-fixture");
      expect(source.edition).toBe("synthetic-fixture");
      expect((await source.getCatalog()).edition).toBe("synthetic-fixture");
      expect((await source.search("Venice")).results[0]).toEqual(VENICE);
      expect(await source.getPlace(VENICE.id)).toEqual(VENICE);
      expect(unexpected).not.toHaveBeenCalled();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("samples point results from the same bounded grid used for tiles", async () => {
    const source = createFixtureAtlasDataSource();
    expect((await source.inspect({ coordinates: VENICE.coordinates, protection: "unprotected" })).results).toEqual([
      { year: 2030, status: "zero", depthMeters: 0 },
      { year: 2050, status: "flooded", depthMeters: 0.4 },
      { year: 2100, status: "flooded", depthMeters: 1.2 },
    ]);
    for (const place of SYNTHETIC_ATLAS_PLACES.slice(1)) {
      const result = await source.inspect({ coordinates: place.coordinates, protection: "unprotected" });
      expect(result.results.every(({ status, depthMeters }) => status === "unknown" && depthMeters === null)).toBe(true);
    }
    const outside = await source.inspect({ coordinates: [0, 50], protection: "protected" });
    expect(outside).toEqual(syntheticAtlasInspectionAt([0, 50], "protected"));
    expect(outside.results.every(({ status }) => status === "unknown")).toBe(true);
  });

  it("renders deterministic valid PNG tiles and derives output counts from measurements", async () => {
    const source = createFixtureAtlasDataSource();
    const coordinate = tileForCoordinate(VENICE.coordinates[0], VENICE.coordinates[1], 14);
    const dry = await source.getTile({ ...coordinate, year: 2030, protection: "protected" });
    const flooded = await source.getTile({ ...coordinate, year: 2100, protection: "unprotected" });
    const repeated = await source.getTile({ ...coordinate, year: 2100, protection: "unprotected" });

    expect(dry.validPixels).toBeGreaterThan(0);
    expect(dry.floodPixels).toBe(0);
    expect(pngPixels(dry.data)).toEqual({ width: 256, height: 256, opaquePixels: 0 });
    expect(flooded.validPixels).toBeGreaterThan(flooded.floodPixels);
    expect(flooded.floodPixels).toBeGreaterThan(0);
    expect(pngPixels(flooded.data)).toEqual({ width: 256, height: 256, opaquePixels: flooded.floodPixels });
    expect(new Uint8Array(repeated.data)).toEqual(new Uint8Array(flooded.data));
    expect(repeated).toMatchObject({ validPixels: flooded.validPixels, floodPixels: flooded.floodPixels });
  });

  it("renders outside-grid tiles as unknown and rejects invalid or aborted requests", async () => {
    const source = createFixtureAtlasDataSource();
    const outside = await source.getTile({ year: 2050, protection: "unprotected", z: 2, x: 0, y: 0 });
    expect(outside).toMatchObject({ validPixels: 0, floodPixels: 0 });
    expect(pngPixels(outside.data).opaquePixels).toBe(0);

    await expect(source.getTile({ year: 2050, protection: "unprotected", z: 3, x: 8, y: 0 }))
      .rejects.toMatchObject({ code: "invalid-request" });
    const controller = new AbortController();
    controller.abort();
    await expect(source.getCatalog({ signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("real-local HTTP atlas data source", () => {
  it("preserves the accepted routes and validates every success response", async () => {
    const fixture = createFixtureAtlasDataSource();
    const coordinate = tileForCoordinate(VENICE.coordinates[0], VENICE.coordinates[1], 14);
    const tile = await fixture.getTile({ ...coordinate, year: 2100, protection: "protected" });
    const realCatalog = validateAtlasCatalog({
      ...SYNTHETIC_ATLAS_CATALOG,
      edition: "real-local",
      source: { ...SYNTHETIC_ATLAS_CATALOG.source, name: "Example verified real-local source" },
    });
    const requests: string[] = [];
    const requestOptions: Array<RequestInit | undefined> = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push(url);
      requestOptions.push(init);
      if (url.endsWith("/manifest.json")) return json(realCatalog);
      if (url.includes("/europe/search?")) return json(searchSyntheticAtlasPlaces("Venice"));
      if (url.includes("/europe/place?")) return json(VENICE);
      if (url.includes("/inspect?")) return json(syntheticAtlasInspectionAt(VENICE.coordinates, "protected"));
      if (url.includes("/tiles/")) return new Response(tile.data, { headers: {
        "Content-Type": "image/png",
        "X-Valid-Pixels": String(tile.validPixels),
        "X-Flood-Pixels": String(tile.floodPixels),
      } });
      return json({ error: "missing" }, 404);
    }) as typeof fetch;
    const source = createRealLocalAtlasDataSource({ baseUrl: "/atlas-data/", fetch: fetcher });

    expect((await source.getCatalog()).edition).toBe("real-local");
    expect((await source.search("Venice")).results[0]).toEqual(VENICE);
    expect(await source.getPlace(VENICE.id)).toEqual(VENICE);
    expect((await source.inspect({ coordinates: VENICE.coordinates, protection: "protected" })).protection).toBe("protected");
    expect(await source.getTile({ ...coordinate, year: 2100, protection: "protected" })).toMatchObject({
      validPixels: tile.validPixels, floodPixels: tile.floodPixels,
    });
    expect(requests).toEqual([
      "/atlas-data/manifest.json",
      "/atlas-data/europe/search?q=Venice",
      "/atlas-data/europe/place?id=fixture%3Avenice",
      "/atlas-data/inspect?lon=12.3155&lat=45.4408&defenses=protected",
      `/atlas-data/tiles/2100/protected/${coordinate.z}/${coordinate.x}/${coordinate.y}.png`,
    ]);
    for (const init of requestOptions) {
      expect(init).toMatchObject({ method: "GET", cache: "no-store" });
    }
  });

  it("returns null only for a missing place", async () => {
    const fetcher = vi.fn(async () => json({ error: "missing" }, 404)) as typeof fetch;
    const source = createRealLocalAtlasDataSource({ fetch: fetcher });
    await expect(source.getPlace("fixture:missing")).resolves.toBeNull();
    await expect(source.getCatalog()).rejects.toMatchObject({ code: "unavailable" });
  });

  it("never falls back to fixture data when real-local transport fails", async () => {
    const fetcher = vi.fn(async () => { throw new Error("connection refused"); }) as typeof fetch;
    const source = createAtlasDataSource({ edition: "real-local", fetch: fetcher });
    await expect(source.getCatalog()).rejects.toEqual(expect.objectContaining({
      name: "AtlasDataSourceError", code: "unavailable",
    }));
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("rejects wrong-edition JSON, mismatched inspections, and invalid tile metadata", async () => {
    const responses = [
      json(SYNTHETIC_ATLAS_CATALOG),
      json(syntheticAtlasInspectionAt(VENICE.coordinates, "unprotected")),
      new Response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0]), { headers: {
        "Content-Type": "image/png", "X-Valid-Pixels": "1", "X-Flood-Pixels": "2",
      } }),
    ];
    const fetcher = vi.fn(async () => responses.shift()!) as typeof fetch;
    const source = createRealLocalAtlasDataSource({ fetch: fetcher });
    await expect(source.getCatalog()).rejects.toMatchObject({ code: "invalid-response" });
    await expect(source.inspect({ coordinates: VENICE.coordinates, protection: "protected" }))
      .rejects.toMatchObject({ code: "invalid-response" });
    await expect(source.getTile({ year: 2050, protection: "protected", z: 2, x: 2, y: 1 }))
      .rejects.toMatchObject({ code: "invalid-response" });
  });

  it("forwards and preserves cancellation", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      init?.signal?.throwIfAborted();
      return json({});
    }) as typeof fetch;
    const source = createRealLocalAtlasDataSource({ fetch: fetcher });
    const controller = new AbortController();
    controller.abort();
    await expect(source.getCatalog({ signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses one technical error class outside scientific point statuses", () => {
    const error = new AtlasDataSourceError("unavailable", "offline");
    expect(error).toMatchObject({ name: "AtlasDataSourceError", code: "unavailable", message: "offline" });
  });
});
