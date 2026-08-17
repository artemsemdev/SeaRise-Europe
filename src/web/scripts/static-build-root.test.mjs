// @vitest-environment node

import { mkdtempSync, mkdirSync, realpathSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { resolveStaticBuildRoot } from "./static-build-root.mjs";

const roots = [];

function temporaryRoot() {
  const root = mkdtempSync(join(tmpdir(), "searise-build-root-test-"));
  roots.push(root);
  return root;
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
    const root = temporaryRoot();
    const target = join(root, "deployment-a");
    expect(resolveStaticBuildRoot({
      webRoot: "/workspace/web",
      environment: {
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: root,
        SEARISE_WEB_DIST_ROOT: target,
      },
    })).toBe(join(realpathSync(root), "deployment-a"));
  });

  it.each([
    ["missing mode", (root) => ({ SEARISE_LIFECYCLE_ROOT: root, SEARISE_WEB_DIST_ROOT: join(root, "a") })],
    ["relative target", (root) => ({ SEARISE_LIFECYCLE_BUILD: "1", SEARISE_LIFECYCLE_ROOT: root, SEARISE_WEB_DIST_ROOT: "a" })],
    ["root itself", (root) => ({ SEARISE_LIFECYCLE_BUILD: "1", SEARISE_LIFECYCLE_ROOT: root, SEARISE_WEB_DIST_ROOT: root })],
    ["outside root", (root) => ({ SEARISE_LIFECYCLE_BUILD: "1", SEARISE_LIFECYCLE_ROOT: root, SEARISE_WEB_DIST_ROOT: resolve(root, "../escape") })],
  ])("rejects %s", (_name, environment) => {
    const root = temporaryRoot();
    expect(() => resolveStaticBuildRoot({ webRoot: "/workspace/web", environment: environment(root) }))
      .toThrow();
  });

  it("rejects an existing symlink below the lifecycle root", () => {
    const root = temporaryRoot();
    const outside = temporaryRoot();
    mkdirSync(join(root, "deployments"));
    symlinkSync(outside, join(root, "deployments/link"));
    expect(() => resolveStaticBuildRoot({
      webRoot: "/workspace/web",
      environment: {
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: root,
        SEARISE_WEB_DIST_ROOT: join(root, "deployments/link/a"),
      },
    })).toThrow(/symbolic link/);
  });
});
