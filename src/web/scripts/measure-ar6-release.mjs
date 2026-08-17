#!/usr/bin/env node
/** Measure an immutable #110 candidate through a real Chromium HTTP Range path. */

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { cpus, platform, release, totalmem } from "node:os";
import { basename, join, resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { once } from "node:events";
import { chromium } from "playwright";

const candidate = resolve(process.argv[2] ?? "");
const output = resolve(process.argv[3] ?? "delivery-trace.json");
const coldIterations = 10;
const warmIterations = 100;
const manifest = JSON.parse(readFileSync(join(candidate, "manifest.json"), "utf8"));
const buildEvidence = JSON.parse(readFileSync(join(candidate, "build-evidence.json"), "utf8"));
const packageLock = readFileSync(resolve("package-lock.json"));
const packageLockDocument = JSON.parse(packageLock.toString("utf8"));
const goldensPath = resolve("src/pipeline/science/evidence/ar6-lookup-goldens.json");
const goldensBytes = readFileSync(goldensPath);
const goldens = JSON.parse(goldensBytes.toString("utf8"));
if (buildEvidence.lookupGoldenEvidence.sha256 !== sha256(goldensBytes)) {
  throw new Error("candidate lookup-golden binding differs from benchmark evidence");
}
const cogRelative = "analysis/ssp2-45/2050.tif";
const gridRelative = "analysis/source-grid.json.gz";
const cog = readFileSync(join(candidate, cogRelative));
const gridGzip = readFileSync(join(candidate, gridRelative));
const grid = JSON.parse(gunzipSync(gridGzip).toString("utf8"));
const golden = goldens.results.find(
  (result) => result.state === "ProjectionAvailable" && result.source,
);
if (!golden) throw new Error("lookup goldens contain no available projection");
const projection = golden.projections.find(
  (item) => item.scenario === "ssp2-45" && item.horizon === 2050,
);
if (!projection) throw new Error("lookup goldens lack the benchmark layer");
const sourceIndex = grid.locationIds.indexOf(golden.source.locationId);
if (sourceIndex < 0) throw new Error("golden source location is absent from source-grid");
const sourceRow = Math.floor(sourceIndex / grid.width);
const sourceColumn = sourceIndex % grid.width;
const cogRow = grid.height - 1 - sourceRow;
const expectedLocationId = grid.locationIds[sourceIndex];
const expectedValuesMillimetres = [
  projection.lowerMillimetres,
  projection.centralMillimetres,
  projection.upperMillimetres,
];
const requests = new Map();

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function record(
  sample,
  kind,
  path,
  artifactPath,
  status,
  responseBytes,
  range,
  contentRange,
) {
  const list = requests.get(sample) ?? [];
  list.push({
    kind,
    path,
    artifactPath,
    status,
    responseBytes,
    range: range ?? null,
    contentRange: contentRange ?? null,
  });
  requests.set(sample, list);
}

function serveBytes(
  request,
  response,
  bytes,
  sample,
  kind,
  path,
  artifactPath,
  contentType,
  contentEncoding,
) {
  const range = request.headers.range;
  response.setHeader("Accept-Ranges", "bytes");
  response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
  response.setHeader("Content-Type", contentType);
  if (contentEncoding) response.setHeader("Content-Encoding", contentEncoding);
  const match = /^bytes=(\d+)-(\d*)$/.exec(range ?? "");
  if (!match) {
    response.writeHead(200, { "Content-Length": bytes.length });
    response.end(bytes);
    record(sample, kind, path, artifactPath, 200, bytes.length, range, null);
    return;
  }
  const start = Number(match[1]);
  const requestedEnd = match[2] ? Number(match[2]) : bytes.length - 1;
  const end = Math.min(requestedEnd, bytes.length - 1);
  const body = bytes.subarray(start, end + 1);
  const contentRange = `bytes ${start}-${end}/${bytes.length}`;
  response.writeHead(206, {
    "Content-Length": body.length,
    "Content-Range": contentRange,
  });
  response.end(body);
  record(sample, kind, path, artifactPath, 206, body.length, range, contentRange);
}

const server = createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const sample = url.searchParams.get("sample") ?? "bootstrap";
  if (url.pathname === "/geotiff.js") {
    const browserBundle = readFileSync(
      resolve("node_modules/geotiff/dist-browser/geotiff.js"),
    );
    response.writeHead(200, { "Content-Type": "text/javascript" });
    response.end(browserBundle);
  } else if (url.pathname === "/projection.tif") {
    serveBytes(
      request,
      response,
      cog,
      sample,
      "cog",
      url.pathname,
      cogRelative,
      "image/tiff",
    );
  } else if (url.pathname === "/source-grid.json.gz") {
    serveBytes(
      request,
      response,
      gridGzip,
      sample,
      "source-grid",
      url.pathname,
      gridRelative,
      "application/json",
      "gzip",
    );
  } else {
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end("<!doctype html><script src='/geotiff.js'></script>");
  }
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
const address = server.address();
if (!address || typeof address === "string") throw new Error("server did not bind TCP");
const origin = `http://127.0.0.1:${address.port}`;
const browser = await chromium.launch({ headless: true, args: ["--enable-precise-memory-info"] });

async function oneLookup(page, sample, reuse) {
  return page.evaluate(
    async ({ origin, sample, sourceColumn, cogRow, expectedLocationId, expectedValuesMillimetres, reuse }) => {
      const started = performance.now();
      const heapBeforeBytes = performance.memory?.usedJSHeapSize ?? -1;
      let peakHeapBytes = heapBeforeBytes;
      const sampleHeap = () => {
        peakHeapBytes = Math.max(peakHeapBytes, performance.memory?.usedJSHeapSize ?? -1);
      };
      const cache = globalThis.__seariseCache ?? {};
      let sourceGrid = cache.sourceGrid;
      let image = cache.image;
      if (!reuse || !sourceGrid) {
        sourceGrid = await (await fetch(`${origin}/source-grid.json.gz?sample=${sample}`)).json();
        sampleHeap();
      }
      if (!reuse || !image) {
        const tiff = await globalThis.GeoTIFF.fromUrl(
          `${origin}/projection.tif?sample=${sample}`,
          { blockSize: 65536, cacheSize: 8 },
        );
        image = await tiff.getImage();
        sampleHeap();
      }
      const values = await image.readRasters({
        window: [sourceColumn, cogRow, sourceColumn + 1, cogRow + 1],
      });
      sampleHeap();
      globalThis.__seariseCache = { sourceGrid, image };
      const sourceRow = sourceGrid.height - 1 - cogRow;
      const actualLocationId = sourceGrid.locationIds[sourceRow * sourceGrid.width + sourceColumn];
      if (actualLocationId !== expectedLocationId) throw new Error("source location ID drifted");
      const valuesMillimetres = Array.from(values, (band) => band[0]);
      if (valuesMillimetres.some((value, index) => value !== expectedValuesMillimetres[index])) {
        throw new Error("COG quantiles differ from the independent golden");
      }
      return {
        durationMilliseconds: performance.now() - started,
        heapBeforeBytes,
        heapAfterBytes: performance.memory?.usedJSHeapSize ?? -1,
        peakHeapBytes,
        locationId: actualLocationId,
        valuesMillimetres,
      };
    },
    { origin, sample, sourceColumn, cogRow, expectedLocationId, expectedValuesMillimetres, reuse },
  );
}

const coldLookupSamples = [];
const warmLookupSamples = [];
let browserVersion;
try {
  browserVersion = browser.version();
  for (let index = 0; index < coldIterations; index += 1) {
    const sample = `cold-${index}`;
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${origin}/?sample=${sample}`);
    const result = await oneLookup(page, sample, false);
    const observed = requests.get(sample) ?? [];
    coldLookupSamples.push({
      ...result,
      rangeRequestCount: observed.filter((item) => item.kind === "cog").length,
      transferBytes: observed.reduce((sum, item) => sum + item.responseBytes, 0),
      requests: observed,
    });
    await context.close();
  }
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${origin}/?sample=warm-bootstrap`);
  await oneLookup(page, "warm-bootstrap", false);
  for (let index = 0; index < warmIterations; index += 1) {
    const sample = `warm-${index}`;
    const result = await oneLookup(page, sample, true);
    const observed = requests.get(sample) ?? [];
    warmLookupSamples.push({
      ...result,
      rangeRequestCount: observed.filter((item) => item.kind === "cog").length,
      transferBytes: observed.reduce((sum, item) => sum + item.responseBytes, 0),
      requests: observed,
    });
  }
  await context.close();
} finally {
  await browser.close();
  server.close();
  await once(server, "close");
}

const artifactHashes = Object.fromEntries(
  manifest.artifacts.map((artifact) => [artifact.path, artifact.sha256]),
);
const artifactByteSizes = Object.fromEntries(
  manifest.artifacts.map((artifact) => [artifact.path, artifact.byteSize]),
);
const trace = {
  schemaVersion: 1,
  harness: "src/web/scripts/measure-ar6-release.mjs",
  candidate: {
    releaseId: manifest.releaseId,
    manifestSha256: sha256(readFileSync(join(candidate, "manifest.json"))),
    artifactHashes,
    artifactByteSizes,
  },
  profiles: {
    hardware: {
      operatingSystem: `${platform()} ${release()}`,
      architecture: process.arch,
      cpu: cpus()[0]?.model ?? "unknown",
      totalMemoryBytes: totalmem(),
    },
    browser: { engine: "Chromium", version: browserVersion },
    network: {
      transport: "loopback-http-1.1",
      cacheControl: "immutable",
      origin,
    },
  },
  target: {
    scenario: "ssp2-45",
    horizon: 2050,
    cogPath: cogRelative,
    sourceGridPath: gridRelative,
    sourceRow,
    sourceColumn,
    cogRow,
    sourceLocationId: expectedLocationId,
    expectedValuesMillimetres,
    goldenEvidenceSha256: sha256(goldensBytes),
  },
  toolchain: {
    playwrightVersion: packageLockDocument.packages["node_modules/playwright"].version,
    geotiffVersion: packageLockDocument.packages["node_modules/geotiff"].version,
    packageLockSha256: sha256(packageLock),
  },
  coldLookupSamples,
  warmLookupSamples,
};
writeFileSync(output, `${JSON.stringify(trace, null, 2)}\n`, "utf8");
process.stdout.write(
  `${JSON.stringify({ output: basename(output), coldIterations, warmIterations }, null, 2)}\n`,
);
