import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, posix } from "node:path";
import { applicationBuildIdentityFile } from "./application-build-identity.mjs";

export const precachePlaceholder = "__SEARISE_PRECACHE_PENDING_V2__";

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
    `/${applicationBuildIdentityFile}`,
    ...[...files].map((path) => `/${path}`),
    `/releases/${dataReleaseId}/manifest.json`,
  ].sort();
}

export function extractEmbeddedPrecachePayload(source) {
  const candidates = [...source.matchAll(/JSON\.parse\((?:`((?:\\.|[^`\\])*)`|("(?:\\.|[^"\\])*"))\)/gu)]
    .map((match) => {
      try {
        if (match[2]) return JSON.parse(JSON.parse(match[2]));
        try { return JSON.parse(match[1]); }
        catch { return JSON.parse(JSON.parse(`"${match[1]}"`)); }
      } catch { return null; }
    })
    .filter((value) => value?.contractVersion === 2 && value?.buildIdentity && Array.isArray(value.urls));
  if (candidates.length !== 1) {
    throw new Error(`Service worker must contain exactly one readable precache authority; found ${candidates.length}`);
  }
  return candidates[0];
}

export function createEmbeddedPrecache({ buildIdentity, urls }) {
  const authority = { contractVersion: 2, buildIdentity, urls };
  const precacheSetSha256 = createHash("sha256")
    .update(JSON.stringify(authority))
    .digest("hex");
  return {
    ...authority,
    precacheSetSha256,
  };
}
