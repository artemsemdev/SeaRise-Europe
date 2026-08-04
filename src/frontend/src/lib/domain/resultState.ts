import type { ResultState } from "@/lib/types";

export interface AssessmentSample {
  inEurope: boolean;
  inCoastalZone: boolean | null;
  classValue: 0 | 1 | null;
}

/** Determine a public state from static support, coastal, and exact class evidence. */
export function determineResultState(sample: AssessmentSample): ResultState {
  if (!sample.inEurope) {
    return "UnsupportedGeography";
  }
  if (sample.inCoastalZone === false) {
    return "OutOfScope";
  }
  if (sample.inCoastalZone !== true) {
    return "DataUnavailable";
  }

  return stateForClass(sample.classValue);
}

function stateForClass(classValue: AssessmentSample["classValue"]): ResultState {
  switch (classValue) {
    case null:
      return "DataUnavailable";
    case 1:
      return "ModeledExposureDetected";
    case 0:
      return "NoModeledExposureDetected";
  }
}
