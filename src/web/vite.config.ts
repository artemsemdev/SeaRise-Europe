import { cpSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const repositoryRoot = resolve(import.meta.dirname, "../..");
const fixtureRoot = resolve(
  repositoryRoot,
  "contracts/release/v1/fixtures/release",
  releaseId,
);

export default defineConfig({
  plugins: [
    react(),
    {
      name: "committed-release-fixture",
      closeBundle() {
        const destination = resolve(import.meta.dirname, "dist/releases", releaseId);
        rmSync(destination, { force: true, recursive: true });
        mkdirSync(destination, { recursive: true });
        cpSync(fixtureRoot, destination, { recursive: true });
      },
    },
  ],
  define: {
    __APP_BUILD_ID__: JSON.stringify(process.env.SEARISE_APP_BUILD_ID ?? "local-fixture"),
    __DATA_RELEASE_ID__: JSON.stringify(releaseId),
    __RELEASE_DISPOSITION__: JSON.stringify("synthetic-fixture"),
  },
  build: {
    target: "es2022",
    sourcemap: true,
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
});
