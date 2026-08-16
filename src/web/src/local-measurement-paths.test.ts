// @vitest-environment node

import { mkdtempSync, mkdirSync, realpathSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { assertPrivateMeasurementOutput } from "../scripts/local-measurement-paths.mjs";

function privateTrees() {
  const root = mkdtempSync(resolve(tmpdir(), "searise-private-output-"));
  const candidateRoot = resolve(root, "candidate");
  const distRoot = resolve(root, "dist");
  const reports = resolve(root, "reports");
  mkdirSync(candidateRoot);
  mkdirSync(distRoot);
  mkdirSync(reports);
  return { root, candidateRoot, distRoot, reports };
}

describe("local Candidate measurement output isolation", () => {
  it("accepts a new canonical path outside Candidate, deployable, and Git trees", () => {
    const trees = privateTrees();
    expect(assertPrivateMeasurementOutput({
      outputPath: resolve(trees.reports, "measurement.json"),
      candidateRoot: trees.candidateRoot,
      distRoot: trees.distRoot,
    })).toBe(resolve(realpathSync(trees.reports), "measurement.json"));
  });

  it.each(["candidateRoot", "distRoot"] as const)("rejects output inside %s", (name) => {
    const trees = privateTrees();
    expect(() => assertPrivateMeasurementOutput({
      outputPath: resolve(trees[name], "measurement.json"),
      candidateRoot: trees.candidateRoot,
      distRoot: trees.distRoot,
    })).toThrow(/outside Candidate and deployable trees/);
  });

  it("rejects canonical aliases into a Git worktree", () => {
    const trees = privateTrees();
    const alias = resolve(trees.root, "worktree-alias");
    symlinkSync(process.cwd(), alias);
    expect(() => assertPrivateMeasurementOutput({
      outputPath: resolve(alias, "measurement.json"),
      candidateRoot: trees.candidateRoot,
      distRoot: trees.distRoot,
    })).toThrow(/outside every Git worktree/);
  });
});
