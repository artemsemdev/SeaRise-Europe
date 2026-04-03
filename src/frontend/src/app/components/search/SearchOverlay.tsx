"use client";

import { useCallback } from "react";
import SearchBar from "./SearchBar";
import CandidateList from "./CandidateList";
import EmptyState from "../shared/EmptyState";
import LoadingState from "../shared/LoadingState";
import ErrorBanner from "../shared/ErrorBanner";
import NoResults from "../shared/NoResults";
import { useAppStore, useAppPhase } from "@/lib/store/appStore";
import { useGeocodeMutation } from "@/lib/api/geocoding";

export default function SearchOverlay() {
  const phase = useAppPhase();
  const startGeocoding = useAppStore((s) => s.startGeocoding);
  const setGeocodingError = useAppStore((s) => s.setGeocodingError);
  const setCandidates = useAppStore((s) => s.setCandidates);
  const setNoResults = useAppStore((s) => s.setNoResults);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const geocodeMutation = useGeocodeMutation();

  const retryGeocoding = useCallback(() => {
    if (phase.phase !== "geocoding_error") return;
    const query = phase.lastQuery;
    startGeocoding(query);
    geocodeMutation.mutate(query, {
      onSuccess: (data) => {
        if (data.candidates.length === 0) setNoResults(query);
        else if (data.candidates.length === 1) {
          const c = data.candidates[0];
          startAssessing({ label: c.label, latitude: c.latitude, longitude: c.longitude });
        } else setCandidates(data.candidates);
      },
      onError: (error) => {
        setGeocodingError({ code: error.code ?? "UNKNOWN", message: error.message }, query);
      },
    });
  }, [phase, startGeocoding, geocodeMutation, setCandidates, setNoResults, setGeocodingError, startAssessing]);

  const retryAssessment = useCallback(() => {
    if (phase.phase !== "assessment_error") return;
    startAssessing(phase.location);
  }, [phase, startAssessing]);

  // Landing / idle: show full hero overlay
  if (phase.phase === "idle") {
    return <EmptyState />;
  }

  // All other search-related phases: floating search bar at top-center + state below
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center pt-6">
      <div className="pointer-events-auto w-full max-w-[520px] px-4">
        <SearchBar />

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

        {phase.phase === "assessing" && (
          <div className="mt-4">
            <LoadingState variant="assessing" locationLabel={phase.location.label} />
          </div>
        )}

        {phase.phase === "assessment_error" && (
          <div className="mt-4">
            <ErrorBanner variant="assessment" onRetry={retryAssessment} />
          </div>
        )}

        {(phase.phase === "result" || phase.phase === "result_updating") && (
          <div className="mt-4 rounded-[var(--r-lg)] p-4 text-sm" style={{ background: "var(--s-low)", color: "var(--text2)" }}>
            {phase.phase === "result" ? phase.result.resultState : "Updating..."}
          </div>
        )}
      </div>
    </div>
  );
}
