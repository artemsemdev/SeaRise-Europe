import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
        locationContext="North Holland"
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
    expect(screen.getByText(/not a safety determination/)).toBeInTheDocument();
    expect(screen.getByText(strings.disclaimerNoExposure)).toBeInTheDocument();
  });

  it("renders DataUnavailable with suggestion buttons", () => {
    renderResultPanel("DataUnavailable");
    expect(screen.getByText(strings.resultStates.DataUnavailable)).toBeInTheDocument();
    expect(screen.getByText(/Try a different model or timeframe/)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.tryNextHorizon)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.tryIpccModel)).toBeInTheDocument();
  });

  it("renders OutOfScope with city-specific heading and center card layout", () => {
    renderResultPanel("OutOfScope");
    expect(screen.getByText("Amsterdam is not on the coast")).toBeInTheDocument();
    expect(screen.getByText(/too far inland/)).toBeInTheDocument();
    expect(screen.getByText(strings.resultSummaries.OutOfScopeSuggestion)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.searchAnother)).toBeInTheDocument();
  });

  it("renders UnsupportedGeography with city-specific heading, two buttons", () => {
    renderResultPanel("UnsupportedGeography");
    expect(screen.getByText("Amsterdam is outside Europe")).toBeInTheDocument();
    expect(screen.getByText(/European coastlines/)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.newSearch)).toBeInTheDocument();
    expect(screen.getByText(strings.actions.reset)).toBeInTheDocument();
  });

  it("shows source citation", () => {
    renderResultPanel("ModeledExposureDetected");
    expect(screen.getByText(strings.source)).toBeInTheDocument();
  });

  it("shows loc-sub with temporal format", () => {
    renderResultPanel("ModeledExposureDetected");
    // Should contain "years (year 2050)"
    expect(screen.getByText(/years \(year 2050\)/)).toBeInTheDocument();
  });

  it("renders metadata rows for exposure result", () => {
    renderResultPanel("ModeledExposureDetected");
    expect(screen.getByText("Forecast model")).toBeInTheDocument();
    expect(screen.getByText("Timeframe")).toBeInTheDocument();
  });
});
