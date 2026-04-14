"use client";

import { useCallback, useEffect } from "react";
import SearchBar from "./SearchBar";
import CandidateList from "./CandidateList";
import EmptyState from "../shared/EmptyState";
import LoadingState from "../shared/LoadingState";
import ErrorBanner from "../shared/ErrorBanner";
import NoResults from "../shared/NoResults";
import { useAppStore, useAppPhase } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { useGeocodeQuery } from "@/lib/api/geocoding";

export default function SearchOverlay() {
  const phase = useAppPhase();
  const startGeocoding = useAppStore((s) => s.startGeocoding);
  const setGeocodingError = useAppStore((s) => s.setGeocodingError);
  const setCandidates = useAppStore((s) => s.setCandidates);
  const setNoResults = useAppStore((s) => s.setNoResults);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);

  // Only drive the query when we are actively geocoding. Other phases
  // (candidate_selection, geocoding_error, no_geocoding_results) park the
  // query so the cache is preserved but no new fetch is triggered.
  const activeQuery = phase.phase === "geocoding" ? phase.query : null;
  const geocodeQuery = useGeocodeQuery(activeQuery);

  // Advance the phase machine based on query outcome. Runs only while phase
  // is "geocoding"; once we transition out, the early return prevents
  // further effect-driven transitions against stale data.
  useEffect(() => {
    if (phase.phase !== "geocoding") return;

    if (geocodeQuery.isSuccess && geocodeQuery.data) {
      const { candidates } = geocodeQuery.data;
      if (candidates.length === 0) {
        setNoResults(phase.query);
      } else if (candidates.length === 1) {
        const c = candidates[0];
        const location = {
          label: c.label,
          displayContext: c.displayContext,
          latitude: c.latitude,
          longitude: c.longitude,
        };
        setSelectedLocation(location);
        startAssessing(location);
      } else {
        setCandidates(candidates);
      }
    } else if (geocodeQuery.isError && geocodeQuery.error) {
      setGeocodingError(
        { code: geocodeQuery.error.code ?? "UNKNOWN", message: geocodeQuery.error.message },
        phase.query
      );
    }
  }, [
    phase,
    geocodeQuery.isSuccess,
    geocodeQuery.isError,
    geocodeQuery.data,
    geocodeQuery.error,
    setCandidates,
    setNoResults,
    setSelectedLocation,
    setGeocodingError,
    startAssessing,
  ]);

  const runGeocode = useCallback(
    (query: string) => {
      startGeocoding(query);
    },
    [startGeocoding]
  );

  const retryGeocoding = useCallback(() => {
    if (phase.phase !== "geocoding_error") return;
    startGeocoding(phase.lastQuery);
  }, [phase, startGeocoding]);

  // Landing / idle: show full hero overlay
  if (phase.phase === "idle") {
    return <EmptyState onSubmitQuery={runGeocode} />;
  }

  // Assessment phases are handled by AssessmentView — don't render here
  if (
    phase.phase === "assessing" ||
    phase.phase === "result" ||
    phase.phase === "result_updating" ||
    phase.phase === "assessment_error"
  ) {
    return null;
  }

  // All search-related phases: floating search bar at top-center + state below
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center pt-6">
      <div className="pointer-events-auto w-full max-w-[520px] px-4">
        <SearchBar onSubmitQuery={runGeocode} />

        {phase.phase === "geocoding" && (
          <div className="mt-4">
            <LoadingState variant="geocoding" />
          </div>
        )}

        {phase.phase === "geocoding_error" && (
          <div className="mt-4">
            <ErrorBanner variant="geocoding" onRetry={retryGeocoding} />
          </div>
        )}

        {phase.phase === "no_geocoding_results" && (
          <div className="mt-4">
            <NoResults query={phase.query} />
          </div>
        )}

        {phase.phase === "candidate_selection" && (
          <CandidateList candidates={phase.candidates} />
        )}
      </div>
    </div>
  );
}
