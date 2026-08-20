// @vitest-environment node

import { mkdirSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createOwnedLifecycleRoot, resolveStaticBuildRoot } from "./static-build-root.mjs";

const roots = [];

function temporaryRoot() {
  const owned = createOwnedLifecycleRoot();
  roots.push(owned.root);
  return owned;
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true });
});

describe("static build output root", () => {
  it("uses dist for every normal production build", () => {
    expect(resolveStaticBuildRoot({ webRoot: "/workspace/web", environment: {} }))
      .toBe(resolve("/workspace/web/dist"));
  });

  it("accepts only an explicit child of a real lifecycle root", () => {
    const owned = temporaryRoot();
    const target = join(owned.root, "deployment-a");
    expect(resolveStaticBuildRoot({
      webRoot: "/workspace/web",
      environment: {
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: owned.root,
        SEARISE_LIFECYCLE_ROOT_TOKEN: owned.token,
        SEARISE_WEB_DIST_ROOT: target,
      },
    })).toBe(target);
  });

  it.each([
    ["missing mode", ({ root, token }) => ({ SEARISE_LIFECYCLE_ROOT: root, SEARISE_LIFECYCLE_ROOT_TOKEN: token, SEARISE_WEB_DIST_ROOT: join(root, "a") })],
    ["relative target", ({ root, token }) => ({ SEARISE_LIFECYCLE_BUILD: "1", SEARISE_LIFECYCLE_ROOT: root, SEARISE_LIFECYCLE_ROOT_TOKEN: token, SEARISE_WEB_DIST_ROOT: "a" })],
    ["root itself", ({ root, token }) => ({ SEARISE_LIFECYCLE_BUILD: "1", SEARISE_LIFECYCLE_ROOT: root, SEARISE_LIFECYCLE_ROOT_TOKEN: token, SEARISE_WEB_DIST_ROOT: root })],
    ["outside root", ({ root, token }) => ({ SEARISE_LIFECYCLE_BUILD: "1", SEARISE_LIFECYCLE_ROOT: root, SEARISE_LIFECYCLE_ROOT_TOKEN: token, SEARISE_WEB_DIST_ROOT: resolve(root, "../escape") })],
  ])("rejects %s", (_name, environment) => {
    const owned = temporaryRoot();
    expect(() => resolveStaticBuildRoot({ webRoot: "/workspace/web", environment: environment(owned) }))
      .toThrow();
  });

  it("rejects an existing symlink below the lifecycle root", () => {
    const owned = temporaryRoot();
    const outside = temporaryRoot();
    mkdirSync(join(owned.root, "deployments"));
    symlinkSync(outside.root, join(owned.root, "deployments/link"));
    expect(() => resolveStaticBuildRoot({
      webRoot: "/workspace/web",
      environment: {
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: owned.root,
        SEARISE_LIFECYCLE_ROOT_TOKEN: owned.token,
        SEARISE_WEB_DIST_ROOT: join(owned.root, "deployments/link/a"),
      },
    })).toThrow(/symbolic link/);
  });

  it("rejects a durable or aliased root even when the caller supplies a token", () => {
    expect(() => resolveStaticBuildRoot({
      webRoot: process.cwd(),
      environment: {
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: process.cwd(),
        SEARISE_LIFECYCLE_ROOT_TOKEN: "a".repeat(64),
        SEARISE_WEB_DIST_ROOT: join(process.cwd(), "destructive-output"),
      },
    })).toThrow(/OS temporary|owner marker/);

    const owned = temporaryRoot();
    const alias = join(tmpdir(), `searise-offline-lifecycle-alias-${Date.now()}`);
    roots.push(alias);
    symlinkSync(owned.root, alias);
    expect(() => resolveStaticBuildRoot({
      webRoot: process.cwd(),
      environment: {
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: alias,
        SEARISE_LIFECYCLE_ROOT_TOKEN: owned.token,
        SEARISE_WEB_DIST_ROOT: join(alias, "A"),
      },
    })).toThrow(/canonical owned OS temporary/);
  });
});
