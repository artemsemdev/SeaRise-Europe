import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, extname, posix, resolve } from "node:path";
import { applicationBuildIdentityFile } from "./application-build-identity.mjs";

export const precachePlaceholder = "__SEARISE_PRECACHE_PENDING_V3__";
export const precacheAuthorityKind = "searise-shell-precache-v3";

const MEDIA_TYPES = Object.freeze({
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".wasm": "application/wasm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
});

function mediaTypeForPath(path) {
  const extension = path === "/" ? ".html" : extname(path);
  const mediaType = MEDIA_TYPES[extension];
  if (!mediaType) throw new Error(`No canonical shell media type exists for ${path}`);
  return mediaType;
}

function collectEntry(viteManifest, key, files) {
  const entry = viteManifest[key];
  if (!entry || files.has(entry.file)) return;
  files.add(entry.file);
  for (const css of entry.css ?? []) files.add(css);
  for (const asset of entry.assets ?? []) files.add(asset);
  for (const imported of entry.imports ?? []) collectEntry(viteManifest, imported, files);
}

export function shellPrecachePaths({ dist, viteManifest, dataReleaseId }) {
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

export function deriveShellPrecacheEntries({ dist, viteManifest, dataReleaseId }) {
  const paths = shellPrecachePaths({ dist, viteManifest, dataReleaseId });
  if (new Set(paths).size !== paths.length) {
    throw new Error("The generated shell precache contains duplicate paths");
  }
  return Object.freeze(paths.map((path) => {
    const filePath = path === "/" ? resolve(dist, "index.html") : resolve(dist, `.${path}`);
    const bytes = readFileSync(filePath);
    return Object.freeze({
      path,
      mediaType: mediaTypeForPath(path),
      byteSize: bytes.length,
      sha256: createHash("sha256").update(bytes).digest("hex"),
    });
  }));
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
    .filter((value) => value?.authorityKind === precacheAuthorityKind);
  if (candidates.length !== 1) {
    throw new Error(`Service worker must contain exactly one readable precache authority; found ${candidates.length}`);
  }
  return candidates[0];
}

export function createEmbeddedPrecache({ buildIdentity, entries }) {
  const authority = Object.freeze({
    authorityKind: precacheAuthorityKind,
    contractVersion: 3,
    buildIdentity,
    entries: Object.freeze(entries.map((entry) => Object.freeze({ ...entry }))),
  });
  const precacheSetSha256 = createHash("sha256")
    .update(JSON.stringify(authority))
    .digest("hex");
  return Object.freeze({
    ...authority,
    precacheSetSha256,
  });
}
