#!/usr/bin/env node
/** Verify real boundary PMTiles decode and rendering through Chromium + MapLibre. */

import { createHash } from "node:crypto";
import { once } from "node:events";
import { readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename, resolve } from "node:path";

import { chromium } from "playwright";

const candidate = resolve(process.argv[2] ?? "");
const output = resolve(process.argv[3] ?? "");
if (!process.argv[2] || !process.argv[3]) {
  throw new Error("usage: verify-boundary-pmtiles-browser.mjs CANDIDATE OUTPUT");
}

const packageLockBytes = readFileSync(resolve("package-lock.json"));
const packageLock = JSON.parse(packageLockBytes);
const maplibreBytes = readFileSync(resolve("node_modules/maplibre-gl/dist/maplibre-gl.js"));
const pmtilesBytes = readFileSync(resolve("node_modules/pmtiles/dist/pmtiles.js"));
const roles = [
  {
    role: "coastal-boundary",
    path: "boundaries/coastal-analysis-zone.pmtiles",
    layer: "coastal_boundary",
  },
  {
    role: "support-boundary",
    path: "boundaries/europe.pmtiles",
    layer: "support_boundary",
  },
];
const zooms = [0, 3, 6];
const requests = [];

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function serveBytes(request, response, bytes, artifactPath) {
  const range = request.headers.range;
  const match = /^bytes=(\d+)-(\d*)$/.exec(range ?? "");
  response.setHeader("Accept-Ranges", "bytes");
  response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
  response.setHeader("Content-Type", "application/vnd.pmtiles");
  if (!match) {
    response.writeHead(200, { "Content-Length": bytes.length });
    response.end(bytes);
    requests.push({ artifactPath, range: range ?? null, responseBytes: bytes.length, status: 200 });
    return;
  }
  const start = Number(match[1]);
  const end = Math.min(match[2] ? Number(match[2]) : bytes.length - 1, bytes.length - 1);
  const body = bytes.subarray(start, end + 1);
  response.writeHead(206, {
    "Content-Length": body.length,
    "Content-Range": `bytes ${start}-${end}/${bytes.length}`,
  });
  response.end(body);
  requests.push({ artifactPath, range, responseBytes: body.length, status: 206 });
}

