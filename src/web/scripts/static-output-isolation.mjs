import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { extname, posix, relative, resolve } from "node:path";

const ROOT_OUTPUTS = Object.freeze([
  "index.html",
  "about/architecture/index.html",
  "vite-manifest.json",
  "service-worker.js",
  "build-report.json",
]);
const SCANNED_EXTENSIONS = new Set([".html", ".js", ".css", ".map"]);
const FORBIDDEN_STATIC_OUTPUT_PATHS = Object.freeze([
  /(?:^|\/)candidate(?:[-_.]?v?\d+)?(?:[/.\-_]|$)/i,
  /(?:^|\/)local-data(?:\/|$)/i,
  /\.(?:7z|rar|tar|tar\.bz2|tar\.gz|tar\.xz|tgz|zip)$/i,
]);
const FORBIDDEN_RUNTIME_REFERENCES = Object.freeze([
  /candidate-v7/i,
  /local-data\/phase-1/i,
  /["'`](?:(?:https?:)?\/\/[^/"'`]+)?\/(?:assess|geocode|config)(?:[/?#"'`]|$)/,
]);
const RELATIVE_RUNTIME_ENDPOINT = /(["'`])((?:\.\/)?(?:assess|geocode|config)(?:[/?#][^"'`]*)?)\1/gu;
const RELEASE_CONFIG_REFERENCE = /\/releases\/[A-Za-z0-9._-]+\/config\/[A-Za-z0-9._-]+\.json(?:[?#][A-Za-z0-9._~!$&'()*+,;=:@%/?-]*)?/gu;

function fail(message) { throw new Error(message); }

function containsForbiddenRuntimeReference(text, allowedReleaseConfigPaths, allowedReleaseConfigReferences) {
  if (FORBIDDEN_RUNTIME_REFERENCES.some((pattern) => pattern.test(text))) return true;
  for (const match of text.matchAll(RELEASE_CONFIG_REFERENCE)) {
    if (!allowedReleaseConfigReferences.has(match[0])) return true;
  }
  for (const match of text.matchAll(RELATIVE_RUNTIME_ENDPOINT)) {
    const path = match[2].replace(/^\.\//u, "").replace(/\\+$/u, "");
    if (!allowedReleaseConfigPaths.has(path)) return true;
  }
  return false;
}

function safeRelativePath(value, label) {
  if (typeof value !== "string" || !value || value.includes("\\") || value.startsWith("/")
      || posix.normalize(value) !== value || value.split("/").some((part) => !part || part === "." || part === "..")) {
    fail(`${label} is not a canonical relative output path`);
  }
  return value;
}

function safePublicReleaseArtifactPath(value, label) {
  const path = safeRelativePath(value, label);
  if (FORBIDDEN_STATIC_OUTPUT_PATHS.some((pattern) => pattern.test(path))) {
    fail(`${label} names a private Candidate or archive output`);
  }
  return path;
}

function addViteEntryOutputs(expected, entry, label) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) fail(`${label} is not a Vite manifest entry`);
  expected.add(safeRelativePath(entry.file, `${label}.file`));
  for (const field of ["css", "assets"]) {
    if (entry[field] === undefined) continue;
    if (!Array.isArray(entry[field])) fail(`${label}.${field} is not an array`);
    for (const value of entry[field]) expected.add(safeRelativePath(value, `${label}.${field}`));
  }
}

function referencedSourceMap(dist, output) {
  if (extname(output) !== ".js") return null;
  const source = readFileSync(resolve(dist, output), "utf8");
  const matches = [...source.matchAll(/\/\/[#@]\s*sourceMappingURL=([^\s]+)\s*$/gmu)];
  if (matches.length > 1) fail(`${output} declares multiple source maps`);
  if (!matches.length) return null;
  const reference = matches[0][1];
  if (reference.includes("/") || reference.includes("\\") || reference.startsWith("data:")) {
    fail(`${output} declares a non-local source map`);
  }
  return safeRelativePath(posix.join(posix.dirname(output), reference), `${output} source map`);
}

export function validateStaticOutputIsolation({
  dist,
  paths,
  viteManifest,
  releaseManifest,
  releaseId,
  buildIdentityFile,
  applicationBuildIdentityFile,
  shellManifestPaths,
}) {
  const expected = new Set([...ROOT_OUTPUTS, buildIdentityFile, applicationBuildIdentityFile]);
  const releasePrefix = `releases/${safeRelativePath(releaseId, "release ID")}`;
  const releaseManifestPath = `${releasePrefix}/manifest.json`;
  expected.add(releaseManifestPath);

  if (!viteManifest || typeof viteManifest !== "object" || Array.isArray(viteManifest)) {
    fail("Vite output manifest is not an object");
  }
  for (const [key, entry] of Object.entries(viteManifest).sort(([left], [right]) => left.localeCompare(right))) {
    addViteEntryOutputs(expected, entry, `Vite manifest entry ${key}`);
  }
  if (!Array.isArray(shellManifestPaths)) fail("Embedded shell manifest paths are not an array");
  for (const [index, path] of shellManifestPaths.entries()) {
    if (path === "/") expected.add("index.html");
    else if (typeof path === "string" && path.startsWith("/")) {
      expected.add(safeRelativePath(path.slice(1), `Embedded shell manifest path ${index}`));
    } else fail(`Embedded shell manifest path ${index} is not root-relative`);
  }

  const viteOutputs = [...expected];
  for (const output of viteOutputs) {
    const absolute = resolve(dist, output);
    if (!paths.includes(absolute)) continue;
    const sourceMap = referencedSourceMap(dist, output);
    if (sourceMap) expected.add(sourceMap);
  }

  if (!releaseManifest || typeof releaseManifest !== "object" || Array.isArray(releaseManifest)
      || releaseManifest.dataReleaseId !== releaseId || !Array.isArray(releaseManifest.artifacts)) {
    fail("Release manifest cannot authorize the static release inventory");
  }
  for (const [index, artifact] of releaseManifest.artifacts.entries()) {
    if (!artifact || typeof artifact !== "object" || Array.isArray(artifact)) {
      fail(`Release manifest artifact ${index} is not an object`);
    }
    expected.add(`${releasePrefix}/${safePublicReleaseArtifactPath(artifact.path, `Release manifest artifact ${index}`)}`);
  }
  const allowedReleaseConfigPaths = new Set(releaseManifest.artifacts
    .map(({ path }) => path)
    .filter((path) => typeof path === "string" && /^config\/[A-Za-z0-9._-]+\.json$/u.test(path)));
  const allowedReleaseConfigReferences = new Set([...allowedReleaseConfigPaths]
    .map((path) => `/${releasePrefix}/${path}`));

  const actual = paths.map((path) => {
    const relativePath = relative(dist, path).replaceAll("\\", "/");
    const safePath = safeRelativePath(relativePath, "Static output");
    const metadata = lstatSync(path);
    if (!metadata.isFile() || metadata.isSymbolicLink()) fail(`Static output is not a regular file: ${safePath}`);
    return safePath;
  });
  if (new Set(actual).size !== actual.length) fail("Static output contains duplicate paths");

  const missing = [...expected].filter((path) => path !== "build-report.json" && !actual.includes(path)).sort();
  if (missing.length) fail(`Static output is missing allowlisted files: ${missing.join(", ")}`);
  const unknown = actual.filter((path) => !expected.has(path)).sort();
  if (unknown.length) fail(`Static output contains unlisted files: ${unknown.join(", ")}`);

  for (const path of actual.filter((path) => SCANNED_EXTENSIONS.has(extname(path)))) {
    const text = readFileSync(resolve(dist, path), "utf8");
    if (containsForbiddenRuntimeReference(text, allowedReleaseConfigPaths, allowedReleaseConfigReferences)) {
      fail(`Forbidden runtime reference in ${path}`);
    }
  }

  const allowedPaths = [...expected].sort();
  return Object.freeze({
    allowedPaths: Object.freeze(allowedPaths),
    inventorySha256: createHash("sha256").update(`${JSON.stringify(allowedPaths)}\n`).digest("hex"),
  });
}
