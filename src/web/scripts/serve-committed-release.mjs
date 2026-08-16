import { createReadStream, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const releaseRoot = resolve(import.meta.dirname, `../dist/releases/${releaseId}`);
const origin = "http://127.0.0.1:4173";
const port = 8091;
const manifest = JSON.parse(readFileSync(resolve(releaseRoot, "manifest.json"), "utf8"));
const artifactByPath = new Map(manifest.artifacts.map((artifact) => [artifact.path, artifact]));
const mediaTypes = {
  ".json": "application/json",
  ".jsonl": "application/x-ndjson",
  ".gz": "application/gzip",
  ".parquet": "application/vnd.apache.parquet",
  ".pmtiles": "application/vnd.pmtiles",
  ".tif": "image/tiff; application=geotiff; profile=cloud-optimized",
  ".txt": "text/plain",
};

createServer((request, response) => {
  const prefix = `/releases/${releaseId}/`;
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (!url.pathname.startsWith(prefix) || !["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(404).end();
    return;
  }
  const relativePath = decodeURIComponent(url.pathname.slice(prefix.length));
  const artifact = artifactByPath.get(relativePath);
  if (!artifact && relativePath !== "manifest.json") {
    response.writeHead(404).end();
    return;
  }
  const path = resolve(releaseRoot, relativePath);
  if (!path.startsWith(`${releaseRoot}${sep}`)) {
    response.writeHead(400).end();
    return;
  }
  const size = statSync(path).size;
  const responseCacheControl = extname(path) === ".pmtiles"
    ? "no-store"
    : "public, max-age=31536000, immutable";
  const responseContentType = mediaTypes[extname(path)] ?? "application/octet-stream";
  const headers = {
    "Accept-Ranges": "bytes",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, HEAD",
    "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
    "Cache-Control": responseCacheControl,
    "Content-Type": responseContentType,
    ...(artifact ? { ETag: `"sha256-${artifact.sha256}"` } : {}),
    Vary: "Origin",
  };
  const rangeHeader = request.headers.range;
  const match = rangeHeader ? /^bytes=(\d+)-(\d*)$/.exec(rangeHeader) : null;
  if (rangeHeader && !match) {
    response.writeHead(416, { ...headers, "Content-Range": `bytes */${size}` }).end();
    return;
  }
  const start = match ? Number(match[1]) : 0;
  const requestedEnd = match?.[2] ? Number(match[2]) : size - 1;
  const end = Math.min(requestedEnd, size - 1);
  if (
    !Number.isSafeInteger(start) ||
    !Number.isSafeInteger(requestedEnd) ||
    start > end ||
    start >= size
  ) {
    response.writeHead(416, { ...headers, "Content-Range": `bytes */${size}` }).end();
    return;
  }
  response.writeHead(match ? 206 : 200, {
    ...headers,
    "Content-Length": String(end - start + 1),
    ...(match ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
  });
  if (request.method === "HEAD") response.end();
  else createReadStream(path, { start, end }).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Serving committed synthetic release on http://127.0.0.1:${port}`);
});
