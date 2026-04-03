"use client";

import { useEffect, useCallback, useRef } from "react";
import Sidebar from "./Sidebar";
import ResultPanel from "./ResultPanel";
import Legend from "./Legend";
import LoadingState from "../shared/LoadingState";
import ErrorBanner from "../shared/ErrorBanner";
import { useAppStore, useAppPhase, useAssessmentParams } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { useAssessment } from "@/lib/api/assessment";
import { useUrlStateWriter } from "@/lib/hooks/useUrlState";
import type { ConfigData, SelectedLocation } from "@/lib/types";
import { strings } from "@/lib/i18n/en";

interface AssessmentViewProps {
  config: ConfigData;
}

export default function AssessmentView({ config }: AssessmentViewProps) {
  const phase = useAppPhase();
  const assessmentParams = useAssessmentParams();
  const setAssessmentParams = useAppStore((s) => s.setAssessmentParams);
  const setResult = useAppStore((s) => s.setResult);
  const setResultUpdating = useAppStore((s) => s.setResultUpdating);
  const setAssessmentError = useAppStore((s) => s.setAssessmentError);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const { updateUrl } = useUrlStateWriter();

  // Get the location from the current phase
  const location: SelectedLocation | null =
    phase.phase === "assessing"
      ? phase.location
      : phase.phase === "result"
        ? phase.location
        : phase.phase === "result_updating"
          ? phase.location
          : phase.phase === "assessment_error"
            ? phase.location
            : null;

  // Initialize assessment params from config defaults when entering assessment phase
  useEffect(() => {
    if (location && !assessmentParams) {
      setAssessmentParams({
        scenarioId: config.defaults.scenarioId,
        horizonYear: config.defaults.horizonYear,
      });
    }
  }, [location, assessmentParams, config.defaults, setAssessmentParams]);

  // Build query params for the assessment hook
  const queryParams =
    location && assessmentParams
      ? {
          latitude: location.latitude,
          longitude: location.longitude,
          scenarioId: assessmentParams.scenarioId,
          horizonYear: assessmentParams.horizonYear,
        }
      : null;

  const { data, isLoading, isError, error } = useAssessment(queryParams);

  // Track previous result for updating state
  const prevResultRef = useRef(
    phase.phase === "result" ? phase.result : null
  );

  // Sync query results with app phase
  useEffect(() => {
    if (!location) return;

    if (isLoading) {
      if (prevResultRef.current && phase.phase !== "assessing") {
        setResultUpdating(location, prevResultRef.current);
      } else if (phase.phase !== "result_updating") {
        startAssessing(location);
      }
    } else if (isError) {
      const errObj = error as { code?: string; message?: string } | undefined;
      setAssessmentError(location, {
        code: errObj?.code ?? "UNKNOWN",
        message: errObj?.message ?? "Assessment failed",
      });
    } else if (data) {
      prevResultRef.current = data;
      setResult(location, data);
    }
  }, [data, isLoading, isError, error, location]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update URL when assessment params or location change
  useEffect(() => {
    if (location && assessmentParams) {
      updateUrl({
        lat: location.latitude,
        lng: location.longitude,
        scenario: assessmentParams.scenarioId,
        horizon: assessmentParams.horizonYear,
      });
    }
  }, [location, assessmentParams, updateUrl]);

  const handleScenarioChange = useCallback(
    (scenarioId: string) => {
      if (!assessmentParams || scenarioId === assessmentParams.scenarioId) return;
      setAssessmentParams({ ...assessmentParams, scenarioId });
    },
    [assessmentParams, setAssessmentParams]
  );

  const handleHorizonChange = useCallback(
    (year: number) => {
      if (!assessmentParams || year === assessmentParams.horizonYear) return;
      setAssessmentParams({ ...assessmentParams, horizonYear: year });
    },
    [assessmentParams, setAssessmentParams]
  );

  const handleRetry = useCallback(() => {
    if (location) {
      startAssessing(location);
    }
  }, [location, startAssessing]);

  if (!location || !assessmentParams) return null;

  const activeScenarioId = assessmentParams.scenarioId;
  const activeHorizonYear = assessmentParams.horizonYear;

  // For OutOfScope/UnsupportedGeography, don't show sidebar
  const result = phase.phase === "result" ? phase.result : null;
  const previousResult = phase.phase === "result_updating" ? phase.previousResult : null;
  const showSidebar =
    result?.resultState !== "OutOfScope" &&
    result?.resultState !== "UnsupportedGeography";

  return (
    <>
      {/* Sidebar with controls */}
      {showSidebar && (
        <Sidebar
          location={location}
          scenarios={config.scenarios}
          horizons={config.horizons}
          activeScenarioId={activeScenarioId}
          activeHorizonYear={activeHorizonYear}
          onScenarioChange={handleScenarioChange}
          onHorizonChange={handleHorizonChange}
        />
      )}

      {/* Assessment state rendering in the map area */}
      <div className="pointer-events-none absolute inset-0 z-20">
        {/* Loading state (first assessment) */}
        {phase.phase === "assessing" && (
          <div className="pointer-events-auto absolute right-[72px] top-6 z-30">
            <LoadingState variant="assessing" locationLabel={location.label} />
          </div>
        )}

        {/* Assessment error */}
        {phase.phase === "assessment_error" && (
          <div className="pointer-events-auto absolute right-[72px] top-6 z-30">
            <ErrorBanner
              variant="assessment"
              onRetry={handleRetry}
              locationLabel={location.label}
              locationContext={location.displayContext}
            />
          </div>
        )}

        {/* Result panel */}
        {result && (
          <div
            aria-busy={phase.phase === "result_updating" ? "true" : undefined}
          >
            {phase.phase === "result_updating" && (
              <>
                {/* Loading indicator overlaid */}
                <div className="pointer-events-auto absolute right-[72px] top-6 z-30">
                  <LoadingState variant="assessing" locationLabel={location.label} />
                </div>
              </>
            )}
            <div
              style={{
                opacity: phase.phase === "result_updating" ? 0.5 : 1,
                pointerEvents: phase.phase === "result_updating" ? "none" : "auto",
                transition: "opacity 0.2s ease",
              }}
            >
              <ResultPanel
                result={result}
                locationLabel={location.label}
                locationContext={location.displayContext}
                scenarios={config.scenarios}
                horizons={config.horizons}
                activeScenarioId={activeScenarioId}
                activeHorizonYear={activeHorizonYear}
                onScenarioChange={handleScenarioChange}
                onHorizonChange={handleHorizonChange}
              />
            </div>
          </div>
        )}

        {/* Result updating: show previous result, muted */}
        {previousResult && phase.phase === "result_updating" && !result && (
          <div
            aria-busy="true"
            style={{ opacity: 0.5, pointerEvents: "none", transition: "opacity 0.2s ease" }}
          >
            <ResultPanel
              result={previousResult}
              locationLabel={location.label}
              locationContext={location.displayContext}
            />
          </div>
        )}

        {/* Legend (only for ModeledExposureDetected) */}
        {result?.resultState === "ModeledExposureDetected" &&
          result.legendSpec && (
            <Legend colorStops={result.legendSpec.colorStops} />
          )}
      </div>
    </>
  );
}
