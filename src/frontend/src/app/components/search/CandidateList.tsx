"use client";

import { useState, useCallback, useRef, useEffect, type KeyboardEvent } from "react";
import type { GeocodingCandidate } from "@/lib/types";
import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import { strings } from "@/lib/i18n/en";

interface CandidateListProps {
  candidates: GeocodingCandidate[];
}

export default function CandidateList({ candidates }: CandidateListProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);

  const displayed = candidates.slice(0, 5);

  useEffect(() => {
    setActiveIndex(0);
  }, [candidates]);

  const selectCandidate = useCallback(
    (candidate: GeocodingCandidate) => {
      const location = {
        label: candidate.label,
        latitude: candidate.latitude,
        longitude: candidate.longitude,
      };
      setSelectedLocation(location);
      startAssessing(location);
    },
    [setSelectedLocation, startAssessing]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setActiveIndex((prev) => (prev < displayed.length - 1 ? prev + 1 : prev));
          break;
        case "ArrowUp":
          e.preventDefault();
          setActiveIndex((prev) => (prev > 0 ? prev - 1 : prev));
          break;
        case "Enter":
        case " ":
          e.preventDefault();
          selectCandidate(displayed[activeIndex]);
          break;
        case "Escape":
          useAppStore.getState().reset();
          break;
      }
    },
    [displayed, activeIndex, selectCandidate]
  );

  return (
    <ul
      ref={listRef}
      role="listbox"
      aria-label={strings.candidateList.heading}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className="overflow-hidden focus:outline-none"
      style={{
        background: "var(--s-low)",
        borderRadius: "0 0 var(--r-lg) var(--r-lg)",
        borderTop: "1px solid var(--s-high)",
        boxShadow: "0 12px 40px rgba(0, 0, 0, 0.5)",
      }}
    >
      {displayed.map((candidate, index) => (
        <li
          key={`${candidate.rank}-${candidate.label}`}
          id={`candidate-${index}`}
          role="option"
          aria-selected={index === activeIndex}
          onClick={() => selectCandidate(candidate)}
          className="flex cursor-pointer flex-col gap-0.5 px-5 py-3 transition-colors"
          style={{
            background: index === activeIndex ? "var(--s-high)" : "transparent",
            borderBottom: index < displayed.length - 1 ? "1px solid var(--s-high)" : "none",
          }}
        >
          <span
            className="text-[0.9rem] font-semibold"
            style={{ color: "var(--text)" }}
          >
            {candidate.label}
          </span>
          <span
            className="text-[0.75rem]"
            style={{ color: "var(--text3)" }}
          >
            {candidate.displayContext}
          </span>
        </li>
      ))}
    </ul>
  );
}
