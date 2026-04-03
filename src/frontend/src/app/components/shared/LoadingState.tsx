"use client";

import { strings } from "@/lib/i18n/en";

interface LoadingStateProps {
  variant: "geocoding" | "assessing";
  locationLabel?: string;
}

export default function LoadingState({ variant, locationLabel }: LoadingStateProps) {
  const message =
    variant === "geocoding"
      ? strings.loading.geocoding
      : strings.loading.assessing(locationLabel ?? "");

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
      {/* Spinner matching design-system.css */}
      <div
        className="h-[18px] w-[18px] flex-shrink-0 animate-spin rounded-full"
        style={{
          border: "2px solid var(--s-high)",
          borderTopColor: "var(--primary)",
        }}
      />
      {message}
    </div>
  );
}
