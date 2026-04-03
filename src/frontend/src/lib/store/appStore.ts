import { create } from "zustand";
import type {
  GeocodingCandidate,
  SelectedLocation,
  AssessmentResult,
  GeocodingError,
  AssessmentError,
} from "@/lib/types";

export type AppPhase =
  | { phase: "idle" }
  | { phase: "geocoding"; query: string }
  | { phase: "geocoding_error"; error: GeocodingError; lastQuery: string }
  | { phase: "no_geocoding_results"; query: string }
  | { phase: "candidate_selection"; candidates: GeocodingCandidate[] }
  | { phase: "assessing"; location: SelectedLocation }
  | {
      phase: "result";
      location: SelectedLocation;
      result: AssessmentResult;
    }
  | {
      phase: "result_updating";
      location: SelectedLocation;
      previousResult: AssessmentResult;
    }
  | {
      phase: "assessment_error";
      location: SelectedLocation;
      error: AssessmentError;
    };

interface AssessmentParams {
  scenarioId: string;
  horizonYear: number;
}

interface AppStore {
  appPhase: AppPhase;
  assessmentParams: AssessmentParams | null;
  startGeocoding: (query: string) => void;
  setGeocodingError: (error: GeocodingError, lastQuery: string) => void;
  setNoResults: (query: string) => void;
  setCandidates: (candidates: GeocodingCandidate[]) => void;
  startAssessing: (location: SelectedLocation) => void;
  setResult: (location: SelectedLocation, result: AssessmentResult) => void;
  setResultUpdating: (
    location: SelectedLocation,
    previousResult: AssessmentResult
  ) => void;
  setAssessmentError: (
    location: SelectedLocation,
    error: AssessmentError
  ) => void;
  setAssessmentParams: (params: AssessmentParams) => void;
  reset: () => void;
}

const initialPhase: AppPhase = { phase: "idle" };

export const useAppStore = create<AppStore>((set) => ({
  appPhase: initialPhase,
  assessmentParams: null,

  startGeocoding: (query) => set({ appPhase: { phase: "geocoding", query } }),

  setGeocodingError: (error, lastQuery) =>
    set({ appPhase: { phase: "geocoding_error", error, lastQuery } }),

  setNoResults: (query) =>
    set({ appPhase: { phase: "no_geocoding_results", query } }),

  setCandidates: (candidates) =>
    set({ appPhase: { phase: "candidate_selection", candidates } }),

  startAssessing: (location) =>
    set({ appPhase: { phase: "assessing", location } }),

  setResult: (location, result) =>
    set({ appPhase: { phase: "result", location, result } }),

  setResultUpdating: (location, previousResult) =>
    set({
      appPhase: { phase: "result_updating", location, previousResult },
    }),

  setAssessmentError: (location, error) =>
    set({ appPhase: { phase: "assessment_error", location, error } }),

  setAssessmentParams: (params) => set({ assessmentParams: params }),

  reset: () => set({ appPhase: initialPhase, assessmentParams: null }),
}));

export const useAppPhase = () => useAppStore((s) => s.appPhase);
export const useAssessmentParams = () =>
  useAppStore((s) => s.assessmentParams);
