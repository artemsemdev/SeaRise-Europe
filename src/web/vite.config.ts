import { cpSync, createReadStream, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { extname, resolve, sep } from "node:path";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

const fixtureReleaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const repositoryRoot = resolve(import.meta.dirname, "../..");
const fixturePayloadRoot = resolve(
  repositoryRoot,
  "contracts/release/v1/fixtures/release",
  fixtureReleaseId,
);
const fixtureOverlayRoot = resolve(
  repositoryRoot,
  "contracts/release/v2/fixtures/browser-release",
  fixtureReleaseId,
);
const releaseMediaTypes: Readonly<Record<string, string>> = Object.freeze({
  ".json": "application/json",
  ".jsonl": "application/x-ndjson",
  ".gz": "application/gzip",
  ".parquet": "application/vnd.apache.parquet",
  ".pmtiles": "application/vnd.pmtiles",
  ".tif": "image/tiff; application=geotiff; profile=cloud-optimized",
  ".txt": "text/plain",
});

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, repositoryRoot, "SEARISE_");
  const releaseId =
    process.env.SEARISE_DATA_RELEASE_ID ?? env.SEARISE_DATA_RELEASE_ID ?? fixtureReleaseId;
  const releaseDisposition =
    process.env.SEARISE_RELEASE_DISPOSITION ??
    env.SEARISE_RELEASE_DISPOSITION ??
    "synthetic-fixture";
  const localManifestUrl =
    process.env.SEARISE_LOCAL_MANIFEST_URL ?? env.SEARISE_LOCAL_MANIFEST_URL;
  if (!["synthetic-fixture", "private-engineering", "public-promoted"].includes(releaseDisposition)) {
    throw new Error("Unsupported release disposition.");
  }
  if (localManifestUrl && (command !== "serve" || releaseDisposition !== "private-engineering")) {
    throw new Error("A local manifest URL is allowed only for explicit private-engineering development.");
  }
  if (localManifestUrl) {
    const localUrl = new URL(localManifestUrl);
    if (localUrl.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(localUrl.hostname)) {
      throw new Error("A private engineering manifest must be served from loopback over HTTP.");
    }
  }
  if (releaseDisposition === "private-engineering" && !localManifestUrl) {
    throw new Error("Private engineering mode requires an explicit local manifest URL.");
  }
  if (command === "build" && releaseDisposition === "private-engineering") {
    throw new Error("Private engineering releases cannot be copied into a production build.");
  }
  const manifestUrl = localManifestUrl ?? `/releases/${releaseId}/manifest.json`;

  return {
    plugins: [
      react(),
      {
        name: "committed-release-fixture",
        closeBundle() {
          if (releaseDisposition !== "synthetic-fixture" || releaseId !== fixtureReleaseId) return;
          const destination = resolve(import.meta.dirname, "dist/releases", releaseId);
          rmSync(destination, { force: true, recursive: true });
          mkdirSync(destination, { recursive: true });
          cpSync(fixturePayloadRoot, destination, { recursive: true });
          cpSync(fixtureOverlayRoot, destination, { recursive: true });
        },
      },
      {
        name: "strict-preview-release-delivery",
        configurePreviewServer(server) {
          const releaseRoot = resolve(import.meta.dirname, "dist/releases", releaseId);
          const manifest = JSON.parse(readFileSync(resolve(releaseRoot, "manifest.json"), "utf8")) as {
            artifacts: Array<{ path: string; sha256: string }>;
          };
          const artifactByPath = new Map(
            manifest.artifacts.map((artifact) => [artifact.path, artifact]),
          );
          server.middlewares.use((request, response, next) => {
            const prefix = `/releases/${releaseId}/`;
            const url = new URL(request.url ?? "/", "http://127.0.0.1");
            if (!url.pathname.startsWith(prefix)) {
              next();
              return;
            }
            if (!request.method || !["GET", "HEAD"].includes(request.method)) {
              response.writeHead(405, { Allow: "GET, HEAD" }).end();
              return;
            }
            let relativePath: string;
            try {
              relativePath = decodeURIComponent(url.pathname.slice(prefix.length));
            } catch {
              response.writeHead(400).end();
              return;
            }
            const path = resolve(releaseRoot, relativePath);
            if (!path.startsWith(`${releaseRoot}${sep}`) || path === releaseRoot) {
              response.writeHead(400).end();
              return;
            }
            let size: number;
            try {
              size = statSync(path).size;
            } catch {
              response.writeHead(404).end();
              return;
            }
            const rangeHeader = request.headers.range;
            const range = rangeHeader ? /^bytes=(\d+)-(\d*)$/.exec(rangeHeader) : null;
            if (rangeHeader && !range) {
              response.writeHead(416, { "Content-Range": `bytes */${size}` }).end();
              return;
            }
            const start = range ? Number(range[1]) : 0;
            const requestedEnd = range?.[2] ? Number(range[2]) : size - 1;
            const end = Math.min(requestedEnd, size - 1);
            if (
              !Number.isSafeInteger(start) ||
              !Number.isSafeInteger(requestedEnd) ||
              start > end ||
              start >= size
            ) {
              response.writeHead(416, { "Content-Range": `bytes */${size}` }).end();
              return;
            }
            const artifact = artifactByPath.get(relativePath);
            const headers = {
              "Accept-Ranges": "bytes",
              "Access-Control-Allow-Origin": "http://127.0.0.1:4173",
              "Access-Control-Allow-Methods": "GET, HEAD",
              "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
              "Cache-Control": "public, max-age=31536000, immutable",
              "Content-Length": String(end - start + 1),
              "Content-Type": releaseMediaTypes[extname(path)] ?? "application/octet-stream",
              ...(artifact ? { ETag: `"sha256-${artifact.sha256}"` } : {}),
              ...(range ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
              Vary: "Origin",
            };
            response.writeHead(range ? 206 : 200, headers);
            if (request.method === "HEAD") response.end();
            else createReadStream(path, { start, end }).pipe(response);
          });
        },
      },
    ],
    define: {
      __APP_BUILD_ID__: JSON.stringify(process.env.SEARISE_APP_BUILD_ID ?? "local-fixture"),
      __DATA_RELEASE_ID__: JSON.stringify(releaseId),
      __RELEASE_DISPOSITION__: JSON.stringify(releaseDisposition),
      __MANIFEST_URL__: JSON.stringify(manifestUrl),
    },
    build: {
      target: "es2022",
      sourcemap: true,
      manifest: "vite-manifest.json",
      rollupOptions: {
        preserveEntrySignatures: "strict",
        input: {
          index: resolve(import.meta.dirname, "index.html"),
          architecture: resolve(import.meta.dirname, "about/architecture/index.html"),
          scientificRuntime: resolve(import.meta.dirname, "src/scientific-runtime.ts"),
        },
      },
    },
    preview: {
      headers: {
        // Preserve precompressed release artifacts as opaque bytes. Without this
        // identity override, Vite preview decodes .br responses before hashing.
        "Content-Encoding": "identity",
        "Access-Control-Allow-Origin": "http://127.0.0.1:4173",
        "Access-Control-Allow-Methods": "GET, HEAD",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
        Vary: "Origin",
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      exclude: ["tests/**", "node_modules/**", "dist/**"],
      coverage: {
        reporter: ["text", "json-summary"],
      },
    },
  };
});
