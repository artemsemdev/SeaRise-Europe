import { describe, expect, it } from "vitest";
import { RESULT_STATES } from "../contracts/generated/release-contract";
import {
  TECHNICAL_ERROR_CODES,
  technicalErrorPresentation,
  type GeographyClassification,
} from "./release";

describe("release domain vocabulary", () => {
  it("contains exactly the four ADR-024 completed outcomes", () => {
    expect(RESULT_STATES).toEqual([
      "ProjectionAvailable",
      "DataUnavailable",
      "OutOfScope",
      "UnsupportedGeography",
    ]);
    expect(RESULT_STATES).not.toContain("TechnicalError");
  });

  it("maps every technical category to user-safe presentation outside the outcomes", () => {
    expect(TECHNICAL_ERROR_CODES).toHaveLength(8);
    for (const code of TECHNICAL_ERROR_CODES) {
      const presentation = technicalErrorPresentation({
        kind: "technical-error",
        code,
        message: "safe detail",
        recoverable: false,
      });
      expect(presentation.title).not.toBe("");
      expect(presentation.guidance).not.toBe("");
      expect(RESULT_STATES).not.toContain(code);
    }
  });

  it("keeps geography classification exhaustive and independent", () => {
    const values: readonly GeographyClassification[] = [
      "OutsideEurope",
      "InEuropeOutsideCoastalZone",
      "InEuropeAndCoastalZone",
    ];
    expect(values).toHaveLength(3);
  });
});
