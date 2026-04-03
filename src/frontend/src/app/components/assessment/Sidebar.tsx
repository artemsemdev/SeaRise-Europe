"use client";

import ScenarioControl from "./ScenarioControl";
import HorizonControl from "./HorizonControl";
import type { ScenarioConfig, HorizonConfig, SelectedLocation } from "@/lib/types";
import { strings } from "@/lib/i18n/en";
import { useUiStore } from "@/lib/store/uiStore";
import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";

interface SidebarProps {
  location: SelectedLocation;
  scenarios: ScenarioConfig[];
  horizons: HorizonConfig[];
  activeScenarioId: string;
  activeHorizonYear: number;
  onScenarioChange: (scenarioId: string) => void;
  onHorizonChange: (year: number) => void;
}

export default function Sidebar({
  location,
  scenarios,
  horizons,
  activeScenarioId,
  activeHorizonYear,
  onScenarioChange,
  onHorizonChange,
}: SidebarProps) {
  const openMethodologyPanel = useUiStore((s) => s.openMethodologyPanel);
  const resetApp = useAppStore((s) => s.reset);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);

  const handleReset = () => {
    setSelectedLocation(null);
    resetApp();
  };

  return (
    <aside
      className="flex w-[280px] min-w-[280px] flex-col gap-6 overflow-y-auto p-6 z-10 md:flex"
      style={{ background: "var(--s-low)" }}
    >
      {/* Location title */}
      <div>
        <div
          className="text-[0.95rem] font-bold"
          style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
        >
          {location.label}
        </div>
      </div>

      {/* Horizon selector */}
      <HorizonControl
        horizons={horizons}
        activeHorizonYear={activeHorizonYear}
        onSelect={onHorizonChange}
      />

      {/* Scenario selector */}
      <ScenarioControl
        scenarios={scenarios}
        activeScenarioId={activeScenarioId}
        onSelect={onScenarioChange}
      />

      {/* Info note */}
      <div
        className="flex items-start gap-3 rounded-[var(--r-md)] p-3 text-[0.8rem] leading-relaxed"
        style={{ background: "var(--s-highest)", color: "var(--text2)" }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="mt-[2px] flex-shrink-0"
          style={{ color: "var(--primary)" }}
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
        <span>{strings.controls.infoNote}</span>
      </div>

      {/* Bottom links */}
      <div className="mt-auto flex flex-col gap-3">
        <button
          type="button"
          onClick={openMethodologyPanel}
          className="inline-flex items-center gap-2 border-none bg-transparent p-0 text-[0.8rem] font-medium cursor-pointer"
          style={{ color: "var(--primary)" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          {strings.actions.methodology}
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="inline-flex items-center gap-2 border-none bg-transparent p-0 text-[0.8rem] font-medium cursor-pointer"
          style={{ color: "var(--primary)" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          {strings.actions.newSearch}
        </button>
      </div>
    </aside>
  );
}
