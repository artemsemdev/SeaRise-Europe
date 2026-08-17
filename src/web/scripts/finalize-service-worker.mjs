import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { validateApplicationBuildIdentity } from "./application-build-identity.mjs";
import { buildIdentityFile, validateBuildIdentity } from "./build-identity.mjs";
import {
  createEmbeddedPrecache,
  deriveShellPrecacheEntries,
  precachePlaceholder,
} from "./service-worker-precache.mjs";
import { resolveStaticBuildRoot } from "./static-build-root.mjs";

const root = resolve(import.meta.dirname, "..");
const dist = resolveStaticBuildRoot({ webRoot: root });
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
validateApplicationBuildIdentity({ dist, expectedIdentity: buildIdentity });
const entries = deriveShellPrecacheEntries({
  dist,
  viteManifest,
  dataReleaseId: buildIdentity.dataReleaseId,
});
const payload = createEmbeddedPrecache({ buildIdentity, entries });
let worker = readFileSync(workerPath, "utf8");
const occurrences = worker.split(precachePlaceholder).length - 1;
if (occurrences !== 1) throw new Error("Service worker precache placeholder is missing or duplicated");
worker = worker.replace(
  precachePlaceholder,
  JSON.stringify(payload).replaceAll("\\", "\\\\").replaceAll('"', '\\"'),
);
worker = worker.replace(/\n?\/\/# sourceMappingURL=service-worker\.js\.map\s*$/u, "");
writeFileSync(workerPath, worker);
rmSync(`${workerPath}.map`, { force: true });
console.log(`embedded ${entries.length} byte-verified shell resources in service-worker.js`);
