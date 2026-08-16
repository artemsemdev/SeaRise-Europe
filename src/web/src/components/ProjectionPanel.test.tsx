import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReleaseMethodology } from "../data/methodology-repository";
import type { AcceptedProjection, ProjectionOperation, ProjectionState } from "../domain/projection-state";
import type { AssessmentResult } from "../domain/scientific-lookup";
import type { ReleaseDisposition, Selection, TechnicalError } from "../domain/release";
import { ProjectionPanel, type ProjectionPanelProps } from "./ProjectionPanel";

const RELEASE_ID = "fixture-static-release-v2";
const release = Object.freeze({
  dataReleaseId: RELEASE_ID,
  methodologyVersion: "ar6-regional-projection-v1" as const,
});

function selection(
  scenario: Selection["scenario"] = "ssp2-45",
  horizon: Selection["horizon"] = 2050,
  latitude = 51.9244,
): Selection {
  return Object.freeze({
    dataReleaseId: RELEASE_ID,
    scenario,
    horizon,
    location: Object.freeze({
      kind: "settlement" as const,
      placeId: "geonames:2747891",
      coordinates: Object.freeze({ latitude, longitude: 4.4777 }),
    }),
  });
}

const identity = {
  dataReleaseId: RELEASE_ID,
  methodologyVersion: "ar6-regional-projection-v1" as const,
  scenario: "ssp2-45" as const,
  horizon: 2050 as const,
  analysisArtifactId: "analysis-ssp2-45-2050",
  analysisArtifactSha256: "a".repeat(64),
  visualArtifactId: "visual-ssp2-45-2050",
  visualArtifactSha256: "b".repeat(64),
  visualArtifactUrl: "https://example.test/release/visual.pmtiles",
};

function result(resultState: AssessmentResult["resultState"]): AssessmentResult {
  switch (resultState) {
    case "ProjectionAvailable":
      return Object.freeze({
        ...identity,
        resultState,
        reason: "projection-available" as const,
        source: Object.freeze({ locationId: 42, latitude: 52, longitude: 4, distanceKilometres: 12.3456 }),
        lowerMillimetres: 156,
        medianMillimetres: 247,
        upperMillimetres: 351,
        lowerMetres: 0.156,
        medianMetres: 0.247,
        upperMetres: 0.351,
        units: "m" as const,
        baseline: "1995-2014 mean" as const,
        confidence: "medium" as const,
        sourceRelease: "20210809" as const,
        sourceMemberSha256: "c".repeat(64),
        nativeResolutionDegrees: 1 as const,
      });
    case "DataUnavailable":
      return Object.freeze({
        ...identity,
        resultState,
        reason: "source-location-too-distant" as const,
        source: Object.freeze({ locationId: 42, latitude: 52, longitude: 4, distanceKilometres: 100.001 }),
      });
    case "OutOfScope":
      return Object.freeze({ ...identity, resultState, reason: "outside-coastal-scope" as const });
    case "UnsupportedGeography":
      return Object.freeze({ ...identity, resultState, reason: "outside-europe-support" as const });
    default:
      throw new Error(`Unhandled result state: ${resultState satisfies never}`);
  }
}

function accepted(resultState: AssessmentResult["resultState"] = "ProjectionAvailable"): AcceptedProjection {
  return Object.freeze({
    release,
    selection: selection(),
    selectionKey: "fixture-selection-key",
    result: result(resultState),
  });
}

function methodology(disposition: ReleaseDisposition = "synthetic-fixture"): ReleaseMethodology {
  return Object.freeze({
    dataReleaseId: RELEASE_ID,
    disposition,
    methodologyVersion: "ar6-regional-projection-v1" as const,
    baseline: "1995-2014 mean" as const,
    likelyRange: Object.freeze({
      confidence: "medium" as const,
      lowerQuantile: 0.167 as const,
      medianQuantile: 0.5 as const,
      upperQuantile: 0.833 as const,
    }),
    lookup: Object.freeze({
      operator: "nearest-source-grid-location" as const,
      nativeResolutionDegrees: 1 as const,
      maximumDistanceKilometres: 100 as const,
      distanceLimitInclusive: true as const,
      interpolation: "prohibited" as const,
      extrapolation: "prohibited" as const,
      nodataSubstitution: "prohibited" as const,
      tideGaugeFallback: "prohibited" as const,
    }),
    resultStates: ["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"] as const,
    limitations: [
      "Reports regional relative sea-level projection, not an absolute water level.",
      "Does not model flooding, terrain exposure, probability, or property risk.",
    ],
    prohibitedClaims: ["flooding", "inundation", "terrain-exposure", "flood-probability", "property-risk"] as const,
    decision: Object.freeze({ id: "ADR-024" as const, href: "https://example.test/ADR-024" }),
    source: Object.freeze({
      title: "IPCC AR6 Regional Sea Level Projections",
      attributionText: "Source: IPCC AR6 regional sea-level projection dataset, release 20210809.",
      sourceUrl: "https://doi.org/10.5281/zenodo.6382554",
      licence: Object.freeze({
        spdxId: "CC-BY-4.0",
        name: "Creative Commons Attribution 4.0",
        url: "https://creativecommons.org/licenses/by/4.0/",
      }),
    }),
  });
}

