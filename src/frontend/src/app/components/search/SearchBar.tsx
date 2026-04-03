"use client";

import { useState, useCallback, type FormEvent } from "react";
import { useAppStore, useAppPhase } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { useGeocodeMutation } from "@/lib/api/geocoding";
import { strings } from "@/lib/i18n/en";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const phase = useAppPhase();
  const startGeocoding = useAppStore((s) => s.startGeocoding);
  const setCandidates = useAppStore((s) => s.setCandidates);
  const setNoResults = useAppStore((s) => s.setNoResults);
  const setGeocodingError = useAppStore((s) => s.setGeocodingError);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);
  const reset = useAppStore((s) => s.reset);

  const geocodeMutation = useGeocodeMutation();

  const isSearchActive = phase.phase !== "idle";

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmed = query.trim();
      if (!trimmed) return;

      startGeocoding(trimmed);

      geocodeMutation.mutate(trimmed, {
        onSuccess: (data) => {
          const { candidates } = data;
          if (candidates.length === 0) {
            setNoResults(trimmed);
          } else if (candidates.length === 1) {
            const c = candidates[0];
            const location = { label: c.label, latitude: c.latitude, longitude: c.longitude };
            setSelectedLocation(location);
            startAssessing(location);
          } else {
            setCandidates(candidates);
          }
        },
        onError: (error) => {
          setGeocodingError(
            { code: error.code ?? "UNKNOWN", message: error.message },
            trimmed
          );
        },
      });
    },
    [query, startGeocoding, geocodeMutation, setCandidates, setNoResults, setGeocodingError, startAssessing, setSelectedLocation]
  );

  const handleClear = useCallback(() => {
    setQuery("");
    reset();
  }, [reset]);

  // Determine border radius based on whether dropdown is showing
  const hasDropdown = phase.phase === "candidate_selection";
  const borderRadius = hasDropdown ? "var(--r-lg) var(--r-lg) 0 0" : "var(--r-lg)";

  return (
    <form
      role="search"
      onSubmit={handleSubmit}
      className="flex items-center gap-3 px-4 py-2"
      style={{
        background: "var(--s-low)",
        borderRadius,
        boxShadow: "0 8px 32px rgba(0, 0, 0, 0.4)",
      }}
    >
      {/* Search icon */}
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ color: "var(--text3)", flexShrink: 0 }}
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>

      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={200}
        placeholder={strings.search.placeholder}
        aria-label={strings.search.placeholder}
        className="flex-1 border-none bg-transparent py-3 text-[0.95rem] outline-none"
        style={{ color: "var(--text)", fontFamily: "var(--font-inter, Inter, sans-serif)" }}
      />

      {/* Show clear button when search is active, otherwise show submit */}
      {isSearchActive ? (
        <button
          type="button"
          onClick={handleClear}
          className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border-none text-sm transition-colors"
          style={{ background: "var(--s-high)", color: "var(--text2)" }}
          title="Clear search"
        >
          &times;
        </button>
      ) : (
        <button
          type="submit"
          className="whitespace-nowrap rounded-[var(--r-md)] border-none px-6 py-3 text-[0.85rem] font-semibold transition-opacity hover:opacity-90"
          style={{ background: "var(--grad)", color: "var(--surface)" }}
        >
          {strings.search.submitLabel}
        </button>
      )}
    </form>
  );
}
