"use client";

import { useAppStore } from "@/lib/store/appStore";
import { strings } from "@/lib/i18n/en";

interface NoResultsProps {
  query: string;
}

export default function NoResults({ query }: NoResultsProps) {
  const reset = useAppStore((s) => s.reset);

  return (
    <div
      aria-live="polite"
      className="flex flex-col items-center gap-4 rounded-[var(--r-lg)] px-6 py-8 text-center"
      style={{
        background: "var(--s-low)",
        boxShadow: "0 12px 40px rgba(0, 0, 0, 0.5)",
      }}
    >
      {/* Icon */}
      <div
        className="flex h-14 w-14 items-center justify-center rounded-full"
        style={{ background: "var(--s-high)" }}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
          <line x1="8" y1="11" x2="14" y2="11" />
        </svg>
      </div>

      <h2
        className="text-[1.2rem] font-bold"
        style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
      >
        {strings.noResults.heading}
      </h2>

      <p
        className="max-w-[360px] text-[0.85rem] leading-relaxed"
        style={{ color: "var(--text2)" }}
      >
        {strings.noResults.body(query)}
      </p>

      <button
        type="button"
        onClick={reset}
        className="rounded-[var(--r-md)] border-none px-4 py-3 text-[0.85rem] font-semibold transition-colors"
        style={{ background: "var(--s-high)", color: "var(--text)" }}
      >
        Clear search
      </button>
    </div>
  );
}
