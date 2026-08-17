import { Buffer } from "node:buffer";
import { timingSafeEqual } from "node:crypto";
import { createReadStream, lstatSync, readFileSync, realpathSync } from "node:fs";
import { createServer } from "node:http";
import { extname, relative, resolve, sep } from "node:path";
import { releaseDeliveryPolicy } from "./release-delivery-policy.mjs";
import {
  OFFLINE_LIFECYCLE_DEPLOYMENTS,
  validateOfflineLifecycleDeployment,
} from "./offline-lifecycle-fixtures.mjs";

export const OFFLINE_LIFECYCLE_CONTROL_HEADER = "x-searise-lifecycle-token";
const CONTROL_PREFIX = "/__lifecycle/";
const MAX_CONTROL_BODY = 1024;
const MAX_LOG_ENTRIES = 2_000;
const CONTENT_TYPES = Object.freeze({
  ".br": "application/octet-stream",
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".tif": "image/tiff",
  ".wasm": "application/wasm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
});

function json(response, status, value) {
  const body = `${JSON.stringify(value)}\n`;
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Length": String(Buffer.byteLength(body)),
    "Content-Type": "application/json; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
  }).end(body);
}

function authenticated(request, token) {
  const supplied = request.headers[OFFLINE_LIFECYCLE_CONTROL_HEADER];
  if (typeof supplied !== "string") return false;
  const actual = Buffer.from(supplied);
  const expected = Buffer.from(token);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

async function body(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > MAX_CONTROL_BODY) throw new Error("Control request body is too large.");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function canonicalPath(pathname) {
  let decoded;
  try { decoded = decodeURIComponent(pathname); } catch { throw new Error("Malformed request path."); }
  if (!decoded.startsWith("/") || decoded.includes("\\") || decoded.includes("\0") || decoded.includes("%")) {
    throw new Error("Non-canonical request path.");
  }
  const parts = decoded.split("/");
  if (parts.some((part) => part === "." || part === "..")) throw new Error("Path traversal is forbidden.");
  if (decoded === "/") return "index.html";
  if (decoded === "/about/architecture/") return "about/architecture/index.html";
  if (decoded.endsWith("/")) throw new Error("Unknown directory route.");
  return decoded.slice(1);
}

function regularFile(root, relativePath) {
  const target = resolve(root, relativePath);
  if (target === root || !target.startsWith(`${root}${sep}`)) throw new Error("Path escaped deployment root.");
  const metadata = lstatSync(target);
  if (!metadata.isFile() || metadata.isSymbolicLink()) throw new Error("Static target is not a regular file.");
  const realRoot = realpathSync(root);
  const realTarget = realpathSync(target);
  const child = relative(realRoot, realTarget);
  if (!child || child === ".." || child.startsWith(`..${sep}`)) throw new Error("Static target escaped deployment root.");
  return Object.freeze({ target, size: metadata.size });
}

function parsedRange(value, size) {
  if (value === undefined) return null;
  if (typeof value !== "string") throw new Error("Multiple byte ranges are forbidden.");
  const match = /^bytes=(\d+)-(\d*)$/u.exec(value);
  if (!match) throw new Error("Malformed byte range.");
  const start = Number(match[1]);
  const requestedEnd = match[2] ? Number(match[2]) : size - 1;
  const end = Math.min(requestedEnd, size - 1);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(requestedEnd) || start < 0 || start > end || start >= size) {
    throw new Error("Unsatisfiable byte range.");
  }
  return Object.freeze({ start, end });
}

function immutableAsset(path) {
  return path.startsWith("assets/") && /-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$/u.test(path);
}

function staticHeaders(path, deployment, size) {
  const prefix = `releases/${deployment.identity.dataReleaseId}/`;
  if (path.startsWith(prefix)) {
    const releasePath = path.slice(prefix.length);
    const artifact = deployment.artifactByPath.get(releasePath);
    const policy = releaseDeliveryPolicy(releasePath, artifact, size);
    return {
      "Accept-Ranges": "bytes",
      "Cache-Control": policy.cacheControl,
      "Content-Type": policy.contentType,
      ...(policy.etag ? { ETag: policy.etag } : {}),
    };
  }
  const noStore = path === "index.html" || path === "service-worker.js" ||
    path === "build-identity.json" || path === "build-report.json" ||
    path === "assets/application-build-identity.js";
  return {
    "Cache-Control": noStore ? "no-store" : immutableAsset(path) ? "public, max-age=31536000, immutable" : "no-cache",
    "Content-Type": CONTENT_TYPES[extname(path)] ?? "application/octet-stream",
    ...(path === "service-worker.js" ? { "Service-Worker-Allowed": "/" } : {}),
  };
}

function runtimeDeployment(record) {
  const manifest = JSON.parse(readFileSync(resolve(record.root, record.identity.manifestPath.slice(1)), "utf8"));
  return Object.freeze({
    ...record,
    artifactByPath: new Map(manifest.artifacts.map((artifact) => [artifact.path, artifact])),
  });
}

