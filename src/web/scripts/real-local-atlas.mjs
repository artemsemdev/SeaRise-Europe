import { spawn as nodeSpawn, execFileSync } from "node:child_process";
import { Buffer } from "node:buffer";
import { once } from "node:events";
import { createReadStream, readFileSync, realpathSync, statSync } from "node:fs";
import { request as nodeHttpRequest } from "node:http";
import { basename, dirname, extname, isAbsolute, resolve, sep } from "node:path";
import { createInterface } from "node:readline";
import { clearTimeout, setTimeout } from "node:timers";
import {
  createRealLocalContextMiddleware,
  loadRealLocalContext,
} from "./real-local-context.mjs";

const YEARS = [2030, 2050, 2100];
const PROTECTIONS = ["unprotected", "protected"];
const SHA256 = /^[a-f0-9]{64}$/u;
const MEDIA_TYPES = Object.freeze({
  ".json": "application/json; charset=utf-8",
  ".pbf": "application/x-protobuf",
  ".pmtiles": "application/vnd.pmtiles",
  ".png": "image/png",
});

export const atlasRepositoryRoot = resolve(import.meta.dirname, "../../..");

export function atlasMainRepositoryRoot(repositoryRoot = atlasRepositoryRoot) {
  const common = resolve(
    repositoryRoot,
    execFileSync("git", ["rev-parse", "--git-common-dir"], {
      cwd: repositoryRoot,
      encoding: "utf8",
    }).trim(),
  );
  return basename(common) === ".git" ? dirname(common) : repositoryRoot;
}

export function atlasDataRoot(repositoryRoot = atlasRepositoryRoot) {
  return resolve(
    process.env.SEARISE_ATLAS_ROOT
      ?? resolve(atlasMainRepositoryRoot(repositoryRoot), "local-data/atlas/europe"),
  );
}

export function atlasPythonInvocation(options = {}) {
  const repositoryRoot = options.repositoryRoot ?? atlasRepositoryRoot;
  const atlasRoot = options.atlasRoot ?? atlasDataRoot(repositoryRoot);
  const selectedPython = options.python ?? process.env.SEARISE_ATLAS_PYTHON;
  const python = selectedPython
    ?? resolve(atlasMainRepositoryRoot(repositoryRoot), ".venv/bin/python");
  const args = [
    resolve(repositoryRoot, "scripts/atlas/europe_raster_service.py"),
    "--data-root",
    atlasRoot,
    "--host",
    "127.0.0.1",
    "--port",
    "0",
  ];
  if (selectedPython === undefined && process.platform === "darwin") {
    try {
      if (
        execFileSync("/usr/sbin/sysctl", ["-n", "hw.optional.arm64"], {
          encoding: "utf8",
        }).trim() === "1"
      ) {
        return Object.freeze({ executable: "/usr/bin/arch", args: ["-arm64", python, ...args] });
      }
    } catch {
      // Non-Apple runners use the selected interpreter directly.
    }
  }
  return Object.freeze({ executable: python, args });
}

function exactBounds(value) {
  if (
    !Array.isArray(value)
    || value.length !== 4
    || value.some((coordinate) => !Number.isFinite(coordinate))
    || value[0] < -180
    || value[2] > 180
    || value[1] < -85
    || value[3] > 85
    || value[0] >= value[2]
    || value[1] >= value[3]
  ) {
    throw new Error("The real-local atlas bounds are invalid.");
  }
  return Object.freeze([...value]);
}

function confinedRaster(root, source) {
  if (
    typeof source?.file !== "string"
    || isAbsolute(source.file)
    || source.file.split(/[\\/]/u).includes("..")
    || !new Set([".tif", ".tiff"]).has(extname(source.file).toLowerCase())
    || !Number.isSafeInteger(source.bytes)
    || source.bytes < 1
    || !SHA256.test(source.sha256 ?? "")
    || source.crs !== "EPSG:3035"
    || !Array.isArray(source.pixelSizeMeters)
    || source.pixelSizeMeters[0] !== 25
    || source.pixelSizeMeters[1] !== 25
  ) {
    throw new Error("A real-local raster identity is invalid.");
  }
  exactBounds(source.bounds);
  const path = realpathSync(resolve(root, source.file));
  if (!path.startsWith(`${root}${sep}`) || !statSync(path).isFile()) {
    throw new Error("A real-local raster escapes its data root.");
  }
  if (statSync(path).size !== source.bytes) {
    throw new Error("A real-local raster size differs from its manifest.");
  }
}

