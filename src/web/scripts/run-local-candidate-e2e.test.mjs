// @vitest-environment node

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  privateOverlayInventory,
  withOwnedPrivateCandidate,
} from "./run-local-candidate-e2e.mjs";

function temporaryServer() {
  const overlay = mkdtempSync(join(tmpdir(), "searise-private-binding-"));
  return {
    overlay,
    async close() {
      rmSync(overlay, { recursive: true });
    },
  };
}

describe("owned private Candidate lifecycle", () => {
  it("leaves no new overlay after a successful task", async () => {
    const before = privateOverlayInventory();
    await expect(
      withOwnedPrivateCandidate({
        serve: async () => temporaryServer(),
        run: async () => "passed",
      }),
    ).resolves.toBe("passed");
    expect(privateOverlayInventory()).toEqual(before);
  });

  it("awaits cleanup and leaves no new overlay after a failed task", async () => {
    const before = privateOverlayInventory();
    await expect(
      withOwnedPrivateCandidate({
        serve: async () => temporaryServer(),
        run: async () => {
          throw new Error("deliberate child failure");
        },
      }),
    ).rejects.toThrow("deliberate child failure");
    expect(privateOverlayInventory()).toEqual(before);
  });
});
