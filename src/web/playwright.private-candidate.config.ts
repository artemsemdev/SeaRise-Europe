import { defineConfig, devices } from "@playwright/test";

if (!process.env.SEARISE_LOCAL_CANDIDATE_ROOT || !process.env.SEARISE_LOCAL_SOURCE_GRID) {
  throw new Error(
    "Private Candidate testing requires explicit SEARISE_LOCAL_CANDIDATE_ROOT and SEARISE_LOCAL_SOURCE_GRID paths.",
  );
}

const port = process.env.SEARISE_LOCAL_PORT ?? "4174";
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/private",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: origin,
    trace: "retain-on-failure",
  },
  projects: [{ name: "candidate-chromium", use: { ...devices["Desktop Chrome"] } }],
});
