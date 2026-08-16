import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, posix } from "node:path";

export const precachePlaceholder = "__SEARISE_PRECACHE_PENDING_V1__";

function collectEntry(viteManifest, key, files) {
  const entry = viteManifest[key];
  if (!entry || files.has(entry.file)) return;
  files.add(entry.file);
  for (const css of entry.css ?? []) files.add(css);
  for (const asset of entry.assets ?? []) files.add(asset);
  for (const imported of entry.imports ?? []) collectEntry(viteManifest, imported, files);
}

export function shellPrecacheUrls({ dist, viteManifest, dataReleaseId }) {
  const files = new Set();
  const mainKey = Object.entries(viteManifest).find(([, entry]) =>
    entry.dynamicImports?.includes("src/components/map/MapExplorer.tsx"),
  )?.[0];
  if (!mainKey) throw new Error("Vite manifest has no static application entry");
  collectEntry(viteManifest, mainKey, files);
  for (const file of [...files].filter((path) => path.endsWith(".css"))) {
    const css = readFileSync(`${dist}/${file}`, "utf8");
    for (const match of css.matchAll(/url\((?:["']?)([^"')]+)(?:["']?)\)/gu)) {
      if (/^(?:data:|https?:)/u.test(match[1])) continue;
      files.add(match[1].startsWith("/")
        ? match[1].slice(1)
        : posix.normalize(posix.join(dirname(file), match[1])));
    }
  }
  return [
    "/",
    ...[...files].map((path) => `/${path}`),
    `/releases/${dataReleaseId}/manifest.json`,
  ].sort();
}

export function createEmbeddedPrecache({ appBuildId, dataReleaseId, releaseDisposition, urls }) {
  const authority = { contractVersion: 1, appBuildId, dataReleaseId, urls };
  const precacheSetSha256 = createHash("sha256")
    .update(JSON.stringify(authority))
    .digest("hex");
  return {
    contractVersion: 1,
    appBuildId,
    dataReleaseId,
    releaseDisposition,
    manifestPath: `/releases/${dataReleaseId}/manifest.json`,
    urls,
    precacheSetSha256,
  };
}
