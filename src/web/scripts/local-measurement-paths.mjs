import { execFileSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";

function contains(root, target) {
  const path = relative(root, target);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

function gitWorktree(path) {
  try {
    const root = execFileSync("git", ["-C", path, "rev-parse", "--show-toplevel"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return root ? realpathSync(root) : null;
  } catch {
    return null;
  }
}

export function assertPrivateMeasurementOutput({ outputPath, candidateRoot, distRoot }) {
  if (existsSync(outputPath)) {
    throw new Error("Local measurement output already exists; choose a new private path.");
  }
  const outputParent = realpathSync(dirname(outputPath));
  const canonicalOutput = resolve(outputParent, basename(outputPath));
  const forbiddenRoots = [realpathSync(candidateRoot), realpathSync(distRoot)];
  if (forbiddenRoots.some((root) => contains(root, canonicalOutput))) {
    throw new Error("Local measurement output must remain outside Candidate and deployable trees.");
  }
  const worktree = gitWorktree(outputParent);
  if (worktree && contains(worktree, canonicalOutput)) {
    throw new Error("Local measurement output must remain outside every Git worktree.");
  }
  return canonicalOutput;
}
