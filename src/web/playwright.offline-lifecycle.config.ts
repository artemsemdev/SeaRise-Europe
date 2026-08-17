import { defineConfig, devices } from "@playwright/test";

const controlToken = "phase2-lifecycle-test-control-token-0001";

export default defineConfig({
  testDir: "./tests",
  testMatch: /offline-lifecycle\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? "github" : "list",
  outputDir: "test-results/offline-lifecycle",
  use: {
    baseURL: "http://127.0.0.1:8093",
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: `SEARISE_LIFECYCLE_CONTROL_TOKEN=${controlToken} npm run serve:offline-lifecycle`,
    url: "http://127.0.0.1:8093/__lifecycle/healthz",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
