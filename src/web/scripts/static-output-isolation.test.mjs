import { Buffer } from "node:buffer";
import { mkdtempSync, mkdirSync, readFileSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
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

function addArchitectureEvidence(fixtureValue, mutation = {}) {
  const { dist, options, paths } = fixtureValue;
  const path = `releases/${RELEASE}/evidence/architecture.json`;
  const absolute = resolve(dist, path);
  mkdirSync(resolve(absolute, ".."), { recursive: true });
  writeFileSync(absolute, JSON.stringify({
    runtime: {
      applicationApiCalls: 0,
      prohibitedRoutes: ["/assess", "/geocode", "/config"],
    },
    ...mutation,
  }));
  options.releaseManifest.artifacts.push({
    artifactId: "architecture-evidence",
    path: "evidence/architecture.json",
    role: "architecture-evidence",
  });
  paths.push(absolute);
}

describe("static output isolation", () => {
  it("accepts only the exact root, Vite, source-map, and release-manifest closure", () => {
    const { dist, options, paths } = fixture();
    writeFileSync(resolve(dist, "assets/main-01234567.js"),
      `export const scenarios = ["/releases/${RELEASE}/config/scenarios.json", "https://fixture.searise.invalid/releases/${RELEASE}/config/scenarios.json"];\n//# sourceMappingURL=main-01234567.js.map\n`);
    expect(validateStaticOutputIsolation({ ...options, paths }).allowedPaths).toContain("assets/main-01234567.js.map");
  });

  it("rejects a symlink even when it appears at an otherwise safe output path", () => {
    const { dist, options, paths } = fixture();
    const linked = resolve(dist, "linked.html");
    symlinkSync(resolve(dist, "index.html"), linked);
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, linked] }))
      .toThrow(/not a regular file: linked\.html/);
  });

  it("rejects a missing release-manifest-authorized file", () => {
    const { dist, options, paths } = fixture();
    const missing = resolve(dist, `releases/${RELEASE}/config/scenarios.json`);
    unlinkSync(missing);
    expect(() => validateStaticOutputIsolation({ ...options, paths: paths.filter((path) => path !== missing) }))
      .toThrow(/missing allowlisted files: releases\/.+\/config\/scenarios\.json/);
  });

  it.each(["candidate-v7.tar", "unexpected-release.zip", "local-data/private.bin"])(
    "rejects forbidden actual output path %s before reading bytes",
    (name) => {
      const { dist, options, paths } = fixture();
      const injected = resolve(dist, name);
      mkdirSync(resolve(injected, ".."), { recursive: true });
      writeFileSync(injected, "synthetic mutation only");
      expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, injected] }))
        .toThrow(/names a private Candidate, archive, or canonical design-reference output/);
    },
  );

  it("rejects an ordinary unlisted output", () => {
    const { dist, options, paths } = fixture();
    const injected = resolve(dist, "unknown-output.bin");
    writeFileSync(injected, "synthetic mutation only");
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, injected] }))
      .toThrow("Static output contains unlisted files: unknown-output.bin");
  });

  it("rejects the canonical Flight mock from built output", () => {
    const { dist, options, paths } = fixture();
    const injected = resolve(dist, "docs/product/Mock/SeaRise-Flight.html");
    mkdirSync(resolve(injected, ".."), { recursive: true });
    writeFileSync(injected, "synthetic design-reference mutation only");
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, injected] }))
      .toThrow(/canonical design-reference output/);
  });

  it("rejects exact canonical Flight bytes under a renamed authorized path", () => {
    const { dist, options, paths } = fixture();
    const renamed = resolve(dist, `releases/${RELEASE}/design.bin`);
    writeFileSync(renamed, readFileSync(resolve(process.cwd(), "../../docs/product/Mock/SeaRise-Flight.html")));
    options.releaseManifest.artifacts.push({ path: "design.bin" });
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, renamed] }))
      .toThrow(/Canonical Flight mock bytes are forbidden/);
  });

  it.each([
    ["Vite", () => ({ file: "candidate-v7.js" })],
    ["shell", null],
  ])("rejects a forbidden %s authorization channel", (_channel, viteEntry) => {
    const { options, paths } = fixture();
    if (viteEntry) options.viteManifest["mutation.ts"] = viteEntry();
    else options.shellManifestPaths.push("/local-data/private.js");
    expect(() => validateStaticOutputIsolation({ ...options, paths }))
      .toThrow(/names a private Candidate, archive, or canonical design-reference output/);
  });

  it.each(["buildIdentityFile", "applicationBuildIdentityFile"])(
    "rejects a forbidden %s authorization channel",
    (field) => {
      const { options, paths } = fixture();
      options[field] = "candidate-v7.json";
      expect(() => validateStaticOutputIsolation({ ...options, paths }))
        .toThrow(/names a private Candidate, archive, or canonical design-reference output/);
    },
  );

  it.each([
    "candidate-v7.tar",
    "analysis/Candidate_v7.bin",
    "local-data/phase-1/private.bin",
    "archives/release.tar.gz",
    "archives/release.tgz",
    "archives/release.zip",
  ])("rejects manifest-authorized private Candidate or archive output %s", (name) => {
    const { dist, options, paths } = fixture();
    const injected = resolve(dist, `releases/${RELEASE}/${name}`);
    mkdirSync(resolve(injected, ".."), { recursive: true });
    writeFileSync(injected, "PRIVATE SENTINEL");
    options.releaseManifest.artifacts.push({ path: name });
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, injected] }))
      .toThrow(/names a private Candidate, archive, or canonical design-reference output/);
  });

  it.each([
    "/assess",
    "/geocode",
    "/config",
    "/v1/assess",
    "/v1/geocode",
    "/v1/config",
    "https://runtime.invalid/config",
    "https://runtime.invalid/v1/assess?lat=1",
  ])("rejects an allowlisted built asset requesting %s", (endpoint) => {
    const { dist, options, paths } = fixture();
    writeFileSync(resolve(dist, "assets/main-01234567.js"), `fetch(${JSON.stringify(endpoint)});\n//# sourceMappingURL=main-01234567.js.map\n`);
    expect(() => validateStaticOutputIsolation({ ...options, paths })).toThrow(/Forbidden runtime reference/);
  });

  it.each([
    `/releases/${RELEASE}/config/UNLISTED.json`,
    "/releases/searise-europe-v9.9.9-20990101-ffffffffffff/config/scenarios.json",
    `https://fixture.searise.invalid/releases/${RELEASE}/config/UNLISTED.json`,
  ])("rejects unbound release config reference %s", (reference) => {
    const { dist, options, paths } = fixture();
    writeFileSync(resolve(dist, "assets/main-01234567.js"),
      `export const unbound = ${JSON.stringify(reference)};\n//# sourceMappingURL=main-01234567.js.map\n`);
    expect(() => validateStaticOutputIsolation({ ...options, paths })).toThrow(/Forbidden runtime reference/);
  });

  it("scans manifest-authorized JSON for dynamic endpoints", () => {
    const { dist, options, paths } = fixture();
    writeFileSync(resolve(dist, `releases/${RELEASE}/config/scenarios.json`), '{"endpoint":"/v1/assess"}');
    expect(() => validateStaticOutputIsolation({ ...options, paths })).toThrow(/Forbidden runtime reference/);
  });

  it("accepts only the exact architecture-evidence zero-call prohibition", () => {
    const value = fixture();
    addArchitectureEvidence(value);
    expect(validateStaticOutputIsolation({ ...value.options, paths: value.paths }).allowedPaths)
      .toContain(`releases/${RELEASE}/evidence/architecture.json`);
  });

  it("rejects endpoint mutations outside the exact architecture prohibition field", () => {
    const value = fixture();
    addArchitectureEvidence(value, { mutationEndpoint: "/v1/assess" });
    expect(() => validateStaticOutputIsolation({ ...value.options, paths: value.paths }))
      .toThrow(/Forbidden runtime reference/);
  });

  it("extracts dynamic endpoints from manifest-authorized binary bytes", () => {
    const { dist, options, paths } = fixture();
    const binary = resolve(dist, `releases/${RELEASE}/data.bin`);
    writeFileSync(binary, Buffer.from([0, ...Buffer.from("/v1/geocode"), 0]));
    options.releaseManifest.artifacts.push({ path: "data.bin" });
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, binary] }))
      .toThrow(/Forbidden runtime reference/);
  });

  it("extracts UTF-16 dynamic endpoints from manifest-authorized binary bytes", () => {
    const { dist, options, paths } = fixture();
    const binary = resolve(dist, `releases/${RELEASE}/utf16.bin`);
    writeFileSync(binary, Buffer.from(`\0${[..."/v1/config"].join("\0")}\0`, "binary"));
    options.releaseManifest.artifacts.push({ path: "utf16.bin" });
    expect(() => validateStaticOutputIsolation({ ...options, paths: [...paths, binary] }))
      .toThrow(/Forbidden runtime reference/);
  });
});
