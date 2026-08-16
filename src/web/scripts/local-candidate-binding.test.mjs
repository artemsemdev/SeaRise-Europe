// @vitest-environment node

import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  allowlistedRecord,
  forbiddenLocalFilesystemRequest,
  overlayIdentity,
  removePrivateOverlay,
  verifiedPinnedBytes,
} from "./local-candidate-binding.mjs";

describe("private Candidate local file isolation", () => {
  it("rejects a same-size in-place content mutation", () => {
    const root = mkdtempSync(join(tmpdir(), "searise-pinned-file-test-"));
    const path = join(root, "source-grid.bin");
    try {
      writeFileSync(path, "reviewed");
      const record = allowlistedRecord(
        path,
        {
          path: "analysis/source-grid.json.gz",
          byteSize: 8,
          sha256: "e4f934f321eb76c9bf8b5103e0a0d9afe72d6e62ace3d3ea849790619bf7487a",
        },
        "test",
      );
      writeFileSync(path, "mutated!");
      expect(() => verifiedPinnedBytes(record)).toThrow("content changed");
    } finally {
      rmSync(root, { recursive: true });
    }
  });

  it("refuses recursive cleanup after the overlay directory identity is replaced", () => {
    const root = mkdtempSync(join(tmpdir(), "searise-private-binding-"));
    chmodSync(root, 0o700);
    const identity = overlayIdentity(root);
    rmSync(root, { recursive: true });
    mkdirSync(root, { mode: 0o700 });
    const sentinel = join(root, "do-not-delete.txt");
    writeFileSync(sentinel, "replacement");
    try {
      expect(() => removePrivateOverlay(identity)).toThrow("replaced private overlay");
      expect(existsSync(sentinel)).toBe(true);
    } finally {
      rmSync(root, { recursive: true });
    }
  });

  it("denies filesystem routes, encoded traversal, and exact local input paths", () => {
    const binding = {
      candidateRoot: "/private/local-data/candidate-v7",
      initialSourceGrid: { path: "/private/local-data/source-grid.json.gz" },
    };
    for (const path of [
      "/@fs//private/local-data/candidate-v7/manifest.json",
      "/%40fs/%2Fprivate%2Flocal-data%2Fsource-grid.json.gz",
      "/@fs/%252e%252e/%2Fprivate%2Flocal-data%2Fcandidate-v7%2Fmanifest.json",
      "/private/local-data/candidate-v7/manifest.json",
      "/private/local-data/source-grid.json.gz",
    ]) {
      expect(forbiddenLocalFilesystemRequest(binding, path), path).toBe(true);
    }
    expect(forbiddenLocalFilesystemRequest(binding, "/about/architecture/")).toBe(false);
  });
});
