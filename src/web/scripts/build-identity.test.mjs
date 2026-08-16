// @vitest-environment node

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  assertSameBuildIdentity,
  privateCandidateBuildIdentity,
  resolveBuildIdentity,
  validateBuildIdentity,
} from "./build-identity.mjs";

const roots = [];
function root() {
  const value = mkdtempSync(join(tmpdir(), "searise-build-identity-"));
  roots.push(value);
  return value;
}
afterEach(() => roots.splice(0).forEach((value) => rmSync(value, { recursive: true, force: true })));

describe("canonical build identity", () => {
  it("resolves only allowlisted identity fields with process precedence", () => {
    const repositoryRoot = root();
    writeFileSync(join(repositoryRoot, ".env.production"), [
      "SEARISE_APP_BUILD_ID=file-build",
      "SEARISE_DATA_RELEASE_ID=file-release",
      "SEARISE_RELEASE_DISPOSITION=synthetic-fixture",
      "SEARISE_SECRET=must-not-appear",
    ].join("\n"));
    const identity = resolveBuildIdentity({
      mode: "production",
      repositoryRoot,
      environment: {
        SEARISE_APP_BUILD_ID: "process-build",
        SEARISE_DATA_RELEASE_ID: "process-release",
        SEARISE_RELEASE_DISPOSITION: "public-promoted",
      },
    });
    expect(identity).toEqual({
      schemaVersion: "1.0.0",
      appBuildId: "process-build",
      dataReleaseId: "process-release",
      releaseDisposition: "public-promoted",
      manifestPath: "/releases/process-release/manifest.json",
    });
    expect(JSON.stringify(identity)).not.toMatch(/secret|must-not-appear|searise-build-identity-/i);
  });

  it("keeps private Candidate identity explicit, local, and path-free", () => {
    expect(() => resolveBuildIdentity({
      mode: "production",
      repositoryRoot: root(),
      environment: { SEARISE_RELEASE_DISPOSITION: "private-engineering" },
    })).toThrow(/explicit local Candidate mode/);
    const privateIdentity = privateCandidateBuildIdentity("candidate-release");
    expect(privateIdentity).toEqual({
      schemaVersion: "1.0.0",
      appBuildId: "private-local-candidate",
      dataReleaseId: "candidate-release",
      releaseDisposition: "private-engineering",
      manifestPath: "/releases/candidate-release/manifest.json",
    });
    expect(JSON.stringify(privateIdentity)).not.toMatch(/candidate-v7|local-data|file:/i);
  });

  it("fails closed on extra fields, inconsistent manifests, and consumer mismatches", () => {
    const identity = resolveBuildIdentity({ mode: "production", repositoryRoot: root(), environment: {} });
    expect(() => validateBuildIdentity({ ...identity, localPath: "/private/candidate" })).toThrow(/additional/);
    expect(() => validateBuildIdentity({ ...identity, manifestPath: "/releases/other/manifest.json" })).toThrow(/inconsistent/);
    expect(() => assertSameBuildIdentity(
      identity,
      { ...identity, appBuildId: "different-build" },
      "service worker",
    )).toThrow(/service worker identity mismatch/);
  });
});
