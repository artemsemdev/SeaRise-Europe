import { cpSync, mkdirSync, rmSync } from "node:fs";
import { resolve, sep } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { atlasEditionPlugin } from "./scripts/atlas-edition.mjs";
import { applicationBuildIdentityPlugin } from "./scripts/application-build-identity.mjs";
import { buildIdentityFile, resolveBuildIdentity } from "./scripts/build-identity.mjs";
import { createReleaseDeliveryMiddleware } from "./scripts/release-delivery-middleware.mjs";
import { inlineInitialStyles } from "./scripts/static-delivery-assets.mjs";
import { resolveStaticBuildRoot } from "./scripts/static-build-root.mjs";

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
  resolve(repositoryRoot, "data/cartography"),
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
  const buildRoot = resolveStaticBuildRoot({ webRoot: import.meta.dirname });

  return {
    plugins: [
      atlasEditionPlugin({ mode, repositoryRoot, buildRoot }),
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
          const destination = resolve(buildRoot, "releases", releaseId);
          rmSync(destination, { force: true, recursive: true });
          mkdirSync(destination, { recursive: true });
          cpSync(fixturePayloadRoot, destination, { recursive: true });
          cpSync(fixtureOverlayRoot, destination, { recursive: true });
        },
      },
      {
        name: "static-delivery-assets",
        closeBundle() {
          inlineInitialStyles(buildRoot);
        },
      },
      {
        name: "strict-preview-release-delivery",
        configurePreviewServer(server) {
          server.middlewares.use(createReleaseDeliveryMiddleware({
            releaseRoot: resolve(buildRoot, "releases", releaseId),
            releaseId,
            origin: "http://127.0.0.1:4173",
          }));
        },
      },
    ],
    define: {
      __SEARISE_PRECACHE_JSON__: JSON.stringify("__SEARISE_PRECACHE_PENDING_V3__"),
    },
    server: {
      fs: {
        strict: true,
        allow: [...viteFilesystemRoots],
        deny: ["**/local-data/**"],
      },
    },
    build: {
      emptyOutDir: true,
      outDir: buildRoot,
      target: "es2022",
      sourcemap: true,
      manifest: "vite-manifest.json",
      rollupOptions: {
        preserveEntrySignatures: "strict",
        input: {
          index: resolve(import.meta.dirname, "index.html"),
          projections: resolve(import.meta.dirname, "projections/index.html"),
          atlasApplication: resolve(import.meta.dirname, "src/atlas/main.tsx"),
          projectionApplication: resolve(import.meta.dirname, "src/main.tsx"),
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
        // identity override, Vite's preview mode decodes .br responses before hashing.
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
