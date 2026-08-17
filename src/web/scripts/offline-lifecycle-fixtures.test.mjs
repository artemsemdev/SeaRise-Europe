// @vitest-environment node

import { lstatSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { serializeApplicationBuildIdentity } from "./application-build-identity.mjs";
import {
  OFFLINE_LIFECYCLE_DEPLOYMENTS,
  OFFLINE_LIFECYCLE_RELEASE_ID,
  prepareOfflineLifecycleFixtures,
  sealOfflineLifecycleDeployment,
  validateOfflineLifecycleDeployment,
} from "./offline-lifecycle-fixtures.mjs";
import { createOwnedLifecycleRoot } from "./static-build-root.mjs";

const roots = [];
const digest = (label) => label.repeat(64).slice(0, 64);

function root() {
  const owned = createOwnedLifecycleRoot();
  roots.push(owned.root);
  return owned.root;
}

function ownership() {
  const owned = createOwnedLifecycleRoot();
  roots.push(owned.root);
  return owned;
}

function fakeDeployment(output, expected) {
  const identity = {
    schemaVersion: "1.0.0",
    appBuildId: expected.appBuildId,
    dataReleaseId: OFFLINE_LIFECYCLE_RELEASE_ID,
    releaseDisposition: "synthetic-fixture",
    manifestPath: `/releases/${OFFLINE_LIFECYCLE_RELEASE_ID}/manifest.json`,
  };
  const precacheSetSha256 = digest(expected.label.toLowerCase());
  mkdirSync(join(output, "assets"), { recursive: true });
  mkdirSync(join(output, "releases", OFFLINE_LIFECYCLE_RELEASE_ID, "config"), { recursive: true });
  writeFileSync(join(output, "index.html"), `<head><script defer src="/assets/application-build-identity.js"></script></head><body><h1>${expected.label}</h1></body>`);
  writeFileSync(join(output, "build-identity.json"), JSON.stringify(identity));
  writeFileSync(join(output, "assets/application-build-identity.js"), serializeApplicationBuildIdentity(identity));
  writeFileSync(join(output, "releases", OFFLINE_LIFECYCLE_RELEASE_ID, "manifest.json"), JSON.stringify({
    dataReleaseId: OFFLINE_LIFECYCLE_RELEASE_ID,
    artifacts: [{ path: "config/test.json" }],
  }));
  writeFileSync(join(output, "releases", OFFLINE_LIFECYCLE_RELEASE_ID, "config/test.json"), `{"deployment":"${expected.label}"}\n`);
  const workerAuthority = {
    authorityKind: "searise-shell-precache-v3",
    contractVersion: 3,
    buildIdentity: identity,
    entries: [],
    precacheSetSha256,
  };
  writeFileSync(join(output, "service-worker.js"), `const value = JSON.parse(${JSON.stringify(JSON.stringify(workerAuthority))});`);
  writeFileSync(join(output, "build-report.json"), JSON.stringify({
    ...identity,
    serviceWorker: { appBuildId: identity.appBuildId, dataReleaseId: identity.dataReleaseId, precacheSetSha256 },
  }));
}

afterEach(() => {
  for (const value of roots.splice(0)) rmSync(value, { force: true, recursive: true });
});

describe("offline lifecycle fixture preparation", () => {
  it("builds A, B, and C with isolated synthetic-only environments", () => {
    const owned = ownership();
    const commands = [];
    const prepared = prepareOfflineLifecycleFixtures({
      webRoot: "/workspace/web",
      environment: { PATH: "/bin", SEARISE_PRIVATE_CANDIDATE_PATH: "/must-not-propagate" },
      createRoot: () => owned,
      run(command) {
        commands.push(command);
        if (command.label.endsWith("Vite build")) {
          const expected = Object.values(OFFLINE_LIFECYCLE_DEPLOYMENTS)
            .find(({ appBuildId }) => appBuildId === command.environment.SEARISE_APP_BUILD_ID);
          fakeDeployment(command.environment.SEARISE_WEB_DIST_ROOT, expected);
        }
      },
    });

    expect([...prepared.deployments.keys()]).toEqual(["A", "B", "C"]);
    expect(commands).toHaveLength(12);
    expect(commands.every(({ environment }) => !("SEARISE_PRIVATE_CANDIDATE_PATH" in environment))).toBe(true);
    expect(commands.every(({ environment }) => environment.SEARISE_RELEASE_DISPOSITION === "synthetic-fixture")).toBe(true);
    prepared.cleanup();
    prepared.cleanup();
  });

  it("rejects mixed identities and symbolic links", () => {
    const output = join(root(), "A");
    fakeDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A);
    const reportPath = join(output, "build-report.json");
    const report = JSON.parse(readFileSync(reportPath, "utf8"));
    report.appBuildId = "wrong";
    writeFileSync(reportPath, JSON.stringify(report));
    expect(() => validateOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A, {})).toThrow(/mismatch/);

    fakeDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A);
    symlinkSync(join(output, "build-identity.json"), join(output, "identity-link"));
    expect(() => validateOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A, {})).toThrow(/symlink/);
  });

  it("rejects shell and release byte mutations against the complete file seal", () => {
    const output = join(root(), "A");
    fakeDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A);
    const sealed = sealOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A);
    expect(validateOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A, sealed.seal).seal)
      .toEqual(sealed.seal);

    const indexPath = join(output, "index.html");
    writeFileSync(indexPath, readFileSync(indexPath, "utf8").replace("</body>", "<p>mutated shell</p></body>"));
    expect(() => validateOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A, sealed.seal))
      .toThrow(/bytes differ/);

    fakeDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A);
    const resealed = sealOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A);
    writeFileSync(join(output, "releases", OFFLINE_LIFECYCLE_RELEASE_ID, "config/test.json"), "mutated release");
    expect(() => validateOfflineLifecycleDeployment(output, OFFLINE_LIFECYCLE_DEPLOYMENTS.A, resealed.seal))
      .toThrow(/bytes differ/);
  });

  it("cleans its exact owned temporary root after a build failure", () => {
    const owned = ownership();
    expect(() => prepareOfflineLifecycleFixtures({
      webRoot: "/workspace/web",
      createRoot: () => owned,
      run() { throw new Error("injected build failure"); },
    })).toThrow(/injected build failure/);
    expect(() => lstatSync(owned.root)).toThrow();
  });
});
