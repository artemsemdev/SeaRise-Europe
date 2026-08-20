import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: /range-cache-compatibility\.spec\.ts/,
  fullyParallel: true,
  workers: 3,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8092",
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "node scripts/serve-range-cache-spike.mjs",
    url: "http://127.0.0.1:8092/healthz",
    reuseExistingServer: false,
  },
});