const artifacts = new Map(
  roles.map((role) => {
    const bytes = readFileSync(resolve(candidate, role.path));
    return [`/${basename(role.path)}`, { bytes, path: role.path }];
  }),
);
const server = createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  if (url.pathname === "/maplibre.js") {
    response.writeHead(200, { "Content-Type": "text/javascript" });
    response.end(maplibreBytes);
  } else if (url.pathname === "/pmtiles.js") {
    response.writeHead(200, { "Content-Type": "text/javascript" });
    response.end(pmtilesBytes);
  } else if (artifacts.has(url.pathname)) {
    const artifact = artifacts.get(url.pathname);
    serveBytes(request, response, artifact.bytes, artifact.path);
  } else {
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(`<!doctype html>
      <style>html,body,#map{height:100%;width:100%;margin:0;background:transparent}</style>
      <script src="/maplibre.js"></script><script src="/pmtiles.js"></script>
      <div id="map"></div>`);
  }
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
const address = server.address();
if (!address || typeof address === "string") throw new Error("browser harness did not bind TCP");
const origin = `http://127.0.0.1:${address.port}`;
const browser = await chromium.launch({ headless: true });
const samples = [];
let browserVersion;
try {
  browserVersion = browser.version();
  const context = await browser.newContext({ viewport: { width: 512, height: 512 } });
  const page = await context.newPage();
  await page.goto(origin);
  for (const role of roles) {
    for (const zoom of zooms) {
      const result = await page.evaluate(
        ({ origin, role, zoom }) =>
          new Promise((resolveSample, rejectSample) => {
            const protocol = new globalThis.pmtiles.Protocol();
            globalThis.maplibregl.addProtocol("pmtiles", protocol.tile);
            const map = new globalThis.maplibregl.Map({
              container: "map",
              center: [6, 52],
              zoom,
              attributionControl: false,
              preserveDrawingBuffer: true,
              style: {
                version: 8,
                sources: {
                  boundary: {
                    type: "vector",
                    url: `pmtiles://${origin}/${role.path.split("/").at(-1)}`,
                  },
                },
                layers: [
                  {
                    id: "boundary-fill",
                    type: "fill",
                    source: "boundary",
                    "source-layer": role.layer,
                    paint: { "fill-color": "#0066ff", "fill-opacity": 1 },
                  },
                ],
              },
            });
            const timeout = setTimeout(() => {
              map.remove();
              rejectSample(new Error(`MapLibre idle timeout for ${role.role} z${zoom}`));
            }, 30000);
            map.once("error", (event) => {
              clearTimeout(timeout);
              map.remove();
              rejectSample(new Error(event.error?.message ?? "MapLibre render failed"));
            });
            map.once("idle", () => {
              clearTimeout(timeout);
              const features = map.queryRenderedFeatures(undefined, {
                layers: ["boundary-fill"],
              });
              const safe = features.every(
                (feature) =>
                  feature.properties.visual_only === true &&
                  feature.properties.analytical_lookup === "prohibited" &&
                  feature.properties.canonical === false &&
                  feature.properties.production === false &&
                  feature.properties.publication_eligible === false &&
                  feature.properties.hazard_extent_claim === false,
              );
              resolveSample({ featureCount: features.length, safe });
              globalThis.__seariseBoundaryMap = map;
            });
          }),
        { origin, role, zoom },
      );
      if (result.featureCount <= 0 || !result.safe) {
        throw new Error(`unsafe or empty browser render for ${role.role} z${zoom}`);
      }
      const screenshot = await page.locator("#map canvas").screenshot({ type: "png" });
      samples.push({
        role: role.role,
        zoom,
        decodedRenderedFeatureCount: result.featureCount,
        screenshot: { byteSize: screenshot.length, sha256: sha256(screenshot) },
      });
      await page.evaluate(() => {
        globalThis.__seariseBoundaryMap.remove();
        delete globalThis.__seariseBoundaryMap;
        globalThis.maplibregl.removeProtocol("pmtiles");
      });
    }
  }
  await context.close();
} finally {
  await browser.close();
  server.close();
  await once(server, "close");
}

for (const role of roles) {
  if (!requests.some((request) => request.artifactPath === role.path && request.status === 206)) {
    throw new Error(`browser made no Range request for ${role.role}`);
  }
}
const inputs = roles.map((role) => {
  const bytes = readFileSync(resolve(candidate, role.path));
  return { role: role.role, path: role.path, byteSize: bytes.length, sha256: sha256(bytes) };
});
writeFileSync(
  output,
  `${JSON.stringify(
    {
      schemaVersion: 1,
      issue: 51,
      status: "passed",
      purpose: "Boundary PMTiles browser compatibility smoke; visual engineering use only.",
      inputs,
      browser: { engine: "Chromium", version: browserVersion, headless: true },
      consumer: {
        maplibreGl: packageLock.packages["node_modules/maplibre-gl"].version,
        pmtiles: packageLock.packages["node_modules/pmtiles"].version,
        playwright: packageLock.packages["node_modules/playwright"].version,
        packageLockSha256: sha256(packageLockBytes),
      },
      runtime: { node: process.version, platform: process.platform, architecture: process.arch },
      assertions: {
        zooms,
        roles: roles.map((role) => role.role),
        everySampleDecodedAndRendered: true,
        safeVisualPropertiesPreserved: true,
        httpRangeUsedForEveryArtifact: true,
      },
      samples,
      requests,
      limitation: {
        visualOnly: true,
        engineeringUse: "engineering-only",
        canonical: false,
        production: false,
        publicationEligible: false,
      },
    },
    null,
    2,
  )}\n`,
);
