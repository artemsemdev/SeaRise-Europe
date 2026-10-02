import { createHash } from "node:crypto";
import { chmodSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export const DATA_IDENTITIES = Object.freeze([
  "manifest.json", "context/manifest.json", "context/source-receipts.json",
  "basemap/assets-receipt.json", "basemap/protomaps-europe.pmtiles.receipt.json",
  "basemap/protomaps-world-overview.pmtiles.receipt.json",
]);

function confined(root, name) {
  const path = resolve(root, name);
  if (!path.startsWith(`${root}${sep}`)) throw new Error("Path escapes its root.");
  let cursor = root;
  for (const part of relative(root, path).split(sep)) {
    cursor = join(cursor, part);
    if (lstatSync(cursor).isSymbolicLink()) throw new Error("Candidate/data paths cannot traverse a symbolic link.");
  }
  return path;
}

function identity(root, name) {
  const path = confined(root, name);
  if (!lstatSync(path).isFile()) throw new Error("Inventory entries must be regular files.");
  const bytes = readFileSync(path);
  return { path: name, bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") };
}

export function dataIdentities(value) {
  const root = realpathSync(value);
  return DATA_IDENTITIES.map((name) => identity(root, name));
}

export function inventory(value) {
  if (lstatSync(value).isSymbolicLink()) throw new Error("App root cannot be a symbolic link.");
  const root = realpathSync(value);
  function walk(directory) {
    return readdirSync(directory).sort().flatMap((name) => {
      const path = confined(root, relative(root, join(directory, name)));
      const metadata = lstatSync(path);
      return metadata.isDirectory() ? walk(path) : [identity(root, relative(root, path).split(sep).join("/"))];
    });
  }
  return walk(root);
}

export function verifyCandidate(value, sourceRevision, identities) {
  if (lstatSync(value).isSymbolicLink()) throw new Error("Candidate root cannot be a symbolic link.");
  const root = realpathSync(value);
  const manifest = JSON.parse(readFileSync(confined(root, "candidate.json"), "utf8"));
  if (manifest.schemaVersion !== "local-demo-candidate-v1" || manifest.status !== "private-local-demo"
    || manifest.publicPromotionAuthorized !== false || manifest.mvpRelease !== false || manifest.atlasEdition !== "real-local") {
    throw new Error("Candidate must explicitly remain a private local demo.");
  }
  if (manifest.sourceRevision !== sourceRevision) throw new Error("Candidate source revision differs from the checkout.");
  if (JSON.stringify(manifest.dataIdentities) !== JSON.stringify(identities)) throw new Error("Candidate data identity differs.");
  const app = confined(root, "app");
  if (JSON.stringify(manifest.appInventory) !== JSON.stringify(inventory(app))) throw new Error("Candidate app inventory differs.");
  if (!readFileSync(join(app, "index.html"), "utf8").includes('<meta name="searise-atlas-edition" content="real-local" />')) {
    throw new Error("Candidate must contain the real-local edition.");
  }
  const build = JSON.parse(readFileSync(join(app, "build-identity.json"), "utf8"));
  if (build.appBuildId !== `demo-${sourceRevision}`) throw new Error("Candidate build identity differs from its source revision.");
  return { app, manifest };
}

export function parseOptions(args) {
  const result = {};
  for (let index = 0; index < args.length; index += 2) {
    const key = args[index].replace(/^--/u, "");
    const value = args[index + 1];
    if (!args[index].startsWith("--") || !["data-root", "python", "output", "candidate", "port"].includes(key)
      || key in result || !value || value.startsWith("--")) throw new Error("Unknown, duplicate, or incomplete option; see --help.");
    if (key === "port") {
      if (!/^[0-9]+$/u.test(value) || Number(value) < 1 || Number(value) > 65535) throw new Error("Port must be 1–65535.");
      result[key] = Number(value);
    } else {
      if (!isAbsolute(value)) throw new Error("Paths must be explicit absolute paths.");
      result[key] = resolve(value);
    }
  }
  return result;
}

export function createOutput(repositoryRoot, value) {
  const base = resolve(repositoryRoot, ".cache/demo-candidates");
  if (!value || !value.startsWith(`${base}${sep}`)) throw new Error("Output must be a new directory beneath this checkout's .cache/demo-candidates/.");
  let cursor = repositoryRoot;
  for (const part of relative(repositoryRoot, value).split(sep)) {
    cursor = join(cursor, part);
    if (cursor === value) break;
    try { mkdirSync(cursor); } catch (error) { if (error.code !== "EEXIST") throw error; }
    if (lstatSync(cursor).isSymbolicLink() || !lstatSync(cursor).isDirectory()) throw new Error("Output parent must be a real directory.");
  }
  mkdirSync(value); // Never overwrite an earlier candidate, including a symbolic link.
  return value;
}

export function seal(root) {
  for (const name of readdirSync(root)) {
    const path = join(root, name);
    if (lstatSync(path).isDirectory()) seal(path);
    else chmodSync(path, 0o444);
  }
  chmodSync(root, 0o555);
}
