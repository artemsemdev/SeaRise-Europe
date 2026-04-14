"use client";

import type { LegendColorStop } from "@/lib/types";
import { strings } from "@/lib/i18n/en";

interface LegendProps {
  colorStops: LegendColorStop[];
}

export default function Legend({ colorStops }: LegendProps) {
  if (colorStops.length === 0) return null;

  return (
    <div
      className="pointer-events-auto absolute bottom-6 left-6 z-20 flex flex-col gap-2 rounded-[var(--r-md)] px-4 py-3"
      style={{
        background: "var(--glass)",
        backdropFilter: `blur(var(--glass-blur))`,
      }}
      aria-label={strings.accessibility.legendLabel}
    >
      {colorStops.map((stop) => (
        <div key={stop.value} className="flex items-center gap-3 text-[0.75rem]">
          <span
            className="h-3 w-3 flex-shrink-0 rounded-sm"
            style={{ background: stop.color }}
            aria-hidden="true"
          />
          <span style={{ color: "var(--text2)" }}>{stop.label}</span>
        </div>
      ))}
    </div>
  );
}
