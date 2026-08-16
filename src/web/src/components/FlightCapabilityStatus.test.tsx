import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { validateAppReleasePair } from "../offline/contracts/keys";
import type { RuntimeCapabilityV2 } from "../offline/contracts/policy";
import {
  FlightCapabilityAlerts,
  FlightCapabilityPill,
} from "./FlightCapabilityStatus";

const pair = validateAppReleasePair({
  contractVersion: 1,
  appBuildId: "flight-capability-test",
  dataReleaseId: "fixture-release",
});

function runtimeCapability(
  data: RuntimeCapabilityV2["data"],
  update: RuntimeCapabilityV2["update"] = Object.freeze({ state: "current" }),
  subject: RuntimeCapabilityV2["subject"] = Object.freeze({
    kind: "assessment", scenario: "ssp2-45", horizon: 2050,
  }),
): RuntimeCapabilityV2 {
  return Object.freeze({ contractVersion: 2, subject, data, update });
}

const noAction = async (): Promise<void> => undefined;
const online = Object.freeze({ state: "online-complete" as const, pair });

afterEach(cleanup);

describe("Flight capability presentation", () => {
  it("uses one conditional canonical header pill only for exact offline capability", () => {
    const { rerender } = render(<div className="flight-header__actions">
      <FlightCapabilityPill capability={runtimeCapability(Object.freeze({
        state: "available-offline", pair, resourceCount: 5, byteCount: 1024,
      }))} />
      <span className="release-pill">Synthetic fixture</span>
    </div>);
    expect(screen.getByText("Available offline for this assessment")).toBeVisible();
    expect(screen.queryByText(/verified resources/u)).not.toBeInTheDocument();
    expect(document.querySelectorAll("[data-capability-state='available-offline']")).toHaveLength(1);

    rerender(<div className="flight-header__actions">
      <FlightCapabilityPill capability={runtimeCapability(online)} />
      <span className="release-pill">Synthetic fixture</span>
    </div>);
    expect(document.querySelector("[data-capability-state]")).toBeNull();
    expect(screen.queryByText(/online/u)).not.toBeInTheDocument();
  });

  it("uses subject-specific offline copy and never claims offline map availability", () => {
    const data = Object.freeze({ state: "available-offline" as const, pair, resourceCount: 2, byteCount: 512 });
    const { container, rerender } = render(<FlightCapabilityPill capability={runtimeCapability(
      data,
      undefined,
      Object.freeze({ kind: "search", shards: Object.freeze(["core", "coastal"] as const) }),
    )} />);
    expect(screen.getByText("Search available offline")).toBeVisible();

    rerender(<FlightCapabilityPill capability={runtimeCapability(
      online,
      undefined,
      Object.freeze({ kind: "map", scenario: "ssp2-45", horizon: 2050 }),
    )} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps narrow/mobile header geometry free of status actions and multiplied capability pills", () => {
    window.innerWidth = 375;
    render(<header className="flight-header"><div className="flight-header__actions">
      <FlightCapabilityPill capability={runtimeCapability(Object.freeze({
        state: "available-offline", pair, resourceCount: 3, byteCount: 768,
      }))} />
      <span className="release-pill">Synthetic fixture</span>
      <button type="button">Methodology</button>
    </div></header>);
    expect(document.querySelectorAll("[data-capability-state]")).toHaveLength(1);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(document.querySelector(".capability-status")).toBeNull();
  });

  it("names missing resource classes and keeps retry in the visible Flight alert slot", async () => {
    const retry = vi.fn(noAction);
    render(<FlightCapabilityAlerts
      capability={runtimeCapability(Object.freeze({
        state: "connection-required",
        pair,
        missing: Object.freeze([
          { kind: "whole" as const, identity: "source-grid" },
          { kind: "range" as const, identity: "projection-range" },
        ]),
        retryable: true,
      }))}
      onRetry={retry}
      onUpdateAction={noAction}
    />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "Connection required. Missing release resource, projection data range for this exact interaction.",
    );
    const button = screen.getByRole("button", { name: "Retry availability" });
    button.focus();
    await userEvent.click(button);
    await waitFor(() => expect(retry).toHaveBeenCalledOnce());
    expect(button).toHaveFocus();
  });

  it.each(["quota", "evicted", "persistence-denied"] as const)(
    "shows %s storage degradation visibly while preserving the accepted result",
    (reason) => {
      render(<FlightCapabilityAlerts
        capability={runtimeCapability(Object.freeze({
          state: "degraded-storage", pair, reason, networkUsable: false,
        }))}
        onRetry={noAction}
        onUpdateAction={noAction}
      />);
      expect(screen.getByRole("alert")).toHaveTextContent(
        `Browser storage degraded (${reason}). The current accepted result remains visible.`,
      );
      expect(screen.getByRole("alert")).not.toHaveTextContent(/DataUnavailable|resultState/u);
    },
  );

  it.each([
    ["update-available", "Update available for next-release. The current version remains active.", "Prepare update"],
    ["ready-to-activate", "Update ready. Reload to use next-release.", "Reload to update"],
    ["activation-blocked", "Update blocked. another tab is active The current version remains active.", "Retry update"],
    ["failed", "Update failed. The current version remains active. integrity check failed", "Retry update"],
  ] as const)("places %s in the visible alert slot with an explicit action", async (state, copy, action) => {
    const request = vi.fn(noAction);
    const update = state === "update-available" || state === "ready-to-activate"
      ? Object.freeze({
          state,
          candidate: validateAppReleasePair({ ...pair, appBuildId: "next-build", dataReleaseId: "next-release" }),
        })
      : Object.freeze({
          state,
          reason: state === "activation-blocked" ? "another tab is active" : "integrity check failed",
        });
    render(<FlightCapabilityAlerts
      capability={runtimeCapability(online, update)}
      onRetry={noAction}
      onUpdateAction={request}
    />);
    expect(screen.getByRole("status")).toHaveTextContent(copy);
    await userEvent.click(screen.getByRole("button", { name: action }));
    await waitFor(() => expect(request).toHaveBeenCalledOnce());
  });

  it("keeps action errors visible and technical", async () => {
    render(<FlightCapabilityAlerts
      capability={runtimeCapability(
        online,
        Object.freeze({ state: "failed", reason: "candidate verification failed" }),
      )}
      onRetry={noAction}
      onUpdateAction={async () => { throw new Error("Update coordinator unavailable."); }}
    />);
    await userEvent.click(screen.getByRole("button", { name: "Retry update" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Capability action failed. Update coordinator unavailable. This is a technical failure, not a scientific outcome.",
    );
    expect(screen.getByRole("alert")).toBeVisible();
  });

  it("reconciles the status with the unchanged canonical Flight authority", () => {
    const mock = readFileSync(resolve(process.cwd(), "../../docs/product/Mock/SeaRise-Flight.html"), "utf8");
    const map = readFileSync(resolve(process.cwd(), "../../docs/product/Mock/MOCK_REQUIREMENTS_MAP.md"), "utf8");
    const styles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    expect(mock).toContain("offline · 3 of 4 capabilities cached");
    expect(map).toContain("Partly cached offline demo");
    expect(map).toContain("determine capability from actual cached resources");
    expect(styles).not.toContain(".capability-status");
  });
});
