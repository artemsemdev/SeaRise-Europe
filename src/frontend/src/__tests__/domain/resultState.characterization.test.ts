import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { buildAssessmentSample } from "@/__tests__/builders/resultStateBuilder";
import {
  determineResultState,
  type AssessmentSample,
} from "@/lib/domain/resultState";
import type { ResultState } from "@/lib/types";

interface FixtureCase {
  id: string;
  input: AssessmentSample;
  expectedState: ResultState;
}

const fixture = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../../tests/fixtures/tdd/five-state-characterization-v1.json"),
    "utf8",
  ),
) as { cases: FixtureCase[] };

describe("shared five-state browser characterization", () => {
  it.each(fixture.cases)("maps $id from the shared fixture", ({ input, expectedState }) => {
    expect(determineResultState(buildAssessmentSample(input))).toBe(expectedState);
  });

  it.each([false, true, null] as const)(
    "keeps outside-Europe precedence for coastal=%s",
    (inCoastalZone) => {
      expect(
        determineResultState(
          buildAssessmentSample({ inEurope: false, inCoastalZone, classValue: 1 }),
        ),
      ).toBe("UnsupportedGeography");
    },
  );

  it.each([0, 1, null] as const)(
    "never reports exposure outside the coastal zone for class=%s",
    (classValue) => {
      expect(
        determineResultState(buildAssessmentSample({ inCoastalZone: false, classValue })),
      ).toBe("OutOfScope");
    },
  );
});
