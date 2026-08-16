import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  createEmbeddedPrecache,
  precachePlaceholder,
  shellPrecacheUrls,
} from "./service-worker-precache.mjs";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
const workerPath = resolve(dist, "service-worker.js");
const viteManifest = JSON.parse(readFileSync(resolve(dist, "vite-manifest.json"), "utf8"));
const workerEntry = viteManifest["src/offline/service-worker.ts"];
if (
  !workerEntry ||
  workerEntry.file !== "service-worker.js" ||
  (workerEntry.imports?.length ?? 0) !== 0 ||
  (workerEntry.dynamicImports?.length ?? 0) !== 0
) {
  throw new Error("The root service worker must be a self-contained Vite entry");
}

const appBuildId = process.env.SEARISE_APP_BUILD_ID ?? "local-fixture";
const dataReleaseId = process.env.SEARISE_DATA_RELEASE_ID ??
  "searise-europe-v1.0.0-20260810-c096aeab4e09";
const releaseDisposition = process.env.SEARISE_RELEASE_DISPOSITION ?? "synthetic-fixture";
if (releaseDisposition === "private-engineering") {
  throw new Error("Private engineering builds cannot emit a service worker");
}
const urls = shellPrecacheUrls({ dist, viteManifest, dataReleaseId });
const payload = createEmbeddedPrecache({ appBuildId, dataReleaseId, releaseDisposition, urls });
let worker = readFileSync(workerPath, "utf8");
const occurrences = worker.split(precachePlaceholder).length - 1;
if (occurrences !== 1) throw new Error("Service worker precache placeholder is missing or duplicated");
worker = worker.replace(precachePlaceholder, JSON.stringify(payload).replaceAll("\\", "\\\\").replaceAll('"', '\\"'));
worker = worker.replace(/\n?\/\/# sourceMappingURL=service-worker\.js\.map\s*$/u, "");
writeFileSync(workerPath, worker);
rmSync(`${workerPath}.map`, { force: true });
console.log(`embedded ${urls.length} exact shell resources in service-worker.js`);
