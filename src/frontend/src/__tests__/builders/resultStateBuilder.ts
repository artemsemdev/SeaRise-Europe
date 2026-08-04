import type { AssessmentSample } from "@/lib/domain/resultState";

export function buildAssessmentSample(
  overrides: Partial<AssessmentSample> = {},
): AssessmentSample {
  return {
    inEurope: true,
    inCoastalZone: true,
    classValue: 0,
    ...overrides,
  };
}
