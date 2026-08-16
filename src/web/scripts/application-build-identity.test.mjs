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
import {
  createEmbeddedPrecache,
  extractEmbeddedPrecachePayload,
  shellPrecachePaths,
} from "./service-worker-precache.mjs";

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
      authorityKind: "searise-shell-precache-v3",
      contractVersion: 3,
      buildIdentity: oldIdentity,
      entries: [
        { path: "/", mediaType: "text/html", byteSize: 1, sha256: "1".repeat(64) },
        { path: oldIdentity.manifestPath, mediaType: "application/json", byteSize: 1, sha256: "2".repeat(64) },
      ],
      precacheSetSha256: "0".repeat(64),
    };
    const embedded = `JSON.parse(${JSON.stringify(JSON.stringify(precache))})`;
    expect(extractEmbeddedPrecachePayload(embedded)).toEqual(precache);
    expect(() => extractEmbeddedPrecachePayload("void 0;")).toThrow(/found 0/);
    expect(() => extractEmbeddedPrecachePayload(`${embedded};${embedded}`)).toThrow(/found 2/);
  });

  it("freezes the generated worker authority and every byte-identity entry", () => {
    const entry = {
      path: "/",
      mediaType: "text/html",
      byteSize: 1,
      sha256: "1".repeat(64),
    };
    const precache = createEmbeddedPrecache({ buildIdentity: oldIdentity, entries: [entry] });
    expect(Object.isFrozen(precache)).toBe(true);
    expect(Object.isFrozen(precache.entries)).toBe(true);
    expect(Object.isFrozen(precache.entries[0])).toBe(true);
    expect(precache.entries[0]).not.toBe(entry);
  });

  it("derives the recursive Flight shell plus emitted Worker and WASM references", () => {
    const dist = temporaryDist();
    const assets = {
      "main-a.js": 'import("./MapExplorer-b.js");new Worker(new URL("/assets/search.worker-c.js",import.meta.url));',
      "shared-d.js": 'import("./decoder-e.js");',
      "decoder-e.js": "export const decoder=true;",
      "MapExplorer-b.js": 'import("./map-runtime-f.js");',
      "map-runtime-f.js": "export const map=true;",
      "map-runtime-g.css": 'url("./map-font-h.woff2")',
      "map-font-h.woff2": "font",
      "search.worker-c.js": 'new URL("./brotli_wasm_bg-i.wasm",import.meta.url);',
      "brotli_wasm_bg-i.wasm": "wasm",
      "unreferenced-j.js": "throw new Error('not shell');",
    };
    for (const [name, source] of Object.entries(assets)) {
      writeFileSync(join(dist, "assets", name), source);
    }
    const manifest = {
      _main: {
        file: "assets/main-a.js",
        imports: ["_shared"],
        dynamicImports: ["src/components/map/MapExplorer.tsx"],
      },
      _shared: {
        file: "assets/shared-d.js",
        dynamicImports: ["decoder"],
      },
      decoder: { file: "assets/decoder-e.js" },
      "src/components/map/MapExplorer.tsx": {
        file: "assets/MapExplorer-b.js",
        imports: ["_main"],
        dynamicImports: ["src/components/map/map-runtime.ts"],
      },
      "src/components/map/map-runtime.ts": {
        file: "assets/map-runtime-f.js",
        css: ["assets/map-runtime-g.css"],
      },
    };

    const paths = shellPrecachePaths({ dist, viteManifest: manifest, dataReleaseId: "old-release" });

    expect(paths).toEqual(expect.arrayContaining([
      "/assets/MapExplorer-b.js",
      "/assets/brotli_wasm_bg-i.wasm",
      "/assets/decoder-e.js",
      "/assets/map-font-h.woff2",
      "/assets/map-runtime-f.js",
      "/assets/map-runtime-g.css",
      "/assets/search.worker-c.js",
    ]));
    expect(paths).not.toContain("/assets/unreferenced-j.js");
  });
});
