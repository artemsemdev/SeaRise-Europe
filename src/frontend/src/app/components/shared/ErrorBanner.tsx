"use client";

import { useAppStore } from "@/lib/store/appStore";
import { strings } from "@/lib/i18n/en";

interface ErrorBannerProps {
  variant: "geocoding" | "assessment";
  onRetry: () => void;
}

export default function ErrorBanner({ variant, onRetry }: ErrorBannerProps) {
  const reset = useAppStore((s) => s.reset);
  const copy =
    variant === "geocoding"
      ? strings.errors.geocodingFailure
      : strings.errors.assessmentFailure;

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Error banner */}
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

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={onRetry}
          className="rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-opacity hover:opacity-90"
          style={{ background: "var(--grad)", color: "var(--surface)" }}
        >
          Retry
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-colors"
          style={{ background: "var(--s-high)", color: "var(--text)" }}
        >
          Clear
        </button>
      </div>
    </div>
  );
}
