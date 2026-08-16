import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { buildIdentityFile, validateBuildIdentity } from "./build-identity.mjs";
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

const buildIdentity = validateBuildIdentity(
  JSON.parse(readFileSync(resolve(dist, buildIdentityFile), "utf8")),
);
const urls = shellPrecacheUrls({
  dist,
  viteManifest,
  dataReleaseId: buildIdentity.dataReleaseId,
});
const payload = createEmbeddedPrecache({ buildIdentity, urls });
let worker = readFileSync(workerPath, "utf8");
const occurrences = worker.split(precachePlaceholder).length - 1;
if (occurrences !== 1) throw new Error("Service worker precache placeholder is missing or duplicated");
worker = worker.replace(precachePlaceholder, JSON.stringify(payload).replaceAll("\\", "\\\\").replaceAll('"', '\\"'));
worker = worker.replace(/\n?\/\/# sourceMappingURL=service-worker\.js\.map\s*$/u, "");
writeFileSync(workerPath, worker);
rmSync(`${workerPath}.map`, { force: true });
console.log(`embedded ${urls.length} exact shell resources in service-worker.js`);