function publicSource(source) {
  if (
    typeof source?.name !== "string"
    || typeof source.url !== "string"
    || typeof source.methodologyUrl !== "string"
    || typeof source.license !== "string"
    || !Array.isArray(source.notes)
    || source.notes.length === 0
    || source.notes.some((note) => typeof note !== "string")
  ) {
    throw new Error("The real-local atlas source metadata is invalid.");
  }
  for (const field of [source.url, source.methodologyUrl]) {
    const url = new URL(field);
    if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password) {
      throw new Error("The real-local atlas source URL is invalid.");
    }
  }
  return Object.freeze({
    name: source.name,
    url: source.url,
    methodologyUrl: source.methodologyUrl,
    license: source.license,
    notes: Object.freeze([...source.notes]),
  });
}

export function loadRealLocalAtlasCatalog(root = atlasDataRoot()) {
  const canonicalRoot = realpathSync(root);
  const manifestPath = realpathSync(resolve(canonicalRoot, "manifest.json"));
  if (!manifestPath.startsWith(`${canonicalRoot}${sep}`) || !statSync(manifestPath).isFile()) {
    throw new Error("The real-local atlas manifest escapes its data root.");
  }
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (
    manifest.version !== 2
    || manifest.scenario !== "ssp585"
    || manifest.condition !== "high-tide"
    || !Array.isArray(manifest.layers)
    || manifest.layers.length !== 6
  ) {
    throw new Error("The real-local European atlas manifest is invalid.");
  }
  const identities = new Set();
  const layers = manifest.layers.map((layer) => {
    const identity = `${layer.year}/${layer.protection}`;
    if (
      !YEARS.includes(layer.year)
      || !PROTECTIONS.includes(layer.protection)
      || layer.scenario !== "ssp585"
      || !new Set(["available", "no-valid-data"]).has(layer.status)
      || layer.id !== `ssp585-${layer.year}-${layer.protection}`
      || identities.has(identity)
      || !Array.isArray(layer.inputs)
      || layer.inputs.length === 0
    ) {
      throw new Error("A real-local European atlas layer is invalid.");
    }
    identities.add(identity);
    for (const source of layer.inputs) confinedRaster(canonicalRoot, source);
    return Object.freeze({
      id: layer.id,
      scenario: "ssp585",
      year: layer.year,
      protection: layer.protection,
      status: layer.status,
    });
  });
  return Object.freeze({
    schemaVersion: "coastal-atlas-browser-v1",
    edition: "real-local",
    bounds: exactBounds(manifest.bounds),
    scenario: "ssp585",
    condition: "spring-high-tide",
    cellSizeMeters: 25,
    source: publicSource(manifest.source),
    layers: Object.freeze(layers),
  });
}

function json(response, status, body) {
  const bytes = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": bytes.length,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(bytes);
}

