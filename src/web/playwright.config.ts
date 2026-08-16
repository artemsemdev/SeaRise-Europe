import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: "npm run serve",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run serve:local-release -- --root dist/releases/searise-europe-v1.0.0-20260810-c096aeab4e09 --release-id searise-europe-v1.0.0-20260810-c096aeab4e09 --app-origin http://127.0.0.1:4173 --port 8091",
      url: "http://127.0.0.1:8091/releases/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
