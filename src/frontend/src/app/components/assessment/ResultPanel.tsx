"use client";

import type { AssessmentResult, ResultState } from "@/lib/types";
import { strings } from "@/lib/i18n/en";
import { useUiStore } from "@/lib/store/uiStore";
import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";

interface ResultPanelProps {
  result: AssessmentResult;
  locationLabel: string;
}

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

function getSummary(
  resultState: ResultState,
  locationLabel: string,
  scenarioDisplayName: string,
  horizonYear: number
): string {
  switch (resultState) {
    case "ModeledExposureDetected":
      return strings.resultSummaries.ModeledExposureDetected(locationLabel, scenarioDisplayName, horizonYear);
    case "NoModeledExposureDetected":
      return strings.resultSummaries.NoModeledExposureDetected(locationLabel, scenarioDisplayName, horizonYear);
    case "DataUnavailable":
      return strings.resultSummaries.DataUnavailable(locationLabel, scenarioDisplayName, horizonYear);
    case "OutOfScope":
      return strings.resultSummaries.OutOfScope(locationLabel);
    case "UnsupportedGeography":
      return strings.resultSummaries.UnsupportedGeography(locationLabel);
  }
}

export default function ResultPanel({ result, locationLabel }: ResultPanelProps) {
  const openMethodologyPanel = useUiStore((s) => s.openMethodologyPanel);
  const reset = useAppStore((s) => s.reset);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);

  const handleReset = () => {
    setSelectedLocation(null);
    reset();
  };

  const { resultState } = result;
  const badgeStyle = getBadgeStyle(resultState);
  const headline = strings.resultStates[resultState];
  const summary = getSummary(
    resultState,
    locationLabel,
    result.scenario.displayName,
    result.horizon.year
  );

  // OutOfScope and UnsupportedGeography use center card layout
  if (resultState === "OutOfScope" || resultState === "UnsupportedGeography") {
    return (
      <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
        {resultState === "UnsupportedGeography" && (
          <div className="absolute inset-0" style={{ background: "rgba(10,15,19,.6)" }} />
        )}
        <div
          className="pointer-events-auto relative flex max-w-[400px] flex-col items-center gap-4 rounded-[var(--r-lg)] p-10 text-center"
          style={{ background: "var(--s-low)" }}
        >
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: resultState === "UnsupportedGeography" ? "var(--w-bg)" : "var(--s-high)" }}
          >
            {resultState === "OutOfScope" ? (
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--text)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="m8 3 4 8 5-5 2 14H2L8 3z" />
                <path d="M4.14 15.08c2.62-1.57 5.24-1.43 7.86.42 2.74 1.94 5.49 2 8.23.19" />
              </svg>
            ) : (
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--warn)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="2" y1="12" x2="22" y2="12" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
            )}
          </div>
          <h2
            className="text-[1.3rem] font-bold"
            style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
          >
            {headline}
          </h2>
          <p className="text-[0.85rem] leading-relaxed" style={{ color: "var(--text2)" }}>
            {summary}
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

  // Standard floating result card for exposure/no-exposure/data-unavailable
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
        {headline}
      </div>

      {/* Location + context */}
      <div>
        <div
          className="text-[1.5rem] font-bold"
          style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
        >
          {locationLabel}
        </div>
        <div className="text-[0.8rem]" style={{ color: "var(--text2)" }}>
          {result.scenario.displayName} &middot; {result.horizon.displayLabel}
        </div>
      </div>

      {/* Summary */}
      <div
        className="rounded-[var(--r-md)] p-3 text-[0.8rem] leading-relaxed"
        style={{ background: "var(--s-high)", color: "var(--text2)" }}
      >
        {summary}
      </div>

      {/* Metadata rows */}
      <div>
        <div className="flex items-center justify-between py-1 text-[0.85rem]">
          <span style={{ color: "var(--text2)" }}>Forecast model</span>
          <span className="font-semibold" style={{ color: "var(--text)" }}>
            {result.scenario.displayName}
          </span>
        </div>
        <div className="flex items-center justify-between py-1 text-[0.85rem]">
          <span style={{ color: "var(--text2)" }}>Time horizon</span>
          <span className="font-semibold" style={{ color: "var(--text)" }}>
            {result.horizon.displayLabel}
          </span>
        </div>
        <div className="flex items-center justify-between py-1 text-[0.85rem]">
          <span style={{ color: "var(--text2)" }}>Methodology</span>
          <span className="font-semibold" style={{ color: "var(--text)" }}>
            {result.methodologyVersion}
          </span>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="text-[0.7rem] italic" style={{ color: "var(--text3)" }}>
        {strings.disclaimer}
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={openMethodologyPanel}
          className="inline-flex items-center gap-2 bg-transparent border-none p-0 text-[0.8rem] font-medium cursor-pointer"
          style={{ color: "var(--primary)" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          {strings.actions.methodology}
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="inline-flex items-center gap-2 bg-transparent border-none p-0 text-[0.8rem] font-medium cursor-pointer"
          style={{ color: "var(--primary)" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          {strings.actions.newSearch}
        </button>
      </div>
    </div>
  );
}
