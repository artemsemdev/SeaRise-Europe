import { brotliCompressSync } from "node:zlib";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const expectedCsp = "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tiles.openfreemap.org; connect-src 'self' https://tiles.openfreemap.org; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; manifest-src 'self'; media-src 'none'";

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
const mainEntry = Object.values(viteManifest).find((entry) =>
  entry.dynamicImports?.includes("src/components/map/MapExplorer.tsx"),
);
if (!mainEntry) throw new Error("Vite manifest has no static application entry");
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
const initialJavascript = assets
  .filter((asset) => asset.path.endsWith(".js") && initialFiles.has(asset.path))
  .reduce((total, asset) => total + asset.brotliBytes, 0);
if (initialJavascript > 250 * 1024) {
  throw new Error(`Initial JavaScript exceeds the 250 KiB Brotli budget: ${initialJavascript}`);
}

const report = {
  schemaVersion: "1.0.0",
  appBuildId: process.env.SEARISE_APP_BUILD_ID ?? "local-fixture",
  dataReleaseId: releaseId,
  releaseDisposition: "synthetic-fixture",
  staticRoutes: ["/", "/about/architecture/"],
  bundleIsolation: {
    initialFiles: [...initialFiles].sort(),
    initialJavascriptBrotliBytes: initialJavascript,
    lazyMapFiles: mapFiles.sort(),
  },
  lazyWorkerAssets: lazySearchPaths.map((path) => relative(dist, path)),
  assets,
};
writeFileSync(resolve(dist, "build-report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(`validated ${paths.length} static files; ${assets.length} measured assets`);
