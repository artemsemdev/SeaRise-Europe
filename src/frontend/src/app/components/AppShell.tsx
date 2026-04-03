"use client";

import dynamic from "next/dynamic";
import { useCallback } from "react";
import Providers from "./Providers";
import SearchOverlay from "./search/SearchOverlay";
import { useScenarioConfig } from "@/lib/api/config";
import { useAppPhase } from "@/lib/store/appStore";

const MapSurface = dynamic(() => import("./map/MapSurface"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center" style={{ background: "var(--surface)" }}>
      <div className="h-8 w-8 animate-pulse rounded-full" style={{ background: "var(--s-high)" }} />
    </div>
  ),
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
  useScenarioConfig();

  return (
    <div className="flex h-full flex-col" style={{ minHeight: "100vh" }}>
      <Topbar />
      <div className="relative flex flex-1 overflow-hidden">
        {/* Full-screen map */}
        <div className="relative flex-1" style={{ background: "var(--surface)" }}>
          <MapSurface />
          {/* All search UI floats on top of the map */}
          <SearchOverlay />
        </div>
      </div>
      <Footer />
    </div>
  );
}

export default function AppShell() {
  return (
    <Providers>
      <AppContent />
    </Providers>
  );
}
