"use client";

import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { strings } from "@/lib/i18n/en";

interface ErrorBannerProps {
  variant: "geocoding" | "assessment";
  onRetry: () => void;
  locationLabel?: string;
  locationContext?: string;
}

export default function ErrorBanner({ variant, onRetry, locationLabel, locationContext }: ErrorBannerProps) {
  const reset = useAppStore((s) => s.reset);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);

  const handleNewSearch = () => {
    setSelectedLocation(null);
    reset();
  };

  // Geocoding error: simple inline banner (unchanged)
  if (variant === "geocoding") {
    const copy = strings.errors.geocodingFailure;
    return (
      <div className="flex flex-col items-center gap-4">
        <div
          role="alert"
          className="flex items-center gap-3 rounded-[var(--r-md)] px-4 py-3 text-[0.85rem]"
          style={{ background: "var(--err-bg)", color: "var(--err)" }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0">
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          {copy.heading}. {copy.body}
        </div>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-opacity hover:opacity-90"
            style={{ background: "var(--grad)", color: "var(--surface)" }}
          >
            {strings.actions.retry}
          </button>
        </div>
      </div>
    );
  }

  // Assessment error: result-card style matching mock 13
  const copy = strings.errors.assessmentFailure;
  return (
    <div
      role="alert"
      className="flex w-[320px] flex-col gap-4 rounded-[var(--r-lg)] p-6"
      style={{ background: "var(--s-low)", boxShadow: "0 12px 40px rgba(0, 0, 0, 0.5)" }}
    >
      {/* Location header */}
      {locationLabel && (
        <div>
          <div
            className="text-[1.5rem] font-bold"
            style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
          >
            {locationLabel}
          </div>
          {locationContext && (
            <div className="mt-1 text-[0.8rem]" style={{ color: "var(--text2)" }}>
              {locationContext}
            </div>
          )}
        </div>
      )}

      {/* Error banner */}
      <div
        className="flex items-center gap-3 rounded-[var(--r-md)] px-4 py-3 text-[0.85rem]"
        style={{ background: "var(--err-bg)", color: "var(--err)" }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
        {copy.heading}. {copy.body}
      </div>

      {/* Action buttons — vertical, full-width (mock 13) */}
      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={onRetry}
          className="w-full rounded-[var(--r-md)] border-none px-4 py-3 text-center text-[0.85rem] font-semibold transition-opacity hover:opacity-90"
          style={{ background: "var(--grad)", color: "var(--surface)" }}
        >
          {strings.actions.retry}
        </button>
        <button
          type="button"
          onClick={handleNewSearch}
          className="w-full rounded-[var(--r-md)] border-none px-4 py-3 text-center text-[0.85rem] font-semibold transition-colors hover:opacity-90"
          style={{ background: "var(--s-high)", color: "var(--text)" }}
        >
          {strings.actions.newSearch}
        </button>
      </div>
    </div>
  );
}
