import { Buffer } from "node:buffer";
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { resolve } from "node:path";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const repositoryRoot = resolve(import.meta.dirname, "../../..");
const releaseRoot = resolve(
  repositoryRoot,
  "contracts/release/v2/fixtures/browser-release",
  releaseId,
);
const payloadRoot = resolve(
  repositoryRoot,
  "contracts/release/v1/fixtures/release",
  releaseId,
);
const manifest = JSON.parse(readFileSync(resolve(releaseRoot, "manifest.json"), "utf8"));
const artifactIds = new Set([
  "projection-ssp2-45-2050-cog",
  "projection-ssp2-45-2050-pmtiles",
]);
const artifacts = manifest.artifacts.filter((candidate) => artifactIds.has(candidate.artifactId));
if (artifacts.length !== artifactIds.size) {
  throw new Error("Committed range-cache fixture artifacts are missing.");
}
const artifactByRequestPath = new Map(artifacts.map((artifact) => {
  const overlayPath = resolve(releaseRoot, artifact.path);
  const filePath = existsSync(overlayPath) ? overlayPath : resolve(payloadRoot, artifact.path);
  if (statSync(filePath).size !== artifact.byteSize) {
    throw new Error(`Committed range-cache fixture size differs for ${artifact.artifactId}.`);
  }
  return [`/releases/${releaseId}/${artifact.path}`, { artifact, filePath }];
}));

const host = "127.0.0.1";
const port = Number(process.env.SEARISE_RANGE_SPIKE_PORT ?? "8092");
const origin = `http://${host}:${port}`;
const page = `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>SeaRise range-cache compatibility</title></head>
  <body><main><h1>Range-cache compatibility harness</h1></main></body>
</html>\n`;

function commonHeaders(artifact) {
  return {
    "Accept-Ranges": "bytes",
    "Access-Control-Allow-Methods": "GET, HEAD",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
    "Cache-Control": "public, max-age=31536000, immutable",
    "Content-Type": artifact.mediaType,
    ETag: `"sha256-${artifact.sha256}"`,
    Vary: "Origin",
    "X-Content-Type-Options": "nosniff",
  };
}

function parseRange(header, artifactSize) {
  if (!header) return null;
  const match = /^bytes=(\d+)-(\d+)$/.exec(header);
  if (!match) return undefined;
  const start = Number(match[1]);
  const end = Number(match[2]);
  if (
    !Number.isSafeInteger(start) ||
    !Number.isSafeInteger(end) ||
    start < 0 ||
    start > end ||
    end >= artifactSize
  ) return undefined;
  return { start, end };
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", origin);
  if (url.pathname === "/healthz") {
    response.writeHead(200, {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
    }).end("ready");
    return;
  }
  if (url.pathname === "/" && request.method === "GET") {
    response.writeHead(200, {
      "Cache-Control": "no-store",
      "Content-Length": String(Buffer.byteLength(page)),
      "Content-Type": "text/html; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    }).end(page);
    return;
  }
  const probe = artifactByRequestPath.get(url.pathname);
  if (!probe || !["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(404, { "Cache-Control": "no-store" }).end();
    return;
  }

  const { artifact, filePath } = probe;
  const range = parseRange(request.headers.range, artifact.byteSize);
  if (range === undefined) {
    response.writeHead(416, {
      ...commonHeaders(artifact),
      "Content-Range": `bytes */${artifact.byteSize}`,
    }).end();
    return;
  }
  const start = range?.start ?? 0;
  const end = range?.end ?? artifact.byteSize - 1;
  response.writeHead(range ? 206 : 200, {
    ...commonHeaders(artifact),
    "Content-Length": String(end - start + 1),
    ...(range ? { "Content-Range": `bytes ${start}-${end}/${artifact.byteSize}` } : {}),
  });
  if (request.method === "HEAD") response.end();
  else createReadStream(filePath, { start, end }).pipe(response);
});

server.listen(port, host, () => {
  console.log(`Range-cache compatibility fixture ready at ${origin}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
