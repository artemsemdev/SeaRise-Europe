"use client";

import { useCallback, useRef, type KeyboardEvent } from "react";
import type { ScenarioConfig } from "@/lib/types";
import { strings } from "@/lib/i18n/en";

interface ScenarioControlProps {
  scenarios: ScenarioConfig[];
  activeScenarioId: string;
  onSelect: (scenarioId: string) => void;
}

export default function ScenarioControl({
  scenarios,
  activeScenarioId,
  onSelect,
}: ScenarioControlProps) {
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);
  const sorted = [...scenarios].sort((a, b) => a.sortOrder - b.sortOrder);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent, index: number) => {
      let nextIndex: number | null = null;

      if (e.key === "ArrowDown" || e.key === "ArrowRight") {
        e.preventDefault();
        nextIndex = (index + 1) % sorted.length;
      } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
        e.preventDefault();
        nextIndex = (index - 1 + sorted.length) % sorted.length;
      } else if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        onSelect(sorted[index].id);
        return;
      }

      if (nextIndex !== null) {
        onSelect(sorted[nextIndex].id);
        itemRefs.current[nextIndex]?.focus();
      }
    },
    [sorted, onSelect]
  );

  return (
    <div>
      <div
        className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.06em]"
        style={{ color: "var(--text3)" }}
        id="scenario-label"
      >
        {strings.controls.scenarioLabel}
      </div>
      <div
        role="radiogroup"
        aria-labelledby="scenario-label"
        className="flex flex-col gap-2"
      >
        {sorted.map((scenario, index) => {
          const isActive = scenario.id === activeScenarioId;
          return (
            <div
              key={scenario.id}
              ref={(el) => { itemRefs.current[index] = el; }}
              role="radio"
              aria-checked={isActive}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onSelect(scenario.id)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              className="flex cursor-pointer items-center gap-3 rounded-[var(--r-md)] p-3 text-[0.85rem] transition-colors"
              style={{
                background: isActive ? "var(--p-bg)" : "var(--s-high)",
                color: isActive ? "var(--primary)" : "var(--text2)",
              }}
            >
              <span
                className="h-2 w-2 flex-shrink-0 rounded-full"
                style={{
                  background: isActive ? "var(--primary)" : "var(--text3)",
                }}
              />
              <div>
                <div>{scenario.displayName}</div>
                <div
                  className="mt-[2px] text-[0.7rem]"
                  style={{ color: "var(--text3)" }}
                >
                  {scenario.description}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
