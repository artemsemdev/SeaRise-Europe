import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, extname, join, relative, resolve } from "node:path";
import { applicationBuildIdentityFile } from "./application-build-identity.mjs";

export const precachePlaceholder = "__SEARISE_PRECACHE_PENDING_V3__";
export const precacheAuthorityKind = "searise-shell-precache-v3";

export function rangeIntegrityBootstrapPath(dataReleaseId) {
  return `/releases/${dataReleaseId}/analysis/cog-range-integrity.json`;
}

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
  for (const imported of entry.dynamicImports ?? []) collectEntry(viteManifest, imported, files);
}

function emittedAssetFiles(dist) {
  const root = resolve(dist, "assets");
  const visit = (directory) => readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? visit(path) : [relative(dist, path).replaceAll("\\", "/")];
  });
  const assets = visit(root).filter((path) => MEDIA_TYPES[extname(path)]);
  const names = assets.map((path) => basename(path));
  if (new Set(names).size !== names.length) {
    throw new Error("The emitted shell asset basenames are not unique");
  }
  return assets;
}

function collectEmittedReferences(dist, files) {
  const candidates = emittedAssetFiles(dist);
  let changed = true;
  while (changed) {
    changed = false;
    for (const sourcePath of [...files]) {
      if (![".css", ".js"].includes(extname(sourcePath))) continue;
      const source = readFileSync(resolve(dist, sourcePath), "utf8");
      for (const candidate of candidates) {
        if (files.has(candidate)) continue;
        const name = basename(candidate);
        if (
          source.includes(candidate) ||
          source.includes(`./${name}`) ||
          source.includes(`/${name}`)
        ) {
          files.add(candidate);
          changed = true;
        }
      }
    }
  }
}

export function shellPrecachePaths({ dist, viteManifest, dataReleaseId }) {
  const files = new Set();
  const mainKey = Object.entries(viteManifest).find(([, entry]) =>
    entry.dynamicImports?.includes("src/components/map/MapExplorer.tsx"),
  )?.[0];
  if (!mainKey) throw new Error("Vite manifest has no static application entry");
  collectEntry(viteManifest, mainKey, files);
  collectEmittedReferences(dist, files);
  return [
    "/",
    `/${applicationBuildIdentityFile}`,
    ...[...files].map((path) => `/${path}`),
    `/releases/${dataReleaseId}/manifest.json`,
    rangeIntegrityBootstrapPath(dataReleaseId),
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
