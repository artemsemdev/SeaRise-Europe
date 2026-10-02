import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { brotliCompressSync } from "node:zlib";
import { preview } from "vite";
import { createRealLocalAtlasMiddleware } from "../../src/web/scripts/real-local-atlas.mjs";
import { sealedPreviewConfig } from "./sealed-preview.mjs";

test("sealed preview serves cache-eligible static bytes and strict releases while private Atlas stays no-store", async () => {
  const root = mkdtempSync(join(tmpdir(), "searise-sealed-http-"));
  const app = join(root, "app");
  const releaseId = "synthetic-http-fixture";
  const releaseRoot = join(app, "releases", releaseId);
  const privateRoot = join(root, "private-atlas");
  const artifacts = [];
  const put = (path, bytes) => {
    mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, bytes);
  };
  const artifact = (path, artifactId, role, mediaType, bytes) => {
    put(join(releaseRoot, path), bytes);
    const record = { path, artifactId, role, mediaType, byteSize: bytes.length,
      sha256: createHash("sha256").update(bytes).digest("hex") };
    artifacts.push(record); return record;
  };
  const compressed = brotliCompressSync(Buffer.from('{"synthetic":true}'));
  const search = artifact("search/europe-core.codepoint-trie.json.br", "settlements-europe-core", "settlement-search-index", "application/vnd.searise.search-index+json", compressed);
  const cog = artifact("analysis/test.tif", "test-cog", "projection-analysis-cog", "image/tiff", Buffer.from("synthetic-cog-bytes"));
  const visual = artifact("layers/ssp2-45/2050.pmtiles", "projection-ssp2-45-2050-pmtiles", "projection-visual-pmtiles", "application/vnd.pmtiles", Buffer.from("synthetic-pmtiles"));
  put(join(releaseRoot, "manifest.json"), JSON.stringify({ artifacts }));
  put(join(releaseRoot, "unlisted.json"), "must not serve");
  put(join(app, "build-identity.json"), JSON.stringify({ dataReleaseId: releaseId }));
  put(join(app, "projections/index.html"), "<html>synthetic reference</html>");
  put(join(app, "service-worker.js"), "// synthetic worker");
  put(join(privateRoot, "basemap/fonts/Test/0-255.pbf"), Buffer.from([1, 2, 3, 4]));
  const native = createServer((request, response) => {
    response.writeHead(200, { "Cache-Control": "no-store", "Content-Type": request.url.startsWith("/tiles/") ? "image/png" : "application/json" }).end("synthetic raster response");
  });
  let active;
  try {
    native.listen(0, "127.0.0.1"); await once(native, "listening");
    const middleware = createRealLocalAtlasMiddleware({ atlasRoot: privateRoot,
      catalog: { edition: "real-local" }, context: { entries: [], totalPlaces: 0, byId: new Map() },
      rasterPort: native.address().port });
    active = await preview(sealedPreviewConfig({ webRoot: root, app, port: 0, middleware, close: () => {} }));
    const origin = `http://127.0.0.1:${active.httpServer.address().port}`;
    const get = (path, options) => globalThis.fetch(`${origin}${path}`, options);
    for (const path of ["/projections/", "/service-worker.js", "/build-identity.json"]) {
      const response = await get(path);
      assert.equal(response.status, 200); assert.equal(response.headers.get("cache-control"), "no-cache");
      await response.arrayBuffer();
    }
    for (const path of ["/atlas-data/manifest.json", "/atlas-data/europe/search?q=test", "/atlas-data/inspect?year=2050", "/atlas-data/tiles/2050/protected/12/2188/1456.png", "/atlas-data/basemap/fonts/Test/0-255.pbf"]) {
      const response = await get(path);
      assert.equal(response.status, 200, path); assert.equal(response.headers.get("cache-control"), "no-store", path);
      await response.arrayBuffer();
    }
    for (const [path, options, status] of [["/atlas-data/missing", {}, 404], ["/atlas-data/manifest.json", { method: "POST" }, 405], ["/atlas-data/basemap/fonts/Test/0-255.pbf", { headers: { Range: "bytes=99-" } }, 416]]) {
      const response = await get(path, options);
      assert.equal(response.status, status); assert.equal(response.headers.get("cache-control"), "no-store");
      await response.arrayBuffer();
    }
    const prefix = `/releases/${releaseId}/`;
    const opaque = await get(`${prefix}${search.path}`, { headers: { "Accept-Encoding": "br" } });
    assert.equal(opaque.headers.get("content-encoding"), "identity");
    assert.equal(opaque.headers.get("etag"), `"sha256-${search.sha256}"`);
    assert.equal(opaque.headers.get("content-type"), search.mediaType);
    assert.deepEqual(Buffer.from(await opaque.arrayBuffer()), compressed);
    for (const record of [cog, visual]) {
      const response = await get(`${prefix}${record.path}`, { headers: { Range: "bytes=2-6" } });
      assert.equal(response.status, 206); assert.equal(response.headers.get("content-range"), `bytes 2-6/${record.byteSize}`);
      assert.equal(response.headers.get("etag"), `"sha256-${record.sha256}"`);
      assert.equal(response.headers.get("cache-control"), record === visual ? "no-store" : "public, max-age=31536000, immutable");
      assert.equal((await response.arrayBuffer()).byteLength, 5);
      const head = await get(`${prefix}${record.path}`, { method: "HEAD" });
      assert.equal(head.status, 200); assert.equal(head.headers.get("content-length"), String(record.byteSize));
      assert.equal((await head.arrayBuffer()).byteLength, 0);
      for (const range of ["bytes=-2", "bytes=1-2,4-5", "bytes=999-", "bytes=7-3", "bytes=9007199254740992-"]) {
        const rejected = await get(`${prefix}${record.path}`, { headers: { Range: range } });
        assert.equal(rejected.status, 416); assert.equal(rejected.headers.get("content-range"), `bytes */${record.byteSize}`);
        assert.equal(rejected.headers.get("etag"), `"sha256-${record.sha256}"`);
        await rejected.arrayBuffer();
      }
    }
    assert.equal((await get(`${prefix}manifest.json`)).status, 200);
    assert.equal((await get(`${prefix}unlisted.json`)).status, 404);
    assert.equal((await get(`${prefix}${cog.path}`, { method: "POST" })).status, 405);
    assert.equal((await get(`${prefix}%zz`)).status, 400);
    writeFileSync(join(releaseRoot, cog.path), "short");
    assert.equal((await get(`${prefix}${cog.path}`)).status, 500);
    rmSync(join(releaseRoot, cog.path));
    symlinkSync(join(privateRoot, "basemap/fonts/Test/0-255.pbf"), join(releaseRoot, cog.path));
    assert.equal((await get(`${prefix}${cog.path}`)).status, 400);
  } finally {
    await active?.close();
    native.closeAllConnections(); await new Promise((resolve) => native.close(resolve));
    rmSync(root, { recursive: true, force: true });
  }
});