export function createOfflineLifecycleServer({
  fixtures,
  controlToken,
  validateDeployment = validateOfflineLifecycleDeployment,
  maxLogEntries = MAX_LOG_ENTRIES,
}) {
  if (typeof controlToken !== "string" || controlToken.length < 32 || controlToken.length > 256) {
    throw new Error("Lifecycle control token must contain 32-256 characters.");
  }
  if (!Number.isSafeInteger(maxLogEntries) || maxLogEntries < 1 || maxLogEntries > MAX_LOG_ENTRIES) {
    throw new Error("Lifecycle request-log bound is invalid.");
  }
  const configured = new Map();
  for (const [label, expected] of Object.entries(OFFLINE_LIFECYCLE_DEPLOYMENTS)) {
    const candidate = fixtures.deployments.get(label);
    if (!candidate) throw new Error(`Lifecycle deployment ${label} is unavailable.`);
    configured.set(label, runtimeDeployment(validateDeployment(candidate.root, expected)));
  }
  let active = "A";
  let generation = 1;
  const requests = [];
  const record = (entry) => {
    requests.push(Object.freeze(entry));
    if (requests.length > maxLogEntries) requests.splice(0, requests.length - maxLogEntries);
  };

  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (url.pathname.startsWith(CONTROL_PREFIX)) {
      if (url.pathname === `${CONTROL_PREFIX}healthz` && request.method === "GET") {
        json(response, 200, { ready: true, deployment: active, generation });
        return;
      }
      if (!authenticated(request, controlToken)) {
        json(response, 403, { error: "Forbidden" });
        return;
      }
      if (url.pathname === `${CONTROL_PREFIX}state` && request.method === "GET") {
        json(response, 200, { deployment: active, generation, requests });
        return;
      }
      if (url.pathname === `${CONTROL_PREFIX}deployment` && request.method === "POST") {
        try {
          if (request.headers["content-type"] !== "application/json") {
            throw new Error("Lifecycle controls require application/json.");
          }
          const input = await body(request);
          if (!input || typeof input !== "object" || Array.isArray(input) ||
              Object.keys(input).length !== 1 || typeof input.deployment !== "string" ||
              !configured.has(input.deployment)) throw new Error("Unknown lifecycle deployment.");
          const expected = OFFLINE_LIFECYCLE_DEPLOYMENTS[input.deployment];
          const current = configured.get(input.deployment);
          configured.set(input.deployment, runtimeDeployment(validateDeployment(current.root, expected)));
          active = input.deployment;
          generation += 1;
          json(response, 200, { deployment: active, generation });
        } catch (error) {
          json(response, 400, { error: error instanceof Error ? error.message : "Invalid control request." });
        }
        return;
      }
      json(response, 404, { error: "Unknown lifecycle control route." });
      return;
    }

    const selectedLabel = active;
    const selectedGeneration = generation;
    const deployment = configured.get(selectedLabel);
    let relativePath;
    try {
      if (!request.method || !["GET", "HEAD"].includes(request.method)) {
        response.writeHead(405, { Allow: "GET, HEAD", "Cache-Control": "no-store" }).end();
        record({ deployment: selectedLabel, generation: selectedGeneration, method: request.method ?? "", path: url.pathname, status: 405 });
        return;
      }
      relativePath = canonicalPath(url.pathname);
      const file = regularFile(deployment.root, relativePath);
      const headers = staticHeaders(relativePath, deployment, file.size);
      let range;
      try { range = parsedRange(request.headers.range, file.size); } catch {
        response.writeHead(416, { ...headers, "Content-Range": `bytes */${file.size}` }).end();
        record({ deployment: selectedLabel, generation: selectedGeneration, method: request.method, path: url.pathname, status: 416 });
        return;
      }
      if (range && !("Accept-Ranges" in headers)) {
        response.writeHead(416, { ...headers, "Content-Range": `bytes */${file.size}` }).end();
        record({ deployment: selectedLabel, generation: selectedGeneration, method: request.method, path: url.pathname, status: 416 });
        return;
      }
      const start = range?.start ?? 0;
      const end = range?.end ?? file.size - 1;
      const status = range ? 206 : 200;
      response.writeHead(status, {
        ...headers,
        "Content-Length": String(end - start + 1),
        ...(range ? { "Content-Range": `bytes ${start}-${end}/${file.size}` } : {}),
        "X-Content-Type-Options": "nosniff",
      });
      record({ deployment: selectedLabel, generation: selectedGeneration, method: request.method, path: url.pathname, status });
      if (request.method === "HEAD") response.end();
      else createReadStream(file.target, { start, end }).pipe(response);
    } catch {
      response.writeHead(404, { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" }).end();
      record({ deployment: selectedLabel, generation: selectedGeneration, method: request.method ?? "", path: url.pathname, status: 404 });
    }
  });
  return Object.freeze({
    server,
    state: () => Object.freeze({ deployment: active, generation, requests: Object.freeze([...requests]) }),
  });
}
