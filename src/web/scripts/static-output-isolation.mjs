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
const CANONICAL_FLIGHT_SHA256 = "2f39c5f4d9d1050df7613999bc205bd08086cd689deefed730db3515a5d0b00f";
const FORBIDDEN_STATIC_OUTPUT_PATHS = Object.freeze([
  /(?:^|\/)candidate(?:[-_.]?v?\d+)?(?:[/.\-_]|$)/i,
  /(?:^|\/)local-data(?:\/|$)/i,
  /\.(?:7z|rar|tar|tar\.bz2|tar\.gz|tar\.xz|tgz|zip)$/i,
  /^docs\/product\/Mock\/SeaRise-Flight\.html$/u,
]);
const FORBIDDEN_RUNTIME_REFERENCES = Object.freeze([
  /candidate-v7/i,
  /local-data\/phase-1/i,
  /["'`](?:(?:https?:)?\/\/[^/"'`]+)?\/(?:v1\/)?(?:assess|geocode|config)(?:[/?#"'`]|$)/,
  /(?:^|[\s=:(,])\/(?:v1\/)?(?:assess|geocode|config)(?:[/?#\s]|$)/m,
]);
const RELATIVE_RUNTIME_ENDPOINT = /(["'`])((?:\.\/)?(?:v1\/)?(?:assess|geocode|config)(?:[/?#][^"'`]*)?)\1/gu;
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

function safeStaticOutputPath(value, label) {
  const path = safeRelativePath(value, label);
  if (FORBIDDEN_STATIC_OUTPUT_PATHS.some((pattern) => pattern.test(path))) {
    fail(`${label} names a private Candidate, archive, or canonical design-reference output`);
  }
  return path;
}

function addViteEntryOutputs(expected, entry, label) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) fail(`${label} is not a Vite manifest entry`);
  expected.add(safeStaticOutputPath(entry.file, `${label}.file`));
  for (const field of ["css", "assets"]) {
    if (entry[field] === undefined) continue;
    if (!Array.isArray(entry[field])) fail(`${label}.${field} is not an array`);
    for (const value of entry[field]) expected.add(safeStaticOutputPath(value, `${label}.${field}`));
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
  return safeStaticOutputPath(posix.join(posix.dirname(output), reference), `${output} source map`);
}

function inspectableStrings(bytes) {
  if (!bytes.includes(0)) return bytes.toString("utf8");
  const strings = [];
  let current = "";
  for (const byte of bytes) {
    if (byte >= 0x20 && byte <= 0x7e) current += String.fromCharCode(byte);
    else {
      if (current.length >= 4) strings.push(current);
      current = "";
    }
  }
  if (current.length >= 4) strings.push(current);
  for (const [characterOffset, zeroOffset] of [[0, 1], [1, 0]]) {
    current = "";
    for (let index = 0; index + 1 < bytes.length; index += 2) {
      const character = bytes[index + characterOffset];
      const zero = bytes[index + zeroOffset];
      if (zero === 0 && character >= 0x20 && character <= 0x7e) current += String.fromCharCode(character);
      else {
        if (current.length >= 4) strings.push(current);
        current = "";
      }
    }
    if (current.length >= 4) strings.push(current);
  }
  return strings.join("\n");
}

function activeProhibitionContent(path, text, releaseArtifactsByOutput) {
  const artifact = releaseArtifactsByOutput.get(path);
  if (artifact?.role !== "architecture-evidence") return text;
  let document;
  try {
    document = JSON.parse(text);
  } catch {
    fail(`Architecture evidence is not valid JSON: ${path}`);
  }
  const prohibitedRoutes = document?.runtime?.prohibitedRoutes;
  if (document?.runtime?.applicationApiCalls !== 0
      || JSON.stringify(prohibitedRoutes) !== JSON.stringify(["/assess", "/geocode", "/config"])) {
    fail(`Architecture evidence does not contain the exact zero-call route prohibition: ${path}`);
  }
  const sanitized = JSON.parse(JSON.stringify(document));
  delete sanitized.runtime.prohibitedRoutes;
  return JSON.stringify(sanitized);
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
  const expected = new Set([...ROOT_OUTPUTS, buildIdentityFile, applicationBuildIdentityFile]
    .map((path) => safeStaticOutputPath(path, "Required static output")));
  const releasePrefix = safeStaticOutputPath(`releases/${safeRelativePath(releaseId, "release ID")}`, "Release prefix");
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
      expected.add(safeStaticOutputPath(path.slice(1), `Embedded shell manifest path ${index}`));
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
    expected.add(safeStaticOutputPath(`${releasePrefix}/${safeRelativePath(artifact.path, `Release manifest artifact ${index}`)}`,
      `Release manifest artifact ${index}`));
  }
  const allowedReleaseConfigPaths = new Set(releaseManifest.artifacts
    .map(({ path }) => path)
    .filter((path) => typeof path === "string" && /^config\/[A-Za-z0-9._-]+\.json$/u.test(path)));
  const allowedReleaseConfigReferences = new Set([...allowedReleaseConfigPaths]
    .map((path) => `/${releasePrefix}/${path}`));
  const releaseArtifactsByOutput = new Map(releaseManifest.artifacts.map((artifact) =>
    [`${releasePrefix}/${artifact.path}`, artifact]));

  const actual = paths.map((path) => {
    const relativePath = relative(dist, path).replaceAll("\\", "/");
    const safePath = safeStaticOutputPath(relativePath, "Static output");
    const metadata = lstatSync(path);
    if (!metadata.isFile() || metadata.isSymbolicLink()) fail(`Static output is not a regular file: ${safePath}`);
    return safePath;
  });
  if (new Set(actual).size !== actual.length) fail("Static output contains duplicate paths");

  const missing = [...expected].filter((path) => path !== "build-report.json" && !actual.includes(path)).sort();
  if (missing.length) fail(`Static output is missing allowlisted files: ${missing.join(", ")}`);
  const unknown = actual.filter((path) => !expected.has(path)).sort();
  if (unknown.length) fail(`Static output contains unlisted files: ${unknown.join(", ")}`);

  for (const path of actual) {
    const bytes = readFileSync(resolve(dist, path));
    if (createHash("sha256").update(bytes).digest("hex") === CANONICAL_FLIGHT_SHA256) {
      fail(`Canonical Flight mock bytes are forbidden in static output: ${path}`);
    }
    const text = activeProhibitionContent(path, inspectableStrings(bytes), releaseArtifactsByOutput);
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
