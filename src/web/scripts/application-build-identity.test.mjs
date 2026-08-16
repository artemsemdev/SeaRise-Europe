// @vitest-environment node

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runInNewContext } from "node:vm";
import { afterEach, describe, expect, it } from "vitest";
import {
  applicationBuildIdentityFile,
  applicationBuildIdentityMarker,
  extractApplicationBuildIdentity,
  serializeApplicationBuildIdentity,
  validateApplicationBuildIdentity,
} from "./application-build-identity.mjs";
import { extractEmbeddedPrecachePayload } from "./service-worker-precache.mjs";

const roots = [];
const oldIdentity = Object.freeze({
  schemaVersion: "1.0.0",
  appBuildId: "old-app",
  dataReleaseId: "old-release",
  releaseDisposition: "synthetic-fixture",
  manifestPath: "/releases/old-release/manifest.json",
});
const forgedIdentity = Object.freeze({
  ...oldIdentity,
  appBuildId: "forged-app",
  dataReleaseId: "forged-release",
  manifestPath: "/releases/forged-release/manifest.json",
});

function temporaryDist() {
  const dist = mkdtempSync(join(tmpdir(), "searise-application-identity-"));
  roots.push(dist);
  mkdirSync(join(dist, "assets"));
  writeFileSync(join(dist, "index.html"), [
    "<html><head>",
    `  <script src="/${applicationBuildIdentityFile}"></script>`,
    "  <script type=\"module\" src=\"/assets/index.js\"></script>",
    "</head></html>",
  ].join("\n"));
  return dist;
}

afterEach(() => roots.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true })));

describe("authoritative application build identity", () => {
  it("round-trips exactly one generated payload", () => {
    expect(extractApplicationBuildIdentity(serializeApplicationBuildIdentity(oldIdentity)))
      .toEqual(oldIdentity);
  });

  it("installs a non-writable, non-configurable runtime authority", () => {
    const context = {};
    runInNewContext(serializeApplicationBuildIdentity(oldIdentity), context);
    const descriptor = Object.getOwnPropertyDescriptor(context, "__SEARISE_RUNTIME_BUILD_IDENTITY__");
    expect(descriptor).toMatchObject({ configurable: false, enumerable: false, writable: false });
    expect(descriptor?.value).toEqual(oldIdentity);
  });

  it.each([
    ["zero", "void 0;", /exactly one/],
    ["duplicate", `${serializeApplicationBuildIdentity(oldIdentity)}${serializeApplicationBuildIdentity(oldIdentity)}`, /exactly one/],
    ["malformed", `/*${applicationBuildIdentityMarker}*/Object.defineProperty(globalThis,"__SEARISE_RUNTIME_BUILD_IDENTITY__",{configurable:false,enumerable:false,writable:false,value:Object.freeze({bad})});`, /malformed/],
  ])("rejects %s identity markers", (_name, source, error) => {
    expect(() => extractApplicationBuildIdentity(source)).toThrow(error);
  });

  it("rejects the exact forged-emitted-identity plus main-bundle decoy attack", () => {
    const dist = temporaryDist();
    writeFileSync(join(dist, applicationBuildIdentityFile), serializeApplicationBuildIdentity(oldIdentity));
    writeFileSync(join(dist, "assets/index.js"), [
      serializeApplicationBuildIdentity(forgedIdentity),
      "globalThis.applicationStarted=true;",
    ].join("\n"));

    expect(() => validateApplicationBuildIdentity({ dist, expectedIdentity: forgedIdentity }))
      .toThrow(/application runtime identity mismatch/);
  });

  it("rejects a decoy marker even when the authoritative identity matches", () => {
    const dist = temporaryDist();
    writeFileSync(join(dist, applicationBuildIdentityFile), serializeApplicationBuildIdentity(oldIdentity));
    writeFileSync(join(dist, "assets/index.js"), serializeApplicationBuildIdentity(oldIdentity));
    expect(() => validateApplicationBuildIdentity({ dist, expectedIdentity: oldIdentity }))
      .toThrow(/Unauthorised application build identity marker/);
  });

  it("requires exactly one readable worker authority instead of selecting a decoy", () => {
    const precache = {
      contractVersion: 2,
      buildIdentity: oldIdentity,
      urls: ["/", oldIdentity.manifestPath],
      precacheSetSha256: "0".repeat(64),
    };
    const embedded = `JSON.parse(${JSON.stringify(JSON.stringify(precache))})`;
    expect(extractEmbeddedPrecachePayload(embedded)).toEqual(precache);
    expect(() => extractEmbeddedPrecachePayload("void 0;")).toThrow(/found 0/);
    expect(() => extractEmbeddedPrecachePayload(`${embedded};${embedded}`)).toThrow(/found 2/);
  });
});