function error(code: TechnicalError["code"], recoverable = true): TechnicalError {
  return Object.freeze({
    kind: "technical-error" as const,
    code,
    message: "The immutable artifact could not be loaded.",
    recoverable,
  });
}

function operation<K extends ProjectionOperation["kind"]>(
  kind: K,
  selected = selection("ssp5-85", 2100, 52.1),
): ProjectionOperation & { readonly kind: K } {
  return Object.freeze({
    kind,
    operationToken: 2,
    selection: selected,
    selectionKey: "new-selection-key",
    dataReleaseId: RELEASE_ID,
  });
}

function failureState(
  phase: "offline" | "connection-required" | "unsupported-browser" | "integrity-error" | "technical-error",
): ProjectionState {
  const failureError = phase === "unsupported-browser"
    ? error("UnsupportedBrowser", false)
    : phase === "integrity-error"
      ? error("IntegrityFailed", false)
      : error("FetchFailed");
  return {
    phase,
    release,
    expectedDataReleaseId: RELEASE_ID,
    operationToken: 2,
    operation: operation("update"),
    previous: accepted(),
    error: failureError,
  } as ProjectionState;
}

const callbacks = (): Omit<ProjectionPanelProps, "state" | "methodology"> => ({
  onSelectionChange: vi.fn(),
  onRetry: vi.fn(),
  onReset: vi.fn(),
  onShare: vi.fn(),
  onOpenMethodology: vi.fn(),
});

function renderPanel(
  state: ProjectionState,
  verifiedMethodology: ReleaseMethodology | null = methodology(),
  handlers = callbacks(),
) {
  return {
    ...render(<ProjectionPanel state={state} methodology={verifiedMethodology} {...handlers} />),
    handlers,
  };
}

afterEach(cleanup);

