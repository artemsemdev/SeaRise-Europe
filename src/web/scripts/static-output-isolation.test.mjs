import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { validateStaticOutputIsolation } from "./static-output-isolation.mjs";

const RELEASE = "searise-europe-v1.0.0-20260810-c096aeab4e09";

function fixture() {
  const dist = mkdtempSync(resolve(tmpdir(), "static-output-isolation-"));
  const files = {
    "index.html": "<main>Flight</main>",
    "about/architecture/index.html": "<main>Architecture</main>",
    "vite-manifest.json": "{}",
    "service-worker.js": "self.addEventListener('fetch', () => {});",
    "build-identity.json": "{}",
    "assets/application-build-identity.js": "export default {};",
    "assets/main-01234567.js": "export const flight = true;\n//# sourceMappingURL=main-01234567.js.map\n",
    "assets/main-01234567.js.map": "{}",
    [`releases/${RELEASE}/manifest.json`]: "{}",
    [`releases/${RELEASE}/config/scenarios.json`]: "{}",
  };
  for (const [path, value] of Object.entries(files)) {
    mkdirSync(resolve(dist, path, ".."), { recursive: true });
    writeFileSync(resolve(dist, path), value);
  }
  const viteManifest = {
    "src/main.tsx": { file: "assets/main-01234567.js", isEntry: true },
    "virtual:application-build-identity": { file: "assets/application-build-identity.js" },
    "src/offline/service-worker.ts": { file: "service-worker.js", isEntry: true },
  };
  const releaseManifest = { dataReleaseId: RELEASE, artifacts: [{ path: "config/scenarios.json" }] };
  const options = {
    dist,
    viteManifest,
    releaseManifest,
    releaseId: RELEASE,
    buildIdentityFile: "build-identity.json",
    applicationBuildIdentityFile: "assets/application-build-identity.js",
    shellManifestPaths: ["/", "/assets/application-build-identity.js", "/assets/main-01234567.js"],
  };
  return { dist, options, paths: Object.keys(files).map((path) => resolve(dist, path)) };
}

describe("static output isolation", () => {
  it("accepts only the exact root, Vite, source-map, and release-manifest closure", () => {
    const { options, paths } = fixture();
    expect(validateStaticOutputIsolation({ ...options, paths }).allowedPaths).toContain("assets/main-01234567.js.map");
  });

  it.each(["candidate-v7.tar", "unexpected-release.zip", "unknown-output.bin"])(
    "rejects unlisted output %s without reading any private Candidate",
    (name) => {
      const { dist, options, paths } = fixture();
      const injected = resolve(dist, name);
      writeFileSync(injected, "synthetic mutation only");
      expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, injected] }))
        .toThrow(`Static output contains unlisted files: ${name}`);
    },
  );

  it.each(["/assess", "/geocode", "/config"])("rejects an allowlisted built asset requesting %s", (endpoint) => {
    const { dist, options, paths } = fixture();
    writeFileSync(resolve(dist, "assets/main-01234567.js"), `fetch(${JSON.stringify(endpoint)});\n//# sourceMappingURL=main-01234567.js.map\n`);
    expect(() => validateStaticOutputIsolation({ ...options, paths })).toThrow(/Forbidden runtime reference/);
  });
});
