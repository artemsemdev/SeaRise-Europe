import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

const baseURL = process.env.SEARISE_ATLAS_URL ?? "http://127.0.0.1:4181";

export default defineConfig({
  testDir: "./tests/real-local",
  testMatch: /local-inundation-(?:atlas|experience|zoom|source)\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  outputDir: resolve(import.meta.dirname, "../../.cache/atlas-qa/playwright"),
  use: {
    baseURL,
    contextOptions: { reducedMotion: "reduce" },
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "atlas-desktop",
      use: { browserName: "chromium", viewport: { width: 1440, height: 1024 } },
    },
    {
      name: "atlas-mobile",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: "atlas-boundaries",
      use: { browserName: "chromium", viewport: { width: 768, height: 1024 } },
    },
  ],
});
