import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

export const STATIC_BUILD_ROOT_ENV = "SEARISE_WEB_DIST_ROOT";
export const LIFECYCLE_BUILD_ENV = "SEARISE_LIFECYCLE_BUILD";
export const LIFECYCLE_ROOT_ENV = "SEARISE_LIFECYCLE_ROOT";

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
  const lexicalRoot = resolve(lifecycleRootValue);
  const lexicalTarget = resolve(requested);
  if (!inside(lexicalRoot, lexicalTarget)) {
    throw new Error("Lifecycle build output must remain inside its temporary root.");
  }
  const lifecycleRoot = realpathSync(lexicalRoot);
  const target = resolve(lifecycleRoot, relative(lexicalRoot, lexicalTarget));
  assertExistingPathHasNoSymlinks(lifecycleRoot, target);
  return target;
}
