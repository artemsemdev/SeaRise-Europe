"use client";

import type { AssessmentResult, ResultState, ScenarioConfig, HorizonConfig } from "@/lib/types";
import { strings } from "@/lib/i18n/en";
import { useUiStore } from "@/lib/store/uiStore";
import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";

interface ResultPanelProps {
  result: AssessmentResult;
  locationLabel: string;
  locationContext: string;
  scenarios?: ScenarioConfig[];
  horizons?: HorizonConfig[];
  activeScenarioId?: string;
  activeHorizonYear?: number;
  onScenarioChange?: (scenarioId: string) => void;
  onHorizonChange?: (year: number) => void;
}

const CURRENT_YEAR = new Date().getFullYear();

function BadgeIcon({ resultState }: { resultState: ResultState }) {
  if (resultState === "ModeledExposureDetected") {
    return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
        <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z" />
      </svg>
    );
  }
  if (resultState === "NoModeledExposureDetected") {
    return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  );
}

function getBadgeStyle(resultState: ResultState): { background: string; color: string } {
  switch (resultState) {
    case "ModeledExposureDetected":
      return { background: "var(--w-bg)", color: "var(--warn)" };
    case "NoModeledExposureDetected":
      return { background: "var(--ok-bg)", color: "var(--ok)" };
    default:
      return { background: "var(--p-bg)", color: "var(--primary)" };
  }
}

function getCityName(label: string): string {
  // Extract city name from "City, Country" format
  return label.split(",")[0].trim();
}

