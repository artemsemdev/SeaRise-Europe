import { createReadStream, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  args.set(process.argv[index], process.argv[index + 1]);
}
const rootArgument = args.get("--root");
const expectedReleaseId = args.get("--release-id");
const appOrigin = args.get("--app-origin");
const port = Number(args.get("--port") ?? "8091");
if (!rootArgument || !expectedReleaseId || !appOrigin) {
  throw new Error("Usage: --root PATH --release-id ID --app-origin ORIGIN [--port 8091]");
}
if (!/^searise-europe-v\d+\.\d+\.\d+-\d{8}-[a-f0-9]{12}$/.test(expectedReleaseId)) {
  throw new Error("Invalid release ID");
}
const allowedOrigin = new URL(appOrigin).origin;
const releaseRoot = resolve(rootArgument);
const manifest = JSON.parse(readFileSync(resolve(releaseRoot, "manifest.json"), "utf8"));
if (manifest.dataReleaseId !== expectedReleaseId) throw new Error("Local manifest release ID mismatch");

const mediaTypes = {
  ".json": "application/json",
  ".jsonl": "application/x-ndjson",
  ".parquet": "application/vnd.apache.parquet",
  ".pmtiles": "application/vnd.pmtiles",
  ".tif": "image/tiff; application=geotiff; profile=cloud-optimized",
  ".txt": "text/plain",
};

createServer((request, response) => {
  const prefix = `/releases/${expectedReleaseId}/`;
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (!url.pathname.startsWith(prefix) || !["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(404).end();
    return;
  }
  const relativePath = decodeURIComponent(url.pathname.slice(prefix.length));
  const path = resolve(releaseRoot, relativePath);
  if (!path.startsWith(`${releaseRoot}${sep}`) || path === releaseRoot) {
    response.writeHead(400).end();
    return;
  }
  let size;
  try {
    size = statSync(path).size;
  } catch {
    response.writeHead(404).end();
    return;
  }
  const headers = {
    "Accept-Ranges": "bytes",
    "Access-Control-Allow-Origin": allowedOrigin,
    "Content-Type": mediaTypes[extname(path)] ?? "application/octet-stream",
    "Vary": "Origin",
  };
  const match = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range ?? "");
  const start = match ? Number(match[1]) : 0;
  const end = match?.[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  if (start > end || start >= size) {
    response.writeHead(416, { ...headers, "Content-Range": `bytes */${size}` }).end();
    return;
  }
  const status = match ? 206 : 200;
  response.writeHead(status, {
    ...headers,
    "Content-Length": String(end - start + 1),
    ...(match ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
  });
  if (request.method === "HEAD") response.end();
  else createReadStream(path, { start, end }).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Serving explicit read-only release ${expectedReleaseId} on http://127.0.0.1:${port}`);
});
