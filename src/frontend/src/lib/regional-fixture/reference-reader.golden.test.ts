// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { RegionalFixture } from "./reference-reader";

interface GoldenVector {
  id: string;
  longitude: number;
  latitude: number;
  scenario: string;
  horizon: number;
  expectedState: string;
  expectedCell: { row: number; column: number } | null;
}

const fixtureDirectory = resolve(process.cwd(), "../pipeline/fixtures/regional");

function readJson(name: string): unknown {
  return JSON.parse(readFileSync(resolve(fixtureDirectory, name), "utf8"));
}

describe("real-source regional golden parity", () => {
  it("matches every shared Python/TypeScript vector bit-exactly", async () => {
    const fixture = await RegionalFixture.parse(readJson("lookup-fixture.json"));
    const golden = readJson("golden-vectors.json") as {
      classificationStatus: string;
      review: { status: string };
      vectors: GoldenVector[];
    };

    expect(golden.classificationStatus).toBe("blocked");
    expect(golden.review.status).toBe("pending");
    expect(golden.vectors).toHaveLength(11);

    for (const vector of golden.vectors) {
      const result = fixture.lookup(
        vector.longitude,
        vector.latitude,
        vector.scenario,
        vector.horizon,
      );
      expect(result.state, vector.id).toBe(vector.expectedState);
      expect(result.cell, vector.id).toEqual(vector.expectedCell);
    }
  });
});
