import { cpSync, createReadStream, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { applicationBuildIdentityPlugin } from "./scripts/application-build-identity.mjs";
import { buildIdentityFile, resolveBuildIdentity } from "./scripts/build-identity.mjs";
import { releaseDeliveryPolicy } from "./scripts/release-delivery-policy.mjs";

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
const viteFilesystemRoots = Object.freeze([
  import.meta.dirname,
  resolve(repositoryRoot, "node_modules"),
  fixturePayloadRoot,
  fixtureOverlayRoot,
]);

function forbiddenViteFilesystemRequest(requestUrl: string | undefined): boolean {
  let pathname: string;
  try {
    pathname = (requestUrl ?? "/").split(/[?#]/, 1)[0].replaceAll("\\", "/");
    for (let depth = 0; depth < 4; depth += 1) {
      const decoded = decodeURIComponent(pathname).replaceAll("\\", "/");
      if (decoded === pathname) break;
      pathname = decoded;
    }
  } catch {
    return true;
  }
  if (!pathname.startsWith("/@fs/")) return false;
  const target = resolve("/", pathname.slice("/@fs".length));
  return !viteFilesystemRoots.some(
    (root) => target === root || target.startsWith(`${root}${sep}`),
  );
}
export default defineConfig(({ mode }) => {
  const buildIdentity = resolveBuildIdentity({ mode, repositoryRoot });
  const releaseId = buildIdentity.dataReleaseId;
  const releaseDisposition = buildIdentity.releaseDisposition;

  return {
    plugins: [
      applicationBuildIdentityPlugin(buildIdentity),
      {
        name: "canonical-build-identity",
        generateBundle() {
          this.emitFile({
            type: "asset",
            fileName: buildIdentityFile,
            source: `${JSON.stringify(buildIdentity)}\n`,
          });
        },
      },
      {
        name: "strict-vite-filesystem-boundary",
        configureServer(server) {
          server.middlewares.use((request, response, next) => {
            if (!forbiddenViteFilesystemRequest(request.url)) {
              next();
              return;
            }
            response.writeHead(403, {
              "Cache-Control": "no-store",
              "Content-Type": "text/plain; charset=utf-8",
              "X-Content-Type-Options": "nosniff",
            }).end("Forbidden filesystem route");
          });
        },
      },
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
            artifacts: Array<{
              artifactId: string; role: string; path: string; mediaType: string;
              byteSize: number; sha256: string;
            }>;
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
            const artifact = artifactByPath.get(relativePath);
            let delivery: ReturnType<typeof releaseDeliveryPolicy>;
            try {
              delivery = releaseDeliveryPolicy(relativePath, artifact, size);
            } catch {
              response.writeHead(500, { "Cache-Control": "no-store" }).end();
              return;
            }
            const rangeHeader = request.headers.range;
            const range = rangeHeader ? /^bytes=(\d+)-(\d*)$/.exec(rangeHeader) : null;
            if (rangeHeader && !range) {
              response.writeHead(416, {
                "Cache-Control": delivery.cacheControl,
                "Content-Range": `bytes */${size}`,
                "Content-Type": delivery.contentType,
                ...(delivery.etag ? { ETag: delivery.etag } : {}),
              }).end();
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
              response.writeHead(416, {
                "Cache-Control": delivery.cacheControl,
                "Content-Range": `bytes */${size}`,
                "Content-Type": delivery.contentType,
                ...(delivery.etag ? { ETag: delivery.etag } : {}),
              }).end();
              return;
            }
            const headers = {
              "Accept-Ranges": "bytes",
              "Access-Control-Allow-Origin": "http://127.0.0.1:4173",
              "Access-Control-Allow-Methods": "GET, HEAD",
              "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
              "Cache-Control": delivery.cacheControl,
              "Content-Length": String(end - start + 1),
              "Content-Type": delivery.contentType,
              ...(delivery.etag ? { ETag: delivery.etag } : {}),
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
      __SEARISE_PRECACHE_JSON__: JSON.stringify("__SEARISE_PRECACHE_PENDING_V2__"),
    },
    server: {
      fs: {
        strict: true,
        allow: [...viteFilesystemRoots],
        deny: ["**/local-data/**"],
      },
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
          serviceWorker: resolve(import.meta.dirname, "src/offline/service-worker.ts"),
        },
        output: {
          entryFileNames: (chunk) =>
            chunk.name === "serviceWorker" ? "service-worker.js" : "assets/[name]-[hash].js",
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
