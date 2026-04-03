"use client";

import { strings } from "@/lib/i18n/en";

interface LoadingStateProps {
  variant: "geocoding" | "assessing";
  locationLabel?: string;
}

export default function LoadingState({ variant, locationLabel }: LoadingStateProps) {
  if (variant === "geocoding") {
    return (
      <div
        aria-busy="true"
        className="flex items-center gap-3 rounded-[var(--r-md)] px-5 py-3 text-[0.85rem]"
        style={{
          background: "var(--s-low)",
          color: "var(--text2)",
          boxShadow: "0 4px 20px rgba(0, 0, 0, 0.3)",
        }}
      >
        <div
          className="h-[18px] w-[18px] flex-shrink-0 animate-spin rounded-full"
          style={{
            border: "2px solid var(--s-high)",
            borderTopColor: "var(--primary)",
          }}
        />
        {strings.loading.geocoding}
      </div>
    );
  }

  // Assessing variant — full card matching mock 05
  return (
    <div
      aria-busy="true"
      className="flex w-[340px] flex-col gap-4 rounded-[var(--r-lg)] p-6"
      style={{
        background: "var(--s-low)",
        boxShadow: "0 12px 40px rgba(0, 0, 0, 0.5)",
      }}
    >
      {/* Header: spinner + title */}
      <div className="flex items-center gap-4">
        <div
          className="h-6 w-6 flex-shrink-0 animate-spin rounded-full"
          style={{
            border: "3px solid var(--s-high)",
            borderTopColor: "var(--primary)",
          }}
        />
        <span
          className="text-[1.15rem] font-bold"
          style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
        >
          {strings.loading.title}
        </span>
      </div>

      {/* Subtitle */}
      <p className="m-0 text-[0.85rem]" style={{ color: "var(--text2)" }}>
        {strings.loading.subtitle(locationLabel ?? "")}
      </p>

      {/* Progress bar */}
      <div
        className="h-[3px] w-full overflow-hidden rounded-full"
        style={{ background: "var(--s-high)" }}
      >
        <div
          className="h-full rounded-full"
          style={{
            background: "var(--grad)",
            animation: "fill-progress 2s ease-in-out infinite",
          }}
        />
      </div>

      {/* Steps */}
      <div className="flex flex-col gap-2">
        {strings.loading.steps.map((step, i) => {
          // Simulate progress: first 2 done, 3rd active, 4th pending
          const state = i < 2 ? "done" : i === 2 ? "active" : "pending";
          return (
            <div key={step} className="flex items-center gap-3 text-[0.8rem]">
              <div
                className="h-[8px] w-[8px] flex-shrink-0 rounded-full"
                style={{
                  background:
                    state === "done"
                      ? "var(--ok)"
                      : state === "active"
                        ? "var(--primary)"
                        : "var(--text3)",
                }}
              />
              <span
                style={{
                  color:
                    state === "done"
                      ? "var(--ok)"
                      : state === "active"
                        ? "var(--primary)"
                        : "var(--text3)",
                }}
              >
                {step}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
