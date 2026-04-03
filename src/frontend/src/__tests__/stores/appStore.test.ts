import { describe, it, expect, beforeEach } from "vitest";
import { useAppStore } from "@/lib/store/appStore";

const mockCandidate = {
  rank: 1,
  label: "Amsterdam, Netherlands",
  country: "NL",
  latitude: 52.3676,
  longitude: 4.9041,
  displayContext: "North Holland, Netherlands",
};

const mockLocation = {
  label: "Amsterdam, Netherlands",
  latitude: 52.3676,
  longitude: 4.9041,
};

const mockResult = {
  requestId: "req_123",
  resultState: "ModeledExposureDetected" as const,
  location: { latitude: 52.3676, longitude: 4.9041 },
  scenario: { id: "ssp2-45", displayName: "Intermediate emissions (SSP2-4.5)" },
  horizon: { year: 2050, displayLabel: "2050" },
  methodologyVersion: "v1.0",
  layerTileUrlTemplate: "https://tiler.example.com/cog/tiles/{z}/{x}/{y}.png",
  legendSpec: { colorStops: [{ value: 1, color: "#E85D04", label: "Modeled exposure zone" }] },
  generatedAt: "2026-03-30T12:00:00Z",
};

describe("appStore", () => {
  beforeEach(() => {
    useAppStore.getState().reset();
  });

  it("initializes with idle phase", () => {
    expect(useAppStore.getState().appPhase).toEqual({ phase: "idle" });
  });

  it("transitions to geocoding", () => {
    useAppStore.getState().startGeocoding("Amsterdam");
    expect(useAppStore.getState().appPhase).toEqual({
      phase: "geocoding",
      query: "Amsterdam",
    });
  });

  it("transitions to geocoding_error", () => {
    useAppStore.getState().startGeocoding("test");
    useAppStore
      .getState()
      .setGeocodingError({ code: "PROVIDER_ERROR", message: "Failed" }, "test");
    const phase = useAppStore.getState().appPhase;
    expect(phase.phase).toBe("geocoding_error");
    if (phase.phase === "geocoding_error") {
      expect(phase.error.code).toBe("PROVIDER_ERROR");
      expect(phase.lastQuery).toBe("test");
    }
  });

  it("transitions to no_geocoding_results", () => {
    useAppStore.getState().startGeocoding("xyz");
    useAppStore.getState().setNoResults("xyz");
    const phase = useAppStore.getState().appPhase;
    expect(phase.phase).toBe("no_geocoding_results");
    if (phase.phase === "no_geocoding_results") {
      expect(phase.query).toBe("xyz");
    }
  });

  it("transitions to candidate_selection", () => {
    useAppStore.getState().startGeocoding("Amsterdam");
    useAppStore.getState().setCandidates([mockCandidate]);
    const phase = useAppStore.getState().appPhase;
    expect(phase.phase).toBe("candidate_selection");
    if (phase.phase === "candidate_selection") {
      expect(phase.candidates).toHaveLength(1);
      expect(phase.candidates[0].label).toBe("Amsterdam, Netherlands");
    }
  });

  it("transitions to assessing", () => {
    useAppStore.getState().startAssessing(mockLocation);
    expect(useAppStore.getState().appPhase).toEqual({
      phase: "assessing",
      location: mockLocation,
    });
  });

  it("transitions to result", () => {
    useAppStore.getState().startAssessing(mockLocation);
    useAppStore.getState().setResult(mockLocation, mockResult);
    const phase = useAppStore.getState().appPhase;
    expect(phase.phase).toBe("result");
    if (phase.phase === "result") {
      expect(phase.result.resultState).toBe("ModeledExposureDetected");
    }
  });

  it("transitions to result_updating", () => {
    useAppStore.getState().setResult(mockLocation, mockResult);
    useAppStore.getState().setResultUpdating(mockLocation, mockResult);
    expect(useAppStore.getState().appPhase.phase).toBe("result_updating");
  });

  it("transitions to assessment_error", () => {
    useAppStore.getState().startAssessing(mockLocation);
    useAppStore
      .getState()
      .setAssessmentError(mockLocation, { code: "FAIL", message: "Err" });
    const phase = useAppStore.getState().appPhase;
    expect(phase.phase).toBe("assessment_error");
    if (phase.phase === "assessment_error") {
      expect(phase.location).toEqual(mockLocation);
    }
  });

  describe("reset() from every phase", () => {
    const phases = [
      () => useAppStore.getState().startGeocoding("test"),
      () =>
        useAppStore
          .getState()
          .setGeocodingError({ code: "ERR", message: "err" }, "test"),
      () => useAppStore.getState().setNoResults("test"),
      () => useAppStore.getState().setCandidates([mockCandidate]),
      () => useAppStore.getState().startAssessing(mockLocation),
      () => useAppStore.getState().setResult(mockLocation, mockResult),
      () => useAppStore.getState().setResultUpdating(mockLocation, mockResult),
      () =>
        useAppStore
          .getState()
          .setAssessmentError(mockLocation, { code: "ERR", message: "err" }),
    ];

    phases.forEach((setup, i) => {
      it(`resets from phase variant ${i}`, () => {
        setup();
        expect(useAppStore.getState().appPhase.phase).not.toBe("idle");
        useAppStore.getState().reset();
        expect(useAppStore.getState().appPhase).toEqual({ phase: "idle" });
      });
    });
  });
});
