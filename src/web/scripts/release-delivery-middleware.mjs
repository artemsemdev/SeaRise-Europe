import { createReadStream, readFileSync, realpathSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import { releaseDeliveryPolicy } from "./release-delivery-policy.mjs";

// Serve only the manifest and its declared artifacts, never an arbitrary release file.
export function createReleaseDeliveryMiddleware({ releaseRoot, releaseId, origin }) {
  const root = realpathSync(releaseRoot);
  const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
  const artifacts = new Map(manifest.artifacts.map((artifact) => [artifact.path, artifact]));
  const prefix = `/releases/${releaseId}/`;
  return (request, response, next) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (!url.pathname.startsWith(prefix)) { next(); return; }
    response.setHeader("Cache-Control", "no-store");
    if (!["GET", "HEAD"].includes(request.method ?? "")) {
      response.writeHead(405, { Allow: "GET, HEAD" }).end(); return;
    }
    let relativePath;
    try { relativePath = decodeURIComponent(url.pathname.slice(prefix.length)); }
    catch { response.writeHead(400).end(); return; }
    const artifact = artifacts.get(relativePath);
    if (!artifact && relativePath !== "manifest.json") { response.writeHead(404).end(); return; }
    let path;
    let size;
    try {
      path = realpathSync(resolve(root, relativePath));
      const stat = statSync(path);
      if (!path.startsWith(`${root}${sep}`) || !stat.isFile()) { response.writeHead(400).end(); return; }
      size = stat.size;
    } catch { response.writeHead(404).end(); return; }
    let delivery;
    try { delivery = releaseDeliveryPolicy(relativePath, artifact, size); }
    catch { response.writeHead(500).end(); return; }
    const headers = {
      "Accept-Ranges": "bytes",
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET, HEAD",
      "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
      "Cache-Control": delivery.cacheControl,
      "Content-Encoding": "identity",
      "Content-Type": delivery.contentType,
      ...(delivery.etag ? { ETag: delivery.etag } : {}),
      Vary: "Origin",
    };
    const rangeHeader = request.headers.range;
    const range = rangeHeader ? /^bytes=(\d+)-(\d*)$/.exec(rangeHeader) : null;
    if (rangeHeader && !range) {
      response.writeHead(416, { ...headers, "Content-Range": `bytes */${size}` }).end(); return;
    }
    const start = range ? Number(range[1]) : 0;
    const requestedEnd = range?.[2] ? Number(range[2]) : size - 1;
    const end = Math.min(requestedEnd, size - 1);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(requestedEnd) || start > end || start >= size) {
      response.writeHead(416, { ...headers, "Content-Range": `bytes */${size}` }).end(); return;
    }
    response.writeHead(range ? 206 : 200, {
      ...headers, "Content-Length": String(end - start + 1),
      ...(range ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
    });
    if (request.method === "HEAD") response.end();
    else createReadStream(path, { start, end }).pipe(response);
  };
}
