import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testIgnore: [/tests\/private\//, /offline-lifecycle\.spec\.ts/],
  fullyParallel: true,
  // Keep timing-gate samples isolated from high-core host contention.
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  preserveOutput: "always",
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
    {
      name: "reduced-motion-chromium",
      testMatch: /projection-ux\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        contextOptions: { reducedMotion: "reduce" },
      },
    },
  ],
  webServer: [
    {
      command: "npm run serve",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run serve:committed-release",
      url: "http://127.0.0.1:8091/releases/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
