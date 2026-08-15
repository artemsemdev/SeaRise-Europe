import { brotliCompressSync } from "node:zlib";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const paths = files(dist);
const required = [
  resolve(dist, "index.html"),
  resolve(dist, "about/architecture/index.html"),
  resolve(dist, "releases", releaseId, "manifest.json"),
];
for (const path of required) {
  if (!paths.includes(path)) throw new Error(`Static build is missing ${relative(dist, path)}`);
}

const scanned = paths.filter((path) => [".html", ".js", ".css", ".map"].includes(extname(path)));
const forbidden = [/candidate-v7/i, /local-data\/phase-1/i, /["'`]\/[^"'`]*assess(?:[/?"'`]|$)/, /["'`]\/[^"'`]*geocode(?:[/?"'`]|$)/, /["'`]\/[^"'`]*config(?:[/?"'`]|$)/];
for (const path of scanned) {
  const text = readFileSync(path, "utf8");
  if (forbidden.some((pattern) => pattern.test(text))) {
    throw new Error(`Forbidden runtime reference in ${relative(dist, path)}`);
  }
}

const assets = paths
  .filter((path) => [".js", ".css", ".woff2"].includes(extname(path)))
  .map((path) => {
    const bytes = readFileSync(path);
    return {
      path: relative(dist, path),
      bytes: bytes.length,
      brotliBytes: brotliCompressSync(bytes).length,
    };
  })
  .sort((left, right) => left.path.localeCompare(right.path));

const report = {
  schemaVersion: "1.0.0",
  appBuildId: process.env.SEARISE_APP_BUILD_ID ?? "local-fixture",
  dataReleaseId: releaseId,
  releaseDisposition: "synthetic-fixture",
  staticRoutes: ["/", "/about/architecture/"],
  assets,
};
writeFileSync(resolve(dist, "build-report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(`validated ${paths.length} static files; ${assets.length} measured assets`);
