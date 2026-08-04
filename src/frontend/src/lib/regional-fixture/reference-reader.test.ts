// @vitest-environment node

import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import {
  FixtureContractError,
  RegionalFixture,
} from "./reference-reader";

function encoded(values: number[]) {
  const bytes = Uint8Array.from(values);
  return {
    encoding: "base64-uint8-row-major",
    data: Buffer.from(bytes).toString("base64"),
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

function document(blocked = false) {
  const layer = blocked
    ? { status: "blocked", blockedBy: ["vertical-datum-reconciliation"] }
    : { status: "ready", values: encoded([1, 0, 0, 255, 0, 0]) };
  return {
    schemaVersion: 1,
    fixtureId: "contract-test-only",
    grid: {
      width: 3,
      height: 2,
      west: 4,
      south: 52,
      east: 5,
      north: 53,
      longitude_convention: "minus-180-to-180",
      edge_rule: "west-north-inclusive-east-south-exclusive",
    },
    supportMask: encoded([1, 1, 1, 1, 1, 0]),
    coastalMask: encoded([1, 1, 0, 1, 1, 0]),
    layers: { "ssp2-45/2050": layer },
  };
}

describe("regional fixture reference reader", () => {
  it("distinguishes all five domain states", async () => {
    const fixture = await RegionalFixture.parse(document());

    expect(fixture.lookup(4.1, 52.9, "ssp2-45", 2050).state).toBe(
      "modeled-exposure-detected",
    );
    expect(fixture.lookup(4.4, 52.9, "ssp2-45", 2050).state).toBe(
      "no-modeled-exposure-detected",
    );
    expect(fixture.lookup(4.1, 52.4, "ssp2-45", 2050).state).toBe("data-unavailable");
    expect(fixture.lookup(4.8, 52.9, "ssp2-45", 2050).state).toBe("out-of-scope");
    expect(fixture.lookup(4.8, 52.4, "ssp2-45", 2050).state).toBe(
      "unsupported-geography",
    );
  });

  it("uses west/north-inclusive and east/south-exclusive edges", async () => {
    const fixture = await RegionalFixture.parse(document());

    expect(fixture.cell(4, 53)).toEqual({ row: 0, column: 0 });
    expect(fixture.cell(5, 53)).toBeNull();
    expect(fixture.cell(4, 52)).toBeNull();
  });

  it("fails a blocked layer closed", async () => {
    const fixture = await RegionalFixture.parse(document(true));
    expect(fixture.lookup(4.1, 52.9, "ssp2-45", 2050).state).toBe("data-unavailable");
  });

  it("rejects a tampered array checksum", async () => {
    const raw = document();
    raw.coastalMask.sha256 = "0".repeat(64);
    await expect(RegionalFixture.parse(raw)).rejects.toThrow("SHA-256 mismatch");
  });

  it("rejects a longitude outside the declared convention", async () => {
    const fixture = await RegionalFixture.parse(document());
    expect(() => fixture.lookup(364.1, 52.9, "ssp2-45", 2050)).toThrow(
      FixtureContractError,
    );
  });
});