describe("projection panel phases", () => {
  const phases: readonly [ProjectionState, RegExp][] = [
    [{ phase: "booting", expectedDataReleaseId: RELEASE_ID, operationToken: 0 }, /loading and verifying the pinned data release/i],
    [{ phase: "ready", release, operationToken: 0 }, /choose a settlement or point/i],
    [{ phase: "searching", release, operationToken: 2, operation: operation("search"), previous: null }, /searching places locally/i],
    [{ phase: "evaluating", release, operationToken: 2, operation: operation("evaluation") }, /checking the selected point/i],
    [{ phase: "updating", release, operationToken: 2, operation: operation("update"), previous: accepted() }, /checking a new selection/i],
    [{ phase: "result", release, operationToken: 2, accepted: accepted() }, /scientific outcome updated: ProjectionAvailable/i],
    [failureState("offline"), /not available offline/i],
    [failureState("connection-required"), /connection required/i],
    [failureState("unsupported-browser"), /browser capability unavailable/i],
    [failureState("integrity-error"), /release integrity check failed/i],
    [failureState("technical-error"), /release delivery unavailable/i],
  ];

  it.each(phases)("renders the %s phase with explicit status", (state, expected) => {
    const { container } = renderPanel(state);
    expect(container.querySelector(".projection-panel")).toHaveAttribute("data-phase", state.phase);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("visibly separates the previous accepted tuple from the new updating selection", () => {
    const previous = accepted();
    const next = selection("ssp5-85", 2100, 52.1);
    renderPanel({ phase: "updating", release, operationToken: 2, operation: operation("update", next), previous });

    const update = screen.getByRole("status", { name: "" });
    expect(update).toHaveTextContent("Checking a new selection");
    expect(update).toHaveTextContent("Higher-emissions scenario (SSP5-8.5)");
    expect(update).toHaveTextContent("2100");
    expect(screen.getByText(/previous accepted result — a new selection is being checked/i)).toBeVisible();
    expect(screen.getByText(/0\.247 m/)).toBeVisible();
    for (const control of screen.getAllByRole("radio")) expect(control).toBeDisabled();
  });
});

describe("projection panel scientific outcomes", () => {
  it.each([
    ["ProjectionAvailable", /projected regional sea-level change available/i],
    ["DataUnavailable", /model data unavailable for this point/i],
    ["OutOfScope", /outside the coastal analysis area/i],
    ["UnsupportedGeography", /outside the supported Europe area/i],
  ] as const)("renders only the authoritative %s meaning", (outcome, headline) => {
    const { container } = renderPanel({ phase: "result", release, operationToken: 2, accepted: accepted(outcome) });
    expect(screen.getByRole("heading", { name: headline })).toBeVisible();
    expect(container.querySelectorAll("[data-outcome]")).toHaveLength(1);
    expect(container.querySelector("[data-outcome]")).toHaveAttribute("data-outcome", outcome);
    expect(screen.getByText(/map meaning:/i)).toBeVisible();
    expect(screen.getByText(/informational and educational use/i)).toHaveTextContent(
      "It does not determine flooding, inundation, terrain exposure, or property risk.",
    );
  });

  it("shows the exact approved available metadata, attribution, licence, limitations, and exclusions", () => {
    renderPanel({ phase: "result", release, operationToken: 2, accepted: accepted() });
    expect(screen.getByText(/selected settlement: geonames:2747891/i)).toBeVisible();
    expect(screen.getByText(/0\.247 m/)).toBeVisible();
    expect(screen.getByText(/0\.156–0\.351 m/)).toBeVisible();
    expect(screen.getByText(/q0\.167–q0\.833/)).toBeVisible();
    expect(screen.getByText(/1995-2014 mean/i)).toBeVisible();
    expect(screen.getByText("52.0000°, 4.0000°")).toBeVisible();
    expect(screen.getByText("12.346 km")).toBeVisible();
    expect(screen.getByText("1°")).toBeVisible();
    expect(screen.getByText("ar6-regional-projection-v1")).toBeVisible();
    expect(screen.getByText(RELEASE_ID)).toBeVisible();
    expect(screen.getByRole("link", { name: /ipcc ar6 regional sea level projections/i })).toHaveAttribute(
      "href", "https://doi.org/10.5281/zenodo.6382554",
    );
    expect(screen.getByRole("link", { name: /creative commons attribution 4\.0/i })).toHaveAttribute(
      "href", "https://creativecommons.org/licenses/by/4.0/",
    );
    expect(screen.getByText(/reports regional relative sea-level projection/i)).toBeVisible();
    expect(screen.getByText(/not from map colour/i)).toBeVisible();
    expect(screen.getByText(/not an engineering assessment, structural survey, legal determination/i)).toBeVisible();
    expect(screen.getByText(/insurance evaluation, mortgage guidance, or financial advice/i)).toBeVisible();
  });

  it("distinguishes both DataUnavailable reasons without substitution or zero meaning", () => {
    const tooDistant = accepted("DataUnavailable");
    const { rerender } = renderPanel({ phase: "result", release, operationToken: 2, accepted: tooDistant });
    expect(screen.getByText(/100\.001 km away, beyond the inclusive 100 km limit/i)).toBeVisible();
    expect(screen.getByText(/no other scenario, year, dataset, source-grid location, or value was substituted/i)).toBeVisible();

    const nodataResult: Extract<AssessmentResult, { resultState: "DataUnavailable" }> = Object.freeze({
      ...identity,
      resultState: "DataUnavailable" as const,
      reason: "source-value-nodata" as const,
      source: Object.freeze({ locationId: 42, latitude: 52, longitude: 4, distanceKilometres: 12 }),
    });
    const nodata: AcceptedProjection = Object.freeze({
      ...tooDistant,
      result: nodataResult,
    });
    rerender(<ProjectionPanel state={{ phase: "result", release, operationToken: 3, accepted: nodata }} methodology={methodology()} {...callbacks()} />);
    expect(screen.getByText(/at least one required source quantile/i)).toBeVisible();
    expect(screen.getByText(/does not mean zero change/i)).toBeVisible();
  });

  it("keeps scope outcomes useful without a no-hazard implication or application failure", () => {
    const { rerender } = renderPanel({ phase: "result", release, operationToken: 2, accepted: accepted("OutOfScope") });
    expect(screen.getByText(/does not imply absence of coastal or climate hazards/i)).toBeVisible();
    rerender(<ProjectionPanel state={{ phase: "result", release, operationToken: 3, accepted: accepted("UnsupportedGeography") }} methodology={methodology()} {...callbacks()} />);
    expect(screen.getByText(/normal domain outcome, not an application error/i)).toBeVisible();
  });
});

describe("projection panel controls and fail-closed presentation", () => {
  it("offers exactly three scenarios and horizons and emits one immutable selection identity", async () => {
    const handlers = callbacks();
    const current = selection();
    renderPanel({ phase: "result", release, operationToken: 2, accepted: { ...accepted(), selection: current } }, methodology(), handlers);
    const user = userEvent.setup();
    const scenarioGroup = screen.getByRole("group", { name: /emissions scenario/i });
    const horizonGroup = screen.getByRole("group", { name: /absolute horizon/i });
    expect(within(scenarioGroup).getAllByRole("radio")).toHaveLength(3);
    expect(within(horizonGroup).getAllByRole("radio")).toHaveLength(3);

    await user.click(screen.getByRole("radio", { name: /lower-emissions scenario.*ssp1-26/i }));
    expect(handlers.onSelectionChange).toHaveBeenLastCalledWith({
      ...current,
      scenario: "ssp1-26",
    });
    expect(vi.mocked(handlers.onSelectionChange).mock.calls[0][0].location).toBe(current.location);

    await user.click(screen.getByRole("radio", { name: "2100" }));
    expect(handlers.onSelectionChange).toHaveBeenLastCalledWith({
      ...current,
      horizon: 2100,
    });
  });

  it("routes enabled actions and disables actions that cannot be honest in the current phase", async () => {
    const handlers = callbacks();
    const user = userEvent.setup();
    const { rerender } = renderPanel({ phase: "result", release, operationToken: 2, accepted: accepted() }, methodology(), handlers);
    expect(screen.getByRole("button", { name: /retry/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reset/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /share/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /methodology/i })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: /share/i }));
    await user.click(screen.getByRole("button", { name: /methodology/i }));
    expect(handlers.onShare).toHaveBeenCalledOnce();
    expect(handlers.onOpenMethodology).toHaveBeenCalledOnce();

    rerender(<ProjectionPanel state={failureState("technical-error")} methodology={methodology()} {...handlers} />);
    expect(screen.getByRole("button", { name: /retry/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /share/i })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(handlers.onRetry).toHaveBeenCalledOnce();
  });

  it("keeps technical failures outside the four-outcome domain", () => {
    const { container } = renderPanel(failureState("technical-error"));
    expect(screen.getByRole("alert")).toHaveTextContent("Technical failure");
    expect(screen.getByRole("alert")).toHaveTextContent("not a DataUnavailable scientific outcome");
    expect(container.querySelector("[data-outcome]")).toHaveAttribute("data-outcome", "ProjectionAvailable");
    expect(screen.getByText(/previous accepted result — separate from the failed operation/i)).toBeVisible();
  });

  it.each([
    ["synthetic-fixture", /synthetic fixture — demonstration only/i],
    ["private-engineering", /private engineering candidate — local validation only/i],
    ["public-promoted", /public promoted release — approved immutable release artifacts/i],
  ] as const)("discloses the %s release disposition", (disposition, disclosure) => {
    renderPanel({ phase: "result", release, operationToken: 2, accepted: accepted() }, methodology(disposition));
    expect(screen.getByText(disclosure)).toBeVisible();
  });

  it("hides scientific values until verified matching methodology is available", () => {
    const state: ProjectionState = { phase: "result", release, operationToken: 2, accepted: accepted() };
    const { rerender } = renderPanel(state, null);
    expect(screen.getByText(/verifying methodology before showing/i)).toHaveAttribute("role", "status");
    expect(screen.queryByText(/0\.247 m/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /share/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /methodology/i })).toBeDisabled();

    rerender(<ProjectionPanel state={state} methodology={{ ...methodology(), dataReleaseId: "other-release" }} {...callbacks()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/does not match this result/i);
    expect(screen.queryByText(/0\.247 m/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /methodology/i })).toBeDisabled();
  });

  it("contains no obsolete binary state or affirmative risk wording", () => {
    const { container } = renderPanel({ phase: "result", release, operationToken: 2, accepted: accepted() });
    const rendered = container.textContent ?? "";
    for (const prohibited of ["Expo" + "sed", "Not" + "Exposed", "sa" + "fe", "risk detected"]) {
      expect(rendered.toLowerCase()).not.toContain(prohibited.toLowerCase());
    }
  });
});
