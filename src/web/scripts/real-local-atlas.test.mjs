import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough, Readable } from "node:stream";
import { setImmediate } from "node:timers";
import { brotliCompressSync } from "node:zlib";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createRealLocalAtlas,
  createRealLocalAtlasMiddleware,
  loadRealLocalAtlasCatalog,
} from "./real-local-atlas.mjs";
import {
  loadRealLocalContext,
  searchRealLocalPlaces,
} from "./real-local-context.mjs";

const temporaryRoots = [];

function temporaryRoot(prefix) {
  const root = mkdtempSync(join(tmpdir(), prefix));
  temporaryRoots.push(root);
  return root;
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixtureRoot(root) {
  const raster = Buffer.from("synthetic raster placeholder");
  mkdirSync(`${root}/rasters`, { recursive: true });
  writeFileSync(`${root}/rasters/venice.tif`, raster);
  const source = {
    file: "rasters/venice.tif",
    bytes: raster.length,
    sha256: "0".repeat(64),
    crs: "EPSG:3035",
    pixelSizeMeters: [25, 25],
    bounds: [12.3, 45.4, 12.4, 45.5],
    overviews: [],
  };
  writeFileSync(`${root}/manifest.json`, JSON.stringify({
    version: 2,
    bounds: [-30.5, 29.5, 45.5, 75.5],
    scenario: "ssp585",
    condition: "high-tide",
    source: {
      name: "CoCliCo coastal flood hazard projections",
      url: "https://example.test/source",
      methodologyUrl: "https://example.test/methodology",
      technicalReportUrl: "https://example.test/private-report-field",
      license: "CC-BY-4.0",
      notes: ["Local source metadata fixture."],
    },
    layers: [2030, 2050, 2100].flatMap((year) =>
      ["unprotected", "protected"].map((protection) => ({
        id: `ssp585-${year}-${protection}`,
        scenario: "ssp585",
        year,
        protection,
        status: "available",
        availabilityMeaning: "fixture-only private field",
        inputs: [{ ...source }],
      }))),
  }));

  const cities = [
    ["geonames:1", "Venice", "IT", "Italy", 12.3155, 45.4408, 250000, ["Venice", "Venezia"]],
    ["geonames:2", "Vénissieux", "FR", "France", 4.88, 45.7, 67000, ["Vénissieux"]],
    ["geonames:3", "Little Venice", "GB", "United Kingdom", -0.18, 51.52, 1000, ["Little Venice"]],
  ];
  const index = brotliCompressSync(Buffer.from(JSON.stringify({
    schemaVersion: 1,
    totalPlaces: cities.length,
    cities,
  })));
  mkdirSync(`${root}/context`, { recursive: true });
  writeFileSync(`${root}/context/cities.json.br`, index);
  writeFileSync(`${root}/context/manifest.json`, JSON.stringify({
    schemaVersion: 1,
    totalPlaces: cities.length,
    index: {
      file: "cities.json.br",
      byteSize: index.length,
      sha256: createHash("sha256").update(index).digest("hex"),
    },
  }));
  mkdirSync(`${root}/basemap/fonts/Test`, { recursive: true });
  writeFileSync(`${root}/basemap/fonts/Test/0-255.pbf`, Buffer.from([1, 2, 3, 4]));
  return root;
}

function captureMiddleware(middleware, url, { method = "GET", headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const response = new PassThrough();
    const chunks = [];
    response.statusCode = 200;
    response.headers = {};
    response.headersSent = false;
    response.writeHead = (status, responseHeaders = {}) => {
      response.statusCode = status;
      response.headers = responseHeaders;
      response.headersSent = true;
      return response;
    };
    response.on("data", (chunk) => chunks.push(chunk));
    response.on("error", reject);
    response.on("finish", () => resolve({
      status: response.statusCode,
      headers: response.headers,
      body: Buffer.concat(chunks),
      next: false,
    }));
    middleware({ url, method, headers }, response, () => resolve({ next: true }));
  });
}

function rasterTransport(calls) {
  return (options, callback) => {
    calls.push(options);
    const request = new EventEmitter();
    request.destroy = vi.fn();
    request.end = () => {
      const source = Readable.from([Buffer.from("raster response")]);
      source.statusCode = 200;
      source.headers = { "content-type": "image/png", "x-valid-pixels": "2", "x-flood-pixels": "1" };
      callback(source);
    };
    return request;
  };
}

function middlewareFor(root, transport) {
  return createRealLocalAtlasMiddleware({
    atlasRoot: root,
    catalog: loadRealLocalAtlasCatalog(root),
    context: loadRealLocalContext(`${root}/context`),
    rasterPort: 43210,
    httpRequest: transport,
  });
}

describe("real-local atlas metadata", () => {
  it("publishes the browser catalog without storage identities or private fields", () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-catalog-"));
    const catalog = loadRealLocalAtlasCatalog(root);

    expect(catalog.edition).toBe("real-local");
    expect(catalog.condition).toBe("spring-high-tide");
    expect(catalog.layers).toHaveLength(6);
    expect(JSON.stringify(catalog)).not.toMatch(/sha256|\.tif|inputs|technicalReport|availabilityMeaning/u);
    expect(catalog.source.name).toContain("CoCliCo");
  });

  it("accepts a syntactically pinned raster without reading its content hash", () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-metadata-"));
    expect(() => loadRealLocalAtlasCatalog(root)).not.toThrow();
  });

  it("rejects a raster symlink that resolves outside the atlas root", () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-confined-"));
    const outside = `${temporaryRoot("searise-atlas-outside-")}/outside.tif`;
    writeFileSync(outside, "outside");
    symlinkSync(outside, `${root}/rasters/escape.tif`);
    const manifest = JSON.parse(readFileSync(`${root}/manifest.json`, "utf8"));
    manifest.layers[0].inputs[0] = {
      ...manifest.layers[0].inputs[0],
      file: "rasters/escape.tif",
      bytes: 7,
    };
    writeFileSync(`${root}/manifest.json`, JSON.stringify(manifest));
    expect(() => loadRealLocalAtlasCatalog(root)).toThrow(/escapes its data root/u);
  });
});