export default function ResultPanel({
  result,
  locationLabel,
  locationContext,
  scenarios,
  horizons,
  activeScenarioId,
  activeHorizonYear,
  onScenarioChange,
  onHorizonChange,
}: ResultPanelProps) {
  const reset = useAppStore((s) => s.reset);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);

  const handleReset = () => {
    setSelectedLocation(null);
    reset();
  };

  const { resultState } = result;
  const badgeStyle = getBadgeStyle(resultState);
  const cityName = getCityName(locationLabel);

  // --- OutOfScope: center card (mock 09) ---
  if (resultState === "OutOfScope") {
    return (
      <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
        <div
          className="pointer-events-auto relative flex max-w-[400px] flex-col items-center gap-4 rounded-[var(--r-lg)] text-center"
          style={{ background: "var(--s-low)", padding: "2.5rem 2rem" }}
        >
          {/* Icon */}
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: "var(--s-high)" }}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--text)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="m8 3 4 8 5-5 2 14H2L8 3z" />
              <path d="M4.14 15.08c2.62-1.57 5.24-1.43 7.86.42 2.74 1.94 5.49 2 8.23.19" />
            </svg>
          </div>

          <h2
            className="text-[1.3rem] font-bold"
            style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
          >
            {strings.resultStates.OutOfScope(cityName)}
          </h2>

          <p className="text-[0.85rem] leading-relaxed" style={{ color: "var(--text2)" }}>
            {strings.resultSummaries.OutOfScope(cityName)}
          </p>

          <p className="text-[0.8rem] leading-relaxed" style={{ color: "var(--text2)" }}>
            {strings.resultSummaries.OutOfScopeSuggestion}
          </p>

          <button
            type="button"
            onClick={handleReset}
            className="mt-2 rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-opacity hover:opacity-90"
            style={{ background: "var(--grad)", color: "var(--surface)" }}
          >
            {strings.actions.searchAnother}
          </button>
        </div>
      </div>
    );
  }

  // --- UnsupportedGeography: center card with dim overlay (mock 10) ---
  if (resultState === "UnsupportedGeography") {
    return (
      <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
        <div className="absolute inset-0" style={{ background: "rgba(10,15,19,.6)", pointerEvents: "none" }} />
        <div
          className="pointer-events-auto relative flex max-w-[400px] flex-col items-center gap-4 rounded-[var(--r-lg)] text-center"
          style={{ background: "var(--s-low)", padding: "2.5rem 2rem" }}
        >
          {/* Icon */}
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: "var(--w-bg)" }}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--warn)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
          </div>

          <h2
            className="text-[1.3rem] font-bold"
            style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
          >
            {strings.resultStates.UnsupportedGeography(cityName)}
          </h2>

          <p className="text-[0.85rem] leading-relaxed" style={{ color: "var(--text2)" }}>
            {strings.resultSummaries.UnsupportedGeography(cityName)}
          </p>

          <p className="text-[0.8rem] leading-relaxed" style={{ color: "var(--text2)" }}>
            {strings.resultSummaries.UnsupportedGeographySuggestion}
          </p>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleReset}
              className="rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-opacity hover:opacity-90"
              style={{ background: "var(--grad)", color: "var(--surface)" }}
            >
              {strings.actions.newSearch}
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-colors hover:opacity-90"
              style={{ background: "var(--s-high)", color: "var(--text)" }}
            >
              {strings.actions.reset}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- Standard floating result card (mocks 06/07/08) ---
  const locSub = strings.locSub(result.horizon.year, CURRENT_YEAR, result.scenario.displayName);
  const summary =
    resultState === "ModeledExposureDetected"
      ? strings.resultSummaries.ModeledExposureDetected(locationLabel, result.scenario.displayName, result.horizon.year)
      : resultState === "NoModeledExposureDetected"
        ? strings.resultSummaries.NoModeledExposureDetected(locationLabel, result.scenario.displayName, result.horizon.year)
        : strings.resultSummaries.DataUnavailable(locationLabel, result.scenario.displayName, result.horizon.year);

  const disclaimer =
    resultState === "NoModeledExposureDetected"
      ? strings.disclaimerNoExposure
      : strings.disclaimer;

  // DataUnavailable suggestion buttons
  const handleTryNextHorizon = () => {
    if (!onHorizonChange || !horizons || !activeHorizonYear) return;
    const currentIndex = horizons.findIndex((h) => h.year === activeHorizonYear);
    const nextHorizon = horizons[currentIndex + 1];
    if (nextHorizon) onHorizonChange(nextHorizon.year);
  };

  const handleTryIpccModel = () => {
    if (!onScenarioChange || !scenarios) return;
    // Find "worst case" / ssp5-85 scenario
    const ipcc = scenarios.find((s) => s.id === "ssp5-85");
    if (ipcc && ipcc.id !== activeScenarioId) onScenarioChange(ipcc.id);
  };

  return (
    <div
      className="pointer-events-auto absolute right-[72px] top-6 z-20 flex w-[320px] flex-col gap-4 rounded-[var(--r-lg)] p-6"
      style={{ background: "var(--s-low)" }}
      aria-live="polite"
      aria-label={strings.accessibility.resultRegion}
    >
      {/* Badge */}
      <div
        className="inline-flex w-fit items-center gap-2 rounded-[var(--r-sm)] px-3 py-1 text-[0.75rem] font-semibold"
        style={badgeStyle}
      >
        <BadgeIcon resultState={resultState} />
        {resultState === "ModeledExposureDetected"
          ? strings.resultStates.ModeledExposureDetected
          : resultState === "NoModeledExposureDetected"
            ? strings.resultStates.NoModeledExposureDetected
            : strings.resultStates.DataUnavailable}
      </div>

      {/* Location + loc-sub */}
      <div>
        <div
          className="text-[1.5rem] font-bold"
          style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
        >
          {locationLabel}
        </div>
        <div className="text-[0.8rem]" style={{ color: "var(--text2)" }}>
          {locSub}
        </div>
      </div>

      {/* Summary card-section */}
      <div
        className="rounded-[var(--r-md)] p-3 text-[0.8rem] leading-relaxed"
        style={{ background: "var(--s-high)", color: "var(--text2)" }}
      >
        {summary}
      </div>

      {/* DataUnavailable suggestion buttons (mock 08) */}
      {resultState === "DataUnavailable" && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleTryNextHorizon}
            className="rounded-full border px-4 py-2 text-[0.85rem] font-medium transition-colors hover:opacity-90"
            style={{ borderColor: "var(--s-high)", background: "transparent", color: "var(--text)" }}
          >
            {strings.actions.tryNextHorizon}
          </button>
          <button
            type="button"
            onClick={handleTryIpccModel}
            className="rounded-full border px-4 py-2 text-[0.85rem] font-medium transition-colors hover:opacity-90"
            style={{ borderColor: "var(--s-high)", background: "transparent", color: "var(--text)" }}
          >
            {strings.actions.tryIpccModel}
          </button>
        </div>
      )}

      {/* Metadata rows (mock 06: Forecast model / Timeframe) */}
      {resultState !== "DataUnavailable" && (
        <>
          <div
            className="my-1"
            style={{ height: "1px", background: "var(--s-high)" }}
          />
          <div>
            <div className="flex items-center justify-between py-1 text-[0.85rem]">
              <span style={{ color: "var(--text2)" }}>Forecast model</span>
              <span className="font-semibold" style={{ color: "var(--text)" }}>
                {result.scenario.displayName}
              </span>
            </div>
            <div className="flex items-center justify-between py-1 text-[0.85rem]">
              <span style={{ color: "var(--text2)" }}>Timeframe</span>
              <span className="font-semibold" style={{ color: "var(--text)" }}>
                +{result.horizon.year - CURRENT_YEAR} years
              </span>
            </div>
          </div>
        </>
      )}

      {/* Source citation (mocks 06/07/08) */}
      <div className="text-[0.7rem]" style={{ color: "var(--text3)" }}>
        {strings.source}
      </div>

      {/* Disclaimer */}
      <div className="text-[0.7rem] italic" style={{ color: "var(--text3)" }}>
        {disclaimer}
      </div>
    </div>
  );
}
