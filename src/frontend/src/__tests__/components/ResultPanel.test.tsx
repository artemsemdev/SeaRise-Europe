import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ResultPanel from "@/app/components/assessment/ResultPanel";
import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { strings } from "@/lib/i18n/en";
import type { AssessmentResult, ResultState } from "@/lib/types";

function createMockResult(resultState: ResultState): AssessmentResult {
  return {
    requestId: "req_test",
    resultState,
    location: { latitude: 52.37, longitude: 4.9 },
    scenario: { id: "ssp2-45", displayName: "Intermediate emissions (SSP2-4.5)" },
    horizon: { year: 2050, displayLabel: "2050" },
    methodologyVersion: "v1.0",
    layerTileUrlTemplate: resultState === "ModeledExposureDetected" ? "https://tiler.example.com/{z}/{x}/{y}" : null,
    legendSpec: resultState === "ModeledExposureDetected" ? { colorStops: [{ value: 1, color: "#E85D04", label: "Modeled exposure zone" }] } : null,
    generatedAt: "2026-04-03T12:00:00Z",
  };
}

function renderResultPanel(resultState: ResultState) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ResultPanel
        result={createMockResult(resultState)}
        locationLabel="Amsterdam, Netherlands"
      />
    </QueryClientProvider>
  );
}

describe("ResultPanel", () => {
  beforeEach(() => {
    useAppStore.getState().reset();
    useMapStore.getState().setSelectedLocation(null);
  });

  it("renders ModeledExposureDetected with correct headline and summary", () => {
    renderResultPanel("ModeledExposureDetected");
    expect(screen.getByText(strings.resultStates.ModeledExposureDetected)).toBeInTheDocument();
    expect(screen.getByText(/shows modeled coastal exposure/)).toBeInTheDocument();
    expect(screen.getByText(strings.disclaimer)).toBeInTheDocument();
  });

  it("renders NoModeledExposureDetected with safety caveat", () => {
    renderResultPanel("NoModeledExposureDetected");
    expect(screen.getByText(strings.resultStates.NoModeledExposureDetected)).toBeInTheDocument();
    expect(screen.getByText(/does not constitute a safety determination/)).toBeInTheDocument();
    expect(screen.getByText(strings.disclaimer)).toBeInTheDocument();
  });

  it("renders DataUnavailable with no-substitution message", () => {
    renderResultPanel("DataUnavailable");
    expect(screen.getByText(strings.resultStates.DataUnavailable)).toBeInTheDocument();
    expect(screen.getByText(/No substitution has been made/)).toBeInTheDocument();
    expect(screen.getByText(strings.disclaimer)).toBeInTheDocument();
  });

  it("renders OutOfScope with center card layout", () => {
    renderResultPanel("OutOfScope");
    expect(screen.getByText(strings.resultStates.OutOfScope)).toBeInTheDocument();
    expect(screen.getByText(/outside the coastal analysis zone/)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.searchAnother)).toBeInTheDocument();
  });

  it("renders UnsupportedGeography with center card layout", () => {
    renderResultPanel("UnsupportedGeography");
    expect(screen.getByText(strings.resultStates.UnsupportedGeography)).toBeInTheDocument();
    expect(screen.getByText(/outside the area currently supported/)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.searchAnother)).toBeInTheDocument();
  });

  it("shows methodology entry point button", () => {
    renderResultPanel("ModeledExposureDetected");
    expect(screen.getByText(strings.actions.methodology)).toBeInTheDocument();
  });

  it("shows new search button", () => {
    renderResultPanel("ModeledExposureDetected");
    expect(screen.getByText(strings.actions.newSearch)).toBeInTheDocument();
  });

  it("renders metadata rows", () => {
    renderResultPanel("ModeledExposureDetected");
    expect(screen.getByText("Forecast model")).toBeInTheDocument();
    expect(screen.getByText("Time horizon")).toBeInTheDocument();
    expect(screen.getByText("Methodology")).toBeInTheDocument();
  });
});