function serveRange(request, response, path, contentType) {
  const size = statSync(path).size;
  const match = /^bytes=(\d+)-(\d*)$/u.exec(request.headers.range ?? "");
  const start = match ? Number(match[1]) : 0;
  const end = match?.[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  if (
    request.headers.range
    && (!match || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size)
  ) {
    response.writeHead(416, {
      "Content-Range": `bytes */${size}`,
      "Cache-Control": "no-store",
    }).end();
    return;
  }
  response.writeHead(match ? 206 : 200, {
    "Content-Type": contentType,
    "Content-Length": end - start + 1,
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, no-cache",
    "X-Content-Type-Options": "nosniff",
    ...(match ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
  });
  const stream = createReadStream(path, { start, end });
  stream.on("error", () => response.destroy());
  response.on("close", () => stream.destroy());
  stream.pipe(response);
}

export function createRasterProxy(port, httpRequest = nodeHttpRequest) {
  return (request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const upstream = httpRequest(
      {
        host: "127.0.0.1",
        port,
        path: `${url.pathname.slice("/atlas-data".length)}${url.search}`,
        method: "GET",
        timeout: 30_000,
      },
      (source) => {
        response.writeHead(source.statusCode ?? 502, source.headers);
        source.pipe(response);
      },
    );
    upstream.on("timeout", () => upstream.destroy(new Error("Raster service timeout")));
    upstream.on("error", () => {
      if (!response.headersSent) response.writeHead(502).end("Local raster service unavailable");
      else response.destroy();
    });
    response.on("close", () => {
      if (!response.writableEnded) upstream.destroy();
    });
    upstream.end();
  };
}

export function createRealLocalAtlasMiddleware({ atlasRoot, catalog, context, rasterPort, httpRequest }) {
  const canonicalRoot = realpathSync(atlasRoot);
  const basemapRoot = realpathSync(resolve(canonicalRoot, "basemap"));
  if (!basemapRoot.startsWith(`${canonicalRoot}${sep}`)) {
    throw new Error("The real-local basemap escapes its data root.");
  }
  const contextMiddleware = createRealLocalContextMiddleware(context);
  const rasterProxy = createRasterProxy(rasterPort, httpRequest);
  return (request, response, next) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (!url.pathname.startsWith("/atlas-data/")) {
      next();
      return;
    }
    if (request.method !== "GET") {
      response.writeHead(405, { Allow: "GET" }).end();
      return;
    }
    if (url.pathname.startsWith("/atlas-data/europe/")) {
      contextMiddleware(request, response, next);
      return;
    }
    if (url.pathname === "/atlas-data/manifest.json" && !url.search) {
      json(response, 200, catalog);
      return;
    }
    if (
      (url.pathname === "/atlas-data/inspect" && url.search)
      || (!url.search && /^\/atlas-data\/tiles\/(2030|2050|2100)\/(unprotected|protected)\/\d+\/\d+\/\d+\.png$/u.test(url.pathname))
    ) {
      rasterProxy(request, response);
      return;
    }
    if (url.pathname.startsWith("/atlas-data/basemap/") && !url.search) {
      let path;
      try {
        path = realpathSync(resolve(basemapRoot, decodeURIComponent(url.pathname.slice(20))));
      } catch {
        response.writeHead(404).end("Local basemap file not found");
        return;
      }
      const contentType = MEDIA_TYPES[extname(path).toLowerCase()];
      if (!path.startsWith(`${basemapRoot}${sep}`) || !contentType || !statSync(path).isFile()) {
        response.writeHead(404).end("Local basemap file not found");
        return;
      }
      serveRange(request, response, path, contentType);
      return;
    }
    response.writeHead(404).end("Atlas resource not found");
  };
}

async function startRasterService(invocation, spawnImpl) {
  const child = spawnImpl(invocation.executable, invocation.args, {
    stdio: ["ignore", "pipe", "inherit"],
  });
  const lines = createInterface({ input: child.stdout });
  const ready = new Promise((accept, reject) => {
    const timer = setTimeout(() => reject(new Error("Local raster startup timed out.")), 30_000);
    const fail = (error) => {
      clearTimeout(timer);
      lines.close();
      reject(error);
    };
    child.once("error", fail);
    child.once("exit", () => fail(new Error("Local raster service exited before startup.")));
    lines.on("line", (line) => {
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        return;
      }
      if (message.ready === true && Number.isInteger(message.port) && message.port > 0 && message.port <= 65_535) {
        clearTimeout(timer);
        lines.close();
        accept({ child, port: message.port });
      }
    });
  });
  try {
    return await ready;
  } catch (error) {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    throw error;
  }
}

export async function createRealLocalAtlas(options = {}) {
  const repositoryRoot = resolve(options.repositoryRoot ?? atlasRepositoryRoot);
  const root = realpathSync(resolve(options.atlasRoot ?? atlasDataRoot(repositoryRoot)));
  const catalog = loadRealLocalAtlasCatalog(root);
  const contextRoot = realpathSync(resolve(root, "context"));
  if (!contextRoot.startsWith(`${root}${sep}`)) {
    throw new Error("The real-local place context escapes its data root.");
  }
  const context = loadRealLocalContext(contextRoot);
  const invocation = atlasPythonInvocation({
    repositoryRoot,
    atlasRoot: root,
    ...(options.python === undefined ? {} : { python: options.python }),
  });
  const { child, port } = await startRasterService(invocation, options.spawn ?? nodeSpawn);
  let closing;
  const close = () => (closing ??= (async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = once(child, "exit");
    child.kill("SIGTERM");
    const force = setTimeout(() => child.kill("SIGKILL"), 2_000);
    force.unref();
    await exited;
    clearTimeout(force);
  })());
  let middleware;
  try {
    middleware = createRealLocalAtlasMiddleware({
      atlasRoot: root,
      catalog,
      context,
      rasterPort: port,
      httpRequest: options.httpRequest,
    });
  } catch (error) {
    await close();
    throw error;
  }
  return Object.freeze({ catalog, middleware, close });
}