describe("real-local context", () => {
  it("searches normalized aliases deterministically and retrieves exact ids", () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-context-"));
    const context = loadRealLocalContext(`${root}/context`);

    expect(searchRealLocalPlaces(context, "venice").map(({ id }) => id)).toEqual([
      "geonames:1",
      "geonames:3",
    ]);
    expect(searchRealLocalPlaces(context, "venissieux")[0].id).toBe("geonames:2");
    expect(context.byId.get("geonames:1")?.coordinates).toEqual([12.3155, 45.4408]);
  });
});

describe("real-local middleware", () => {
  it("serves catalog, search, byte ranges, and exact raster routes", async () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-middleware-"));
    const calls = [];
    const middleware = middlewareFor(root, rasterTransport(calls));

    const catalog = await captureMiddleware(middleware, "/atlas-data/manifest.json");
    expect(catalog.status).toBe(200);
    expect(JSON.parse(catalog.body).edition).toBe("real-local");

    const search = await captureMiddleware(middleware, "/atlas-data/europe/search?q=Venezia");
    expect(JSON.parse(search.body).results[0].id).toBe("geonames:1");

    const range = await captureMiddleware(
      middleware,
      "/atlas-data/basemap/fonts/Test/0-255.pbf",
      { headers: { range: "bytes=1-2" } },
    );
    expect(range.status).toBe(206);
    expect([...range.body]).toEqual([2, 3]);
    expect(range.headers["Content-Range"]).toBe("bytes 1-2/4");

    const raster = await captureMiddleware(
      middleware,
      "/atlas-data/tiles/2050/protected/12/2188/1456.png",
    );
    expect(raster.status).toBe(200);
    expect(raster.body.toString()).toBe("raster response");
    expect(calls[0]).toMatchObject({
      host: "127.0.0.1",
      port: 43210,
      path: "/tiles/2050/protected/12/2188/1456.png",
      method: "GET",
    });

    const removed = await captureMiddleware(middleware, "/atlas-data/own/inspect");
    expect(removed.status).toBe(404);
    expect(calls).toHaveLength(1);
  });

  it("keeps non-atlas requests outside its boundary and rejects non-GET methods", async () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-methods-"));
    const middleware = middlewareFor(root, rasterTransport([]));

    expect((await captureMiddleware(middleware, "/assets/app.js")).next).toBe(true);
    const post = await captureMiddleware(middleware, "/atlas-data/manifest.json", { method: "POST" });
    expect(post.status).toBe(405);
    expect(post.headers.Allow).toBe("GET");
  });
});

describe("real-local activation", () => {
  it("starts one child, waits for readiness, and closes idempotently", async () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-runtime-"));
    const children = [];
    const spawn = vi.fn(() => {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.exitCode = null;
      child.signalCode = null;
      child.kill = vi.fn((signal) => {
        child.signalCode = signal;
        setImmediate(() => child.emit("exit", null, signal));
      });
      children.push(child);
      setImmediate(() => child.stdout.write('{"ready":true,"port":43210}\n'));
      return child;
    });

    const runtime = await createRealLocalAtlas({
      repositoryRoot: process.cwd(),
      atlasRoot: root,
      python: "/fixture/python",
      spawn,
      httpRequest: rasterTransport([]),
    });

    expect(spawn).toHaveBeenCalledOnce();
    expect(spawn.mock.calls[0][0]).toBe("/fixture/python");
    expect(spawn.mock.calls[0][1]).toContain(`${process.cwd()}/scripts/atlas/europe_raster_service.py`);
    expect(runtime.catalog.edition).toBe("real-local");
    await Promise.all([runtime.close(), runtime.close()]);
    expect(children[0].kill).toHaveBeenCalledOnce();
  });

  it("terminates the raster child when middleware initialization fails", async () => {
    const root = fixtureRoot(temporaryRoot("searise-atlas-startup-failure-"));
    rmSync(`${root}/basemap`, { recursive: true });
    const children = [];
    const spawn = vi.fn(() => {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.exitCode = null;
      child.signalCode = null;
      child.kill = vi.fn((signal) => {
        child.signalCode = signal;
        setImmediate(() => child.emit("exit", null, signal));
      });
      children.push(child);
      setImmediate(() => child.stdout.write('{"ready":true,"port":43210}\n'));
      return child;
    });

    await expect(createRealLocalAtlas({
      repositoryRoot: process.cwd(),
      atlasRoot: root,
      python: "/fixture/python",
      spawn,
    })).rejects.toThrow();

    expect(spawn).toHaveBeenCalledOnce();
    expect(children[0].kill).toHaveBeenCalledOnce();
    expect(children[0].kill).toHaveBeenCalledWith("SIGTERM");
  });
});
