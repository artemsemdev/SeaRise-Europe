import { cpSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
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
        input: {
          index: resolve(import.meta.dirname, "index.html"),
          architecture: resolve(import.meta.dirname, "about/architecture/index.html"),
        },
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
