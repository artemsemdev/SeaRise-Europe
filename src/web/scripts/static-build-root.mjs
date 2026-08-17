import { randomBytes } from "node:crypto";
import { lstatSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

export const STATIC_BUILD_ROOT_ENV = "SEARISE_WEB_DIST_ROOT";
export const LIFECYCLE_BUILD_ENV = "SEARISE_LIFECYCLE_BUILD";
export const LIFECYCLE_ROOT_ENV = "SEARISE_LIFECYCLE_ROOT";
export const LIFECYCLE_ROOT_TOKEN_ENV = "SEARISE_LIFECYCLE_ROOT_TOKEN";
const ROOT_PREFIX = "searise-offline-lifecycle-";
const OWNER_MARKER = ".searise-lifecycle-owner";

function inside(root, target) {
  const child = relative(root, target);
  return child !== "" && child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child);
}

function assertExistingPathHasNoSymlinks(root, target) {
  const child = relative(root, target);
  let cursor = root;
  for (const part of child.split(sep).filter(Boolean)) {
    cursor = resolve(cursor, part);
    try {
      if (lstatSync(cursor).isSymbolicLink()) {
        throw new Error("Lifecycle build output cannot traverse a symbolic link.");
      }
    } catch (error) {
      if (error?.code === "ENOENT") return;
      throw error;
    }
  }
}

export function createOwnedLifecycleRoot() {
  const temporary = realpathSync(tmpdir());
  const root = mkdtempSync(join(temporary, ROOT_PREFIX));
  const token = randomBytes(32).toString("hex");
  writeFileSync(join(root, OWNER_MARKER), `${token}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
  return Object.freeze({ root, token });
}

export function validateOwnedLifecycleRoot({ root: value, token }) {
  if (!value || !isAbsolute(value) || typeof token !== "string" || !/^[0-9a-f]{64}$/u.test(token)) {
    throw new Error("Lifecycle root ownership is invalid.");
  }
  const temporary = realpathSync(tmpdir());
  const lexical = resolve(value);
  const root = realpathSync(lexical);
  const metadata = lstatSync(lexical);
  if (lexical !== root || !metadata.isDirectory() || metadata.isSymbolicLink() ||
      dirname(root) !== temporary || !basename(root).startsWith(ROOT_PREFIX)) {
    throw new Error("Lifecycle root must be a canonical owned OS temporary directory.");
  }
  const marker = join(root, OWNER_MARKER);
  const markerMetadata = lstatSync(marker);
  if (!markerMetadata.isFile() || markerMetadata.isSymbolicLink() || readFileSync(marker, "utf8") !== `${token}\n`) {
    throw new Error("Lifecycle root owner marker is invalid.");
  }
  return root;
}

/**
 * Resolves the normal production output or a lifecycle-only temporary root.
 * Alternate roots require an explicit build mode and an existing, real
 * lifecycle root so an inherited environment variable cannot redirect a
 * normal production build into the repository or another durable location.
 */
export function resolveStaticBuildRoot({ webRoot, environment = process.env }) {
  const normal = resolve(webRoot, "dist");
  const requested = environment[STATIC_BUILD_ROOT_ENV];
  if (!requested) return normal;
  if (environment[LIFECYCLE_BUILD_ENV] !== "1") {
    throw new Error(`${STATIC_BUILD_ROOT_ENV} is restricted to explicit lifecycle builds.`);
  }
  const lifecycleRootValue = environment[LIFECYCLE_ROOT_ENV];
  if (!lifecycleRootValue || !isAbsolute(lifecycleRootValue) || !isAbsolute(requested)) {
    throw new Error("Lifecycle build roots must be explicit absolute paths.");
  }
  const lifecycleRoot = validateOwnedLifecycleRoot({
    root: lifecycleRootValue,
    token: environment[LIFECYCLE_ROOT_TOKEN_ENV],
  });
  const lexicalRoot = resolve(lifecycleRootValue);
  const lexicalTarget = resolve(requested);
  if (!inside(lexicalRoot, lexicalTarget)) {
    throw new Error("Lifecycle build output must remain inside its temporary root.");
  }
  const target = resolve(lifecycleRoot, relative(lexicalRoot, lexicalTarget));
  assertExistingPathHasNoSymlinks(lifecycleRoot, target);
  return target;
}
