"use client";

import dynamic from "next/dynamic";
import { Suspense, useEffect, useRef } from "react";
import Providers from "./Providers";
import SearchOverlay from "./search/SearchOverlay";
import { useScenarioConfig } from "@/lib/api/config";
import { useAppStore, useAppPhase } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { useUiStore } from "@/lib/store/uiStore";
import { useUrlStateReader } from "@/lib/hooks/useUrlState";
import AssessmentView from "./assessment/AssessmentView";
import { strings } from "@/lib/i18n/en";

const MapSurface = dynamic(() => import("./map/MapSurface"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center" style={{ background: "var(--surface)" }}>
      <div className="h-8 w-8 animate-pulse rounded-full" style={{ background: "var(--s-high)" }} />
    </div>
  ),
});

const MethodologyPanel = dynamic(() => import("./assessment/MethodologyPanel"), {
  ssr: false,
});

function Topbar() {
  return (
    <header
      className="relative z-50 flex h-[52px] items-center justify-between px-6"
      style={{ background: "var(--s-low)" }}
    >
      <a
        href="/"
        className="text-[1.1rem] font-extrabold tracking-wide no-underline"
        style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--primary)" }}
      >
        SEARISE EUROPE
      </a>
      <nav>
        <ul className="flex list-none gap-6">
          <li>
            <span
              className="text-[0.85rem] font-medium"
              style={{ color: "var(--text)", borderBottom: "2px solid var(--primary)", paddingBottom: "2px" }}
            >
              Explorer
            </span>
          </li>
          <li>
            <span
              className="cursor-pointer text-[0.85rem] font-medium transition-colors hover:text-[var(--text)]"
              style={{ color: "var(--text2)" }}
            >
              About Data
            </span>
          </li>
        </ul>
      </nav>
      <div className="flex items-center gap-3">
        <button
          className="flex h-[34px] w-[34px] items-center justify-center rounded-full border-none text-[15px] transition-colors"
          style={{ background: "var(--s-high)", color: "var(--text2)" }}
          title="Help"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </button>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer
      className="relative z-50 flex items-center justify-between px-6 py-2 text-[0.65rem]"
      style={{ background: "var(--s-darkest)", color: "var(--text3)" }}
    >
      <span>&copy; 2026 SeaRise Europe. Data: NASA, Copernicus, IPCC.</span>
      <div className="flex gap-6">
        <span className="cursor-pointer transition-colors hover:text-[var(--text)]">About Data</span>
        <span className="cursor-pointer transition-colors hover:text-[var(--text)]">Privacy</span>
      </div>
    </footer>
  );
}

function AppContent() {
  const { data: config } = useScenarioConfig();
  const phase = useAppPhase();
  const isMethodologyPanelOpen = useUiStore((s) => s.isMethodologyPanelOpen);
  const closeMethodologyPanel = useUiStore((s) => s.closeMethodologyPanel);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const setAssessmentParams = useAppStore((s) => s.setAssessmentParams);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);
  const urlState = useUrlStateReader(config);
  const initializedFromUrl = useRef(false);

  // Initialize from URL params on first load
  useEffect(() => {
    if (!config || !urlState || initializedFromUrl.current) return;
    if (phase.phase !== "idle") return;

    initializedFromUrl.current = true;

    const location = {
      label: `${urlState.lat.toFixed(4)}, ${urlState.lng.toFixed(4)}`,
      displayContext: "",
      latitude: urlState.lat,
      longitude: urlState.lng,
    };

    setSelectedLocation(location);
    setAssessmentParams({
      scenarioId: urlState.scenario,
      horizonYear: urlState.horizon,
    });
    startAssessing(location);
  }, [config, urlState, phase.phase, startAssessing, setAssessmentParams, setSelectedLocation]);

  const isAssessmentPhase =
    phase.phase === "assessing" ||
    phase.phase === "result" ||
    phase.phase === "result_updating" ||
    phase.phase === "assessment_error";

  return (
    <div className="flex h-full flex-col" style={{ minHeight: "100vh" }}>
      {/* Skip to content */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[300] focus:rounded-[var(--r-md)] focus:px-4 focus:py-2"
        style={{ background: "var(--primary)", color: "var(--surface)" }}
      >
        {strings.accessibility.skipToContent}
      </a>
      <Topbar />
      <div id="main-content" className="relative flex flex-1 overflow-hidden">
        {/* Sidebar for assessment phases */}
        {isAssessmentPhase && config && (
          <AssessmentView config={config} />
        )}

        {/* Map area */}
        <div className="relative flex-1" style={{ background: "var(--surface)" }}>
          <MapSurface />
          {/* Search overlay is only shown for non-assessment phases */}
          {!isAssessmentPhase && <SearchOverlay />}
        </div>
      </div>
      <Footer />

      {/* Methodology panel overlay */}
      {isMethodologyPanelOpen && (
        <MethodologyPanel onClose={closeMethodologyPanel} />
      )}
    </div>
  );
}

export default function AppShell() {
  return (
    <Providers>
      <Suspense fallback={null}>
        <AppContent />
      </Suspense>
    </Providers>
  );
}
