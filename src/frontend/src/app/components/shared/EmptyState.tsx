"use client";

import SearchBar from "../search/SearchBar";
import { strings } from "@/lib/i18n/en";

interface EmptyStateProps {
  onSubmitQuery: (query: string) => void;
}

export default function EmptyState({ onSubmitQuery }: EmptyStateProps) {
  return (
    <div
      className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center p-6 text-center"
    >
      <div className="pointer-events-auto flex max-w-[560px] flex-col items-center">
        <h1
          aria-live="polite"
          className="mb-3 text-[2.4rem] font-extrabold leading-tight"
          style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
        >
          {strings.emptyState.headlinePrefix}{" "}
          <span
            className="bg-clip-text"
            style={{
              background: "var(--grad)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            {strings.emptyState.headlineAccent}
          </span>{" "}
          {strings.emptyState.headlineSuffix}
        </h1>
        <p
          className="mb-8 max-w-[480px] text-[0.95rem] leading-relaxed"
          style={{ color: "var(--text2)" }}
        >
          {strings.emptyState.body}
        </p>
        <div className="w-full max-w-[520px]">
          <SearchBar onSubmitQuery={onSubmitQuery} />
        </div>
      </div>

      {/* Disclaimer bar at bottom */}
      <div
        className="pointer-events-auto absolute bottom-[52px] left-1/2 -translate-x-1/2 whitespace-nowrap rounded-[var(--r-md)] px-4 py-2 text-[0.65rem]"
        style={{ background: "var(--s-high)", color: "var(--text2)" }}
      >
        {strings.emptyState.subtext}
      </div>
    </div>
  );
}
