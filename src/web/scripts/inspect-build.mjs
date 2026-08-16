import { brotliCompressSync } from "node:zlib";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import {
  assertSameBuildIdentity,
  buildIdentityFile,
  validateBuildIdentity,
} from "./build-identity.mjs";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
const buildIdentity = validateBuildIdentity(
  JSON.parse(readFileSync(resolve(dist, buildIdentityFile), "utf8")),
);
const releaseId = buildIdentity.dataReleaseId;
const expectedCsp = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'";

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const paths = files(dist);
const required = [
  resolve(dist, "index.html"),
  resolve(dist, "about/architecture/index.html"),
  resolve(dist, "releases", releaseId, "manifest.json"),
  resolve(dist, "vite-manifest.json"),
  resolve(dist, "service-worker.js"),
  resolve(dist, buildIdentityFile),
];
for (const path of required) {
  if (!paths.includes(path)) throw new Error(`Static build is missing ${relative(dist, path)}`);
}

for (const entry of ["index.html", "about/architecture/index.html"]) {
  const html = readFileSync(resolve(dist, entry), "utf8");
  const csp = html.match(/<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"\s*\/?\s*>/i)?.[1];
  if (csp !== expectedCsp) {
    throw new Error(`${entry} does not contain the exact static-document CSP`);
  }
  if (csp.includes("frame-ancestors")) {
    throw new Error(`${entry} must leave frame-ancestors to the deployment response header`);
  }
  if (/(?:^|[;\s])'unsafe-eval'(?:[;\s]|$)/.test(csp)) {
    throw new Error(`${entry} permits JavaScript eval`);
  }
  if (!/<meta\s+name="referrer"\s+content="no-referrer"\s*\/?\s*>/i.test(html)) {
    throw new Error(`${entry} does not enforce the no-referrer document policy`);
  }
}

const workerPaths = paths.filter((path) => /search\.worker-[^/]+\.js$/.test(path));
if (workerPaths.length !== 1) throw new Error("Static build must contain one lazy settlement search worker chunk");
const brotliWasmPaths = paths.filter((path) => /brotli_wasm_bg-[^/]+\.wasm$/.test(path));
if (brotliWasmPaths.length !== 1) throw new Error("Static build must contain one lazy Brotli decoder asset");
const lazySearchPaths = [...workerPaths, ...brotliWasmPaths];
for (const htmlPath of paths.filter((path) => extname(path) === ".html")) {
  const html = readFileSync(htmlPath, "utf8");
  if (lazySearchPaths.some((path) => html.includes(relative(dist, path)))) {
    throw new Error("Settlement search worker and decoder must remain outside the initial HTML dependency graph");
  }
}

const scanned = paths.filter((path) => [".html", ".js", ".css", ".map"].includes(extname(path)));
const forbidden = [/candidate-v7/i, /local-data\/phase-1/i, /["'`]\/[^"'`]*assess(?:[/?"'`]|$)/, /["'`]\/[^"'`]*geocode(?:[/?"'`]|$)/, /["'`]\/[^"'`]*config(?:[/?"'`]|$)/];
for (const path of scanned) {
  const text = readFileSync(path, "utf8");
  if (forbidden.some((pattern) => pattern.test(text))) {
    throw new Error(`Forbidden runtime reference in ${relative(dist, path)}`);
  }
  if (extname(path) === ".js" && /\b(?:new\s+)?Function\s*\(|Error compiling schema, function code/.test(text)) {
    throw new Error(`CSP-incompatible runtime code generation in ${relative(dist, path)}`);
  }
}

const assets = paths
  .filter((path) => [".js", ".css", ".wasm", ".woff2"].includes(extname(path)))
  .map((path) => {
    const bytes = readFileSync(path);
    return {
      path: relative(dist, path),
      bytes: bytes.length,
      brotliBytes: brotliCompressSync(bytes).length,
    };
  })
  .sort((left, right) => left.path.localeCompare(right.path));

const viteManifest = JSON.parse(readFileSync(resolve(dist, "vite-manifest.json"), "utf8"));
const serviceWorkerEntry = viteManifest["src/offline/service-worker.ts"];
if (
  !serviceWorkerEntry ||
  serviceWorkerEntry.file !== "service-worker.js" ||
  (serviceWorkerEntry.imports?.length ?? 0) !== 0 ||
  (serviceWorkerEntry.dynamicImports?.length ?? 0) !== 0 ||
  paths.includes(resolve(dist, "service-worker.js.map"))
) throw new Error("Service worker must be one self-contained root entry without a stale source map");
const serviceWorker = readFileSync(resolve(dist, "service-worker.js"), "utf8");
if (/skipWaiting\s*\(|clients\s*\.\s*claim\s*\(/u.test(serviceWorker)) {
  throw new Error("Worker shell cannot force activation or claim existing clients");
}
function parsedEmbeddedJson(source) {
  return [...source.matchAll(/JSON\.parse\((?:`((?:\\.|[^`\\])*)`|("(?:\\.|[^"\\])*"))\)/gu)]
    .map((match) => {
      try {
        if (match[2]) return JSON.parse(JSON.parse(match[2]));
        try { return JSON.parse(match[1]); }
        catch { return JSON.parse(JSON.parse(`"${match[1]}"`)); }
      } catch { return null; }
    });
}
const embedded = parsedEmbeddedJson(serviceWorker)
  .find((value) => value?.contractVersion === 2 && value?.buildIdentity && Array.isArray(value.urls));
if (!embedded) throw new Error("Service worker has no readable embedded precache authority");

const expectedPrecacheFiles = new Set();
function collectPrecache(key) {
  const entry = viteManifest[key];
  if (!entry || expectedPrecacheFiles.has(entry.file)) return;
  expectedPrecacheFiles.add(entry.file);
  for (const css of entry.css ?? []) expectedPrecacheFiles.add(css);
  for (const asset of entry.assets ?? []) expectedPrecacheFiles.add(asset);
  for (const imported of entry.imports ?? []) collectPrecache(imported);
}
const precacheMainKey = Object.entries(viteManifest).find(([, entry]) =>
  entry.dynamicImports?.includes("src/components/map/MapExplorer.tsx"),
)?.[0];
if (!precacheMainKey) throw new Error("Vite manifest has no precache application entry");
collectPrecache(precacheMainKey);
for (const file of [...expectedPrecacheFiles].filter((path) => path.endsWith(".css"))) {
  const css = readFileSync(resolve(dist, file), "utf8");
  for (const match of css.matchAll(/url\((?:["']?)([^"')]+)(?:["']?)\)/gu)) {
    if (/^(?:data:|https?:)/u.test(match[1])) continue;
    expectedPrecacheFiles.add(match[1].startsWith("/")
      ? match[1].slice(1)
      : join(dirname(file), match[1]).replaceAll("\\", "/"));
  }
}
const expectedPrecacheUrls = [
  "/",
  ...[...expectedPrecacheFiles].map((path) => `/${path}`),
  `/releases/${releaseId}/manifest.json`,
].sort();
const expectedPrecacheHash = createHash("sha256").update(JSON.stringify({
  contractVersion: 2,
  buildIdentity,
  urls: expectedPrecacheUrls,
})).digest("hex");
if (
  JSON.stringify(embedded.urls) !== JSON.stringify(expectedPrecacheUrls) ||
  embedded.precacheSetSha256 !== expectedPrecacheHash ||
  embedded.urls.some((url) => url.startsWith("/about/") ||
    (url.startsWith("/releases/") && url !== buildIdentity.manifestPath))
) throw new Error("Service worker embedded precache differs from the independent shell inventory");
assertSameBuildIdentity(buildIdentity, embedded.buildIdentity, "service worker");
const mainEntry = Object.values(viteManifest).find((entry) =>
  entry.dynamicImports?.includes("src/components/map/MapExplorer.tsx"),
);
if (!mainEntry) throw new Error("Vite manifest has no static application entry");
const application = readFileSync(resolve(dist, mainEntry.file), "utf8");
const applicationIdentity = parsedEmbeddedJson(application)
  .find((value) => value?.schemaVersion === "1.0.0" && value?.manifestPath);
if (!applicationIdentity) throw new Error("Application bundle has no readable canonical build identity");
assertSameBuildIdentity(buildIdentity, applicationIdentity, "application bundle");
const initialFiles = new Set();
function collectInitial(entry) {
  if (!entry || initialFiles.has(entry.file)) return;
  initialFiles.add(entry.file);
  for (const imported of entry.imports ?? []) collectInitial(viteManifest[imported]);
}
collectInitial(mainEntry);
const dynamicFiles = Object.values(viteManifest)
  .filter((entry) => entry.isDynamicEntry)
  .map((entry) => entry.file);
const mapFiles = Object.entries(viteManifest)
  .filter(([key]) => /components\/map\/(?:MapExplorer|map-runtime)\.tsx?$/.test(key))
  .map(([, entry]) => entry.file);
if (mapFiles.length !== 2 || mapFiles.some((file) => initialFiles.has(file))) {
  throw new Error("MapLibre/PMTiles runtime is not isolated from the initial application graph");
}
if (mapFiles.some((file) => !dynamicFiles.includes(file))) {
  throw new Error("Map visualization modules must remain dynamic Vite entries");
}
const mapRuntimeEntry = viteManifest["src/components/map/map-runtime.ts"];
const mapRuntimeSourceMap = JSON.parse(readFileSync(
  resolve(dist, `${mapRuntimeEntry.file}.map`),
  "utf8",
));
const networkSourceIndex = mapRuntimeSourceMap.sources.findIndex((source) =>
  source.endsWith("/components/map/pmtiles-network-source.ts"),
);
const networkSource = mapRuntimeSourceMap.sourcesContent?.[networkSourceIndex];
if (
  networkSourceIndex < 0 ||
  typeof networkSource !== "string" ||
  !networkSource.includes('cache: "no-store"') ||
  !networkSource.includes("new PMTiles(source, cache)") ||
  !networkSource.includes("new NetworkOnlyPmtilesSource(authority)") ||
  /\b(?:indexedDB|sessionStorage|localStorage|CacheStorage)\b|\bcaches\s*\./u.test(networkSource) ||
  /\b(?:ProjectionAvailable|DataUnavailable|OutOfScope|UnsupportedGeography)\b/u.test(networkSource)
) {
  throw new Error("Built PMTiles source is not a network-only, no-store, visual-only adapter");
}
const mapRuntimeJavascript = readFileSync(resolve(dist, mapRuntimeEntry.file), "utf8");
if (!/cache:[`'"]no-store[`'"]/u.test(mapRuntimeJavascript)) {
  throw new Error("Emitted PMTiles adapter does not preserve Request.cache=no-store");
}
if (embedded.urls.some((url) => url.endsWith(".pmtiles"))) {
  throw new Error("Visual PMTiles cannot enter the service-worker precache");
}
const initialJavascript = assets
  .filter((asset) => asset.path.endsWith(".js") && initialFiles.has(asset.path))
  .reduce((total, asset) => total + asset.brotliBytes, 0);
if (initialJavascript > 250 * 1024) {
  throw new Error(`Initial JavaScript exceeds the 250 KiB Brotli budget: ${initialJavascript}`);
}

const report = {
  ...buildIdentity,
  staticRoutes: ["/", "/about/architecture/"],
  bundleIsolation: {
    initialFiles: [...initialFiles].sort(),
    initialJavascriptBrotliBytes: initialJavascript,
    lazyMapFiles: mapFiles.sort(),
  },
  lazyWorkerAssets: lazySearchPaths.map((path) => relative(dist, path)),
  serviceWorker: {
    path: "/service-worker.js",
    scope: "/",
    appBuildId: buildIdentity.appBuildId,
    dataReleaseId: buildIdentity.dataReleaseId,
    precacheSetSha256: embedded.precacheSetSha256,
    precacheUrls: embedded.urls,
    brotliBytes: brotliCompressSync(serviceWorker).length,
  },
  assets,
};
writeFileSync(resolve(dist, "build-report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(`validated ${paths.length} static files; ${assets.length} measured assets`);
