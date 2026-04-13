"use client";

import { useEffect, useRef } from "react";
import { useMethodology } from "@/lib/api/methodology";
import { strings } from "@/lib/i18n/en";

interface MethodologyPanelProps {
  onClose: () => void;
}

export default function MethodologyPanel({ onClose }: MethodologyPanelProps) {
  const { data, isLoading, isError } = useMethodology();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Focus trap, focus management, and focus restoration on unmount.
  useEffect(() => {
    // Capture whoever was focused when the drawer opened so we can return to
    // it on close. This satisfies WCAG 2.4.3 focus order and matches the
    // claim in docs/delivery/artifacts/a11y-audit-report.md.
    previouslyFocusedRef.current = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();

    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      if (e.key === "Tab" && panelRef.current) {
        const focusable = panelRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocusedRef.current?.focus();
    };
  }, [onClose]);

  // Prevent scroll on body when panel is open
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-[200] flex justify-end"
      style={{ background: "rgba(10,15,19,.7)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={strings.methodology.title}
    >
      <div
        ref={panelRef}
        className="relative flex w-[420px] max-w-full flex-col gap-6 overflow-y-auto p-8"
        style={{
          background: "var(--s-low)",
          boxShadow: "0 0 40px rgba(223,227,233,.08)",
        }}
      >
        {/* Close button — positioned relative to drawer */}
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-full border-none text-[16px] cursor-pointer"
          style={{ background: "var(--s-high)", color: "var(--text2)" }}
          aria-label={strings.accessibility.closePanel}
        >
          &times;
        </button>

        <h2
          className="text-[1.3rem] font-bold"
          style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)" }}
        >
          {strings.methodology.title}
        </h2>

        {isLoading && (
          <div className="flex items-center gap-3 text-[0.85rem]" style={{ color: "var(--text2)" }}>
            <div
              className="h-5 w-5 flex-shrink-0 animate-spin rounded-full"
              style={{ border: "2px solid var(--s-high)", borderTopColor: "var(--primary)" }}
            />
            {strings.methodology.loading}
          </div>
        )}

        {isError && (
          <div className="text-[0.85rem]" style={{ color: "var(--err)" }}>
            {strings.methodology.error}
          </div>
        )}

        {data && (
          <>
            {/* Data sources */}
            <div className="flex flex-col gap-3">
              <h3
                className="text-[1rem] font-semibold"
                style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
              >
                {strings.methodology.dataSources}
              </h3>
              {[data.seaLevelProjectionSource, data.elevationSource].map((source) => (
                <div
                  key={source.name}
                  className="flex flex-col gap-2 rounded-[var(--r-md)] p-4"
                  style={{ background: "var(--s-high)" }}
                >
                  <div
                    className="text-[0.9rem] font-semibold"
                    style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
                  >
                    {source.name}
                  </div>
                  <div className="text-[0.8rem]" style={{ color: "var(--text2)" }}>
                    {source.provider}
                  </div>
                  {source.url && (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[0.8rem] underline"
                      style={{ color: "var(--primary)" }}
                    >
                      {strings.methodology.sourceLinkLabel}
                    </a>
                  )}
                </div>
              ))}
            </div>

            {/* How it works */}
            <div className="flex flex-col gap-3">
              <h3
                className="text-[1rem] font-semibold"
                style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
              >
                {strings.methodology.howItWorks}
              </h3>
              <p className="text-[0.85rem] leading-[1.7]" style={{ color: "var(--text2)" }}>
                {data.whatItDoes}
              </p>
            </div>

            {/* What this does NOT account for */}
            <div className="flex flex-col gap-3">
              <h3
                className="text-[1rem] font-semibold"
                style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
              >
                {strings.methodology.whatItDoesNotAccount}
              </h3>
              <ul
                className="flex flex-col gap-2 pl-4 text-[0.85rem] leading-[1.7]"
                style={{ color: "var(--text2)", listStyle: "disc" }}
              >
                {data.whatItDoesNotAccountFor.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              {data.resolutionNote && (
                <p
                  className="text-[0.8rem] italic leading-[1.6]"
                  style={{ color: "var(--text3)" }}
                >
                  {data.resolutionNote}
                </p>
              )}
            </div>

            {/* Important warning */}
            <div className="flex flex-col gap-3">
              <h3
                className="text-[1rem] font-semibold"
                style={{ fontFamily: "var(--font-manrope, Manrope, sans-serif)", color: "var(--text)" }}
              >
                {strings.methodology.important}
              </h3>
              <div
                className="rounded-[var(--r-md)] p-4 text-[0.85rem] leading-[1.7]"
                style={{ background: "var(--w-bg)", color: "var(--warn)" }}
              >
                {strings.methodology.warningText}
              </div>
            </div>

            {/* Metadata */}
            <div
              className="pt-4 text-[0.7rem]"
              style={{ color: "var(--text3)", borderTop: "1px solid var(--s-high)" }}
            >
              {strings.methodology.versionLabel}: {data.methodologyVersion} &middot; {strings.methodology.dataUpdated} {new Date(data.updatedAt).toISOString().slice(0, 10)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
