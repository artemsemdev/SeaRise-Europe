"use client";

import { useCallback, useRef, type KeyboardEvent } from "react";
import type { HorizonConfig } from "@/lib/types";
import { strings } from "@/lib/i18n/en";

interface HorizonControlProps {
  horizons: HorizonConfig[];
  activeHorizonYear: number;
  onSelect: (year: number) => void;
}

const CURRENT_YEAR = 2026;

function relativeLabel(year: number): string {
  const diff = year - CURRENT_YEAR;
  return `+${diff} yr`;
}

export default function HorizonControl({
  horizons,
  activeHorizonYear,
  onSelect,
}: HorizonControlProps) {
  const stopRefs = useRef<(HTMLDivElement | null)[]>([]);
  const sorted = [...horizons].sort((a, b) => a.sortOrder - b.sortOrder);

  const activeIndex = sorted.findIndex((h) => h.year === activeHorizonYear);
  const fillPercentage =
    sorted.length > 1 && activeIndex >= 0
      ? (activeIndex / (sorted.length - 1)) * 100
      : 0;

  const handleKeyDown = useCallback(
    (e: KeyboardEvent, index: number) => {
      let nextIndex: number | null = null;

      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        nextIndex = Math.min(index + 1, sorted.length - 1);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        nextIndex = Math.max(index - 1, 0);
      } else if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        onSelect(sorted[index].year);
        return;
      }

      if (nextIndex !== null && nextIndex !== index) {
        onSelect(sorted[nextIndex].year);
        stopRefs.current[nextIndex]?.focus();
      }
    },
    [sorted, onSelect]
  );

  return (
    <div>
      <div
        className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.06em]"
        style={{ color: "var(--text3)" }}
        id="horizon-label"
      >
        {strings.controls.horizonLabel}
      </div>
      <div
        role="radiogroup"
        aria-labelledby="horizon-label"
        className="relative select-none pb-2 pt-4"
        style={{ "--dot-size": "14px" } as React.CSSProperties}
      >
        <div className="relative flex items-start justify-between px-1">
          {/* Track line */}
          <div
            className="absolute rounded-[1px]"
            style={{
              top: "calc(7px - 1px)",
              left: "4px",
              right: "4px",
              height: "2px",
              background: "var(--s-high)",
            }}
          />
          {/* Gradient fill */}
          <div
            className="pointer-events-none absolute rounded-[1px] transition-[width] duration-300 ease-out"
            style={{
              top: "calc(7px - 1px)",
              left: "4px",
              height: "2px",
              width: `${fillPercentage}%`,
              background: "var(--grad)",
            }}
          />

          {sorted.map((horizon, index) => {
            const isActive = horizon.year === activeHorizonYear;
            const isPassed = index < activeIndex;

            return (
              <div
                key={horizon.year}
                ref={(el) => { stopRefs.current[index] = el; }}
                role="radio"
                aria-checked={isActive}
                aria-label={`${relativeLabel(horizon.year)}, year ${horizon.year}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => onSelect(horizon.year)}
                onKeyDown={(e) => handleKeyDown(e, index)}
                className="relative z-[2] flex cursor-pointer flex-col items-center gap-[6px]"
              >
                {/* Dot */}
                <div
                  className="h-[14px] w-[14px] flex-shrink-0 rounded-full transition-all duration-[250ms] ease-out"
                  style={{
                    background: isActive
                      ? "var(--primary)"
                      : isPassed
                        ? "var(--p-dim)"
                        : "var(--s-bright)",
                    borderWidth: "2.5px",
                    borderStyle: "solid",
                    borderColor: isActive
                      ? "var(--primary)"
                      : isPassed
                        ? "var(--p-dim)"
                        : "var(--s-high)",
                    boxShadow: isActive
                      ? "0 0 0 4px rgba(157,202,255,.15), 0 0 12px rgba(157,202,255,.3)"
                      : "none",
                    transform: isActive ? "scale(1.2)" : "scale(1)",
                  }}
                />
                {/* Relative label */}
                <span
                  className="whitespace-nowrap text-[0.65rem] font-medium leading-none transition-all duration-[250ms] ease-out"
                  style={{
                    color: isActive ? "var(--primary)" : "var(--text3)",
                    fontWeight: isActive ? 700 : 500,
                    fontSize: isActive ? "0.72rem" : "0.65rem",
                  }}
                >
                  {relativeLabel(horizon.year)}
                </span>
                {/* Absolute year */}
                <span
                  className="text-[0.58rem] leading-none transition-opacity duration-[250ms] ease-out"
                  style={{
                    color: "var(--p-dim)",
                    opacity: isActive ? 1 : 0,
                  }}
                >
                  {horizon.year}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
