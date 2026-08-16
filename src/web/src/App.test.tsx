import { StrictMode } from "react";
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AssessmentControllerPort,
  BrowserRuntimeFactory,
} from "./application/browser-runtime";
import type { ProjectionUrlEnvironment } from "./application/projection-url-controller";
import { LandingPage } from "./App";
import App from "./App";
import type { ReleaseMethodology } from "./data/methodology-repository";
import {
  createBootingProjectionState,
  projectionReducer,
  projectionReleaseIdentity,
  selectionKey,
  visibleAcceptedProjection,
  type ProjectionState,
} from "./domain/projection-state";
import type { SearchLifecycleEvent } from "./domain/projection-search";
import type { AssessmentResult } from "./domain/scientific-lookup";
import {
  ReleaseContext,
  TechnicalFailure,
  type Selection,
} from "./domain/release";
import type { SearchWorkerFactory } from "./search/client";
import type {
  SearchWorkerPort,
  SearchWorkerRequest,
  SearchWorkerResponse,
} from "./search/worker-protocol";
import { fixtureReleaseContext } from "./test/release-fixture";
import type { HorizonYear, ScenarioId } from "./contracts/generated/release-contract";
import { releaseScopeStatus } from "./release-copy";
import { isForbiddenApplicationApiPath } from "./test/application-api-boundary";

vi.mock("./components/map/MapExplorer", () => ({
  default: ({ selection, journeyActive, journeyTarget, journeyMotionSkipToken, onSelection, context }: {
    selection?: Selection;
    journeyActive?: boolean;
    journeyTarget?: { latitude: number; longitude: number };
    journeyMotionSkipToken?: number;
    onSelection: (selection: Selection) => void;
    context: ReleaseContext;
  }) => (
    <section aria-label="Test map composition">
      <h2>Explore the source grid</h2>
      <div data-testid="map-accepted-selection">
        {selection ? `${selection.scenario}/${selection.horizon}/${selection.location.coordinates.latitude}` : "preview-only"}
      </div>
      <div data-testid="map-journey-active">{journeyActive ? "true" : "false"}</div>
      <div data-testid="map-journey-target">
        {journeyTarget ? `${journeyTarget.latitude}/${journeyTarget.longitude}` : "none"}
      </div>
      <div data-testid="map-motion-skip-token">{journeyMotionSkipToken ?? 0}</div>
      <button type="button" onClick={() => onSelection(Object.freeze({
        dataReleaseId: context.dataReleaseId,
        scenario: selection?.scenario ?? context.defaults.scenario,
        horizon: selection?.horizon ?? context.defaults.horizon,
        location: Object.freeze({
          kind: "coordinate" as const,
          coordinates: Object.freeze({ latitude: 42, longitude: 7 }),
        }),
      }))}>Select test map point</button>
      <button type="button" disabled={!selection} onClick={() => selection && onSelection(Object.freeze({
        ...selection,
        scenario: "ssp5-85" as const,
      }))}>Select test map scenario</button>
    </section>
  ),
}));

let releaseContext: ReleaseContext;
let replacementContext: ReleaseContext;

beforeAll(async () => {
  releaseContext = await fixtureReleaseContext();
  const replacementManifest = structuredClone(releaseContext.manifest);
  (replacementManifest as { dataReleaseId: string }).dataReleaseId =
    "searise-europe-v1.0.1-20260816-aaaaaaaaaaaa";
  replacementContext = new ReleaseContext({
    manifest: replacementManifest,
    manifestUrl: releaseContext.manifestUrl.replace(releaseContext.dataReleaseId, replacementManifest.dataReleaseId),
    disposition: releaseContext.disposition,
    artifacts: { ...releaseContext.artifacts },
    datasets: { ...releaseContext.datasets },
  });
});

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(fixture), { headers: { "content-type": "application/json" } }),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

afterAll(() => vi.restoreAllMocks());

function methodology(context: ReleaseContext): ReleaseMethodology {
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    disposition: context.disposition,
    methodologyVersion: context.methodologyVersion,
    baseline: "1995-2014 mean",
    likelyRange: Object.freeze({
      confidence: "medium",
      lowerQuantile: 0.167,
      medianQuantile: 0.5,
      upperQuantile: 0.833,
    }),
    lookup: Object.freeze({
      operator: "nearest-source-grid-location",
      nativeResolutionDegrees: 1,
      maximumDistanceKilometres: 100,
      distanceLimitInclusive: true,
      interpolation: "prohibited",
      extrapolation: "prohibited",
      nodataSubstitution: "prohibited",
      tideGaugeFallback: "prohibited",
    }),
    resultStates: Object.freeze([
      "ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography",
    ] as const),
    limitations: Object.freeze([
      "Reports regional relative sea-level projection, not an absolute water level.",
      "Does not model flooding, terrain exposure, probability, or property risk.",
    ]),
    prohibitedClaims: Object.freeze([
      "flooding", "inundation", "terrain-exposure", "flood-probability", "property-risk",
    ] as const),
    decision: Object.freeze({ id: "ADR-024", href: "https://example.test/ADR-024" }),
    source: Object.freeze({
      title: "IPCC AR6 Sea Level Projections",
      attributionText: "IPCC AR6 Sea Level Projections, CC BY 4.0.",
      sourceUrl: "https://doi.org/10.5281/zenodo.6382554",
      licence: Object.freeze({
        spdxId: "CC-BY-4.0",
        name: "Creative Commons Attribution 4.0 International",
        url: "https://creativecommons.org/licenses/by/4.0/",
      }),
    }),
  });
}

function outcome(context: ReleaseContext, selection: Selection): AssessmentResult {
  const dataset = context.dataset(selection.scenario, selection.horizon);
  const analysis = context.artifact(dataset.analysisArtifactId);
  const visual = context.artifact(dataset.visualArtifactId);
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    methodologyVersion: context.methodologyVersion,
    scenario: selection.scenario,
    horizon: selection.horizon,
    analysisArtifactId: analysis.artifactId,
    analysisArtifactSha256: analysis.sha256,
    visualArtifactId: visual.artifactId,
    visualArtifactSha256: visual.sha256,
    visualArtifactUrl: visual.url,
    resultState: "OutOfScope",
    reason: "outside-coastal-scope",
  });
}

class TestController implements AssessmentControllerPort {
  readonly select = vi.fn(async (selection: Selection) => {
    const operationToken = ++this.#operationToken;
    const previous = visibleAcceptedProjection(this.#state);
    this.#publish(projectionReducer(this.#state, {
      type: previous ? "update-started" : "evaluation-started",
      operationToken,
      selection,
    }));
    if (this.deferNextSelection) {
      this.deferNextSelection = false;
      await new Promise<void>((resolve, reject) => {
        this.#deferred = { selection, operationToken, resolve, reject };
      });
      return;
    }
    if (this.#nextAssessmentError) {
      const error = this.#nextAssessmentError;
      this.#nextAssessmentError = null;
      this.#publish(projectionReducer(this.#state, {
        type: "operation-failed",
        operationToken,
        selectionKey: selectionKey(selection),
        dataReleaseId: selection.dataReleaseId,
        error,
      }));
      return;
    }
    this.#complete(selection, operationToken);
  });
  readonly retry = vi.fn(async () => false);
  readonly reset = vi.fn(() => {
    this.#publish(projectionReducer(this.#state, {
      type: "reset",
      operationToken: ++this.#operationToken,
      dataReleaseId: this.context.dataReleaseId,
    }));
  });
  readonly handleSearchLifecycle = vi.fn((event: SearchLifecycleEvent) => {
    this.#publish(projectionReducer(this.#state, event));
  });
  readonly cancelSearch = vi.fn(() => {
    if (this.#state.phase !== "searching") return;
    this.#publish(projectionReducer(this.#state, {
      type: "search-cancelled",
      searchToken: this.#state.operation.searchToken,
      searchGeneration: this.#state.operation.searchGeneration,
      queryKey: this.#state.operation.queryKey,
      dataReleaseId: this.#state.operation.dataReleaseId,
    }));
  });
  readonly dispose = vi.fn(() => undefined);
  readonly context: ReleaseContext;
  deferNextSelection = false;
  #state: ProjectionState;
  #operationToken = 0;
  #nextAssessmentError: TechnicalFailure["detail"] | null = null;
  #deferred: {
    selection: Selection;
    operationToken: number;
    resolve: () => void;
    reject: (error: unknown) => void;
  } | null = null;
  readonly #listeners = new Set<() => void>();

  constructor(context: ReleaseContext, initiallyBooting = false) {
    this.context = context;
    this.#state = createBootingProjectionState(context.dataReleaseId);
    if (!initiallyBooting) this.markReady();
  }

  readonly getSnapshot = (): ProjectionState => this.#state;
  readonly subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  markReady(): void {
    this.#publish(projectionReducer(this.#state, {
      type: "release-ready",
      operationToken: this.#state.operationToken,
      release: projectionReleaseIdentity(this.context),
    }));
  }

  resolveDeferred(): void {
    const deferred = this.#deferred;
    if (!deferred) throw new Error("No deferred selection.");
    this.#deferred = null;
    this.#complete(deferred.selection, deferred.operationToken);
    deferred.resolve();
  }

  failDeferredAssessment(
    error: TechnicalFailure["detail"],
    availability?: "offline" | "connection-required",
  ): void {
    const deferred = this.#deferred;
    if (!deferred) throw new Error("No deferred selection.");
    this.#deferred = null;
    const guard = {
      operationToken: deferred.operationToken,
      selectionKey: selectionKey(deferred.selection),
      dataReleaseId: deferred.selection.dataReleaseId,
    };
    this.#publish(projectionReducer(this.#state, availability
      ? { type: "operation-unavailable", availability, error, ...guard }
      : { type: "operation-failed", error, ...guard }));
    deferred.resolve();
  }

  rejectNextSelection(error: unknown): void {
    this.select.mockImplementationOnce(async () => Promise.reject(error));
  }

  failNextAssessment(error: TechnicalFailure["detail"]): void {
    this.#nextAssessmentError = error;
  }

  #complete(selection: Selection, operationToken: number): void {
    const active = this.#state.phase === "evaluating" || this.#state.phase === "updating"
      ? this.#state.operation
      : null;
    this.#publish(projectionReducer(this.#state, {
      type: "assessment-completed",
      operationToken,
      selectionKey: selectionKey(selection),
      dataReleaseId: selection.dataReleaseId,
      result: outcome(this.context, selection),
    }));
    if (!active) throw new Error("Selection completion had no active operation.");
  }

  #publish(next: ProjectionState): void {
    if (next === this.#state) return;
    this.#state = next;
    for (const listener of [...this.#listeners]) listener();
  }
}

interface RuntimeRecord {
  readonly context: ReleaseContext;
  readonly controller: TestController;
}

function runtimeFactory(options: {
  methodologyFailure?: boolean;
  initiallyBooting?: boolean;
} = {}): {
  readonly factory: BrowserRuntimeFactory;
  readonly records: RuntimeRecord[];
} {
  const records: RuntimeRecord[] = [];
  return {
    records,
    factory: (context) => {
      const controller = new TestController(context, options.initiallyBooting);
      records.push({ context, controller });
      return {
        context,
        controller,
        methodology: {
          load: async () => {
            if (options.methodologyFailure) throw new TechnicalFailure({
              kind: "technical-error",
              code: "IntegrityFailed",
              message: "Methodology hash mismatch.",
              recoverable: false,
            });
            return methodology(context);
          },
        },
      };
    },
  };
}

class TestUrlEnvironment implements ProjectionUrlEnvironment {
  url: URL;
  readonly replacements: URL[] = [];
  readonly listeners = new Set<() => void>();

  constructor(url = "https://app.example/") {
    this.url = new URL(url);
  }

  readonly currentUrl = (): URL => new URL(this.url);
  readonly replaceUrl = (url: URL): void => {
    this.url = new URL(url);
    this.replacements.push(new URL(url));
  };
  readonly subscribePopState = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  pop(url: string): void {
    this.url = new URL(url);
    for (const listener of [...this.listeners]) listener();
  }
}

const SETTLEMENT = Object.freeze({
  placeId: "geonames:2950159",
  displayName: "Fixturehafen",
  searchNames: Object.freeze(["Fixturehafen"]),
  countryCode: "DE",
  admin1Name: "Hamburg",
  population: 1000,
  featureCode: "PPL",
  distanceToCoastMeters: 250,
  isCoastal: true,
  latitude: 53.55,
  longitude: 9.9937,
});

class TestSearchWorker implements SearchWorkerPort {
  onmessage: ((event: MessageEvent<SearchWorkerResponse>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  readonly requests: SearchWorkerRequest[] = [];
  readonly terminate = vi.fn();

  postMessage(message: SearchWorkerRequest): void {
    this.requests.push(message);
    if (message.kind === "terminate") return;
    const response: SearchWorkerResponse = message.kind === "query"
      ? {
          kind: "results",
          token: message.token,
          results: [{ record: SETTLEMENT, matchTier: 0, editDistance: 0, shardId: "europe-core" }],
          durationMilliseconds: 1,
          readyShards: ["europe-core", "europe-coastal"],
        }
      : {
          kind: "ready",
          token: message.token,
          shardId: message.kind === "initialize" ? "europe-core" : "europe-coastal",
          runtimeVersion: "settlement-browser-worker-v2",
          durationMilliseconds: 1,
        };
    queueMicrotask(() => this.onmessage?.({ data: response } as MessageEvent<SearchWorkerResponse>));
  }
}

function searchFactory(records: TestSearchWorker[] = []): SearchWorkerFactory {
  return () => {
    const worker = new TestSearchWorker();
    records.push(worker);
    return worker;
  };
}

function ready(context = releaseContext) {
  return { phase: "ready" as const, context };
}

function urlFor(
  context = releaseContext,
  scenario: ScenarioId = context.defaults.scenario,
  horizon: HorizonYear = context.defaults.horizon,
): string {
  return `https://app.example/?release=${context.dataReleaseId}&scenario=${scenario}&horizon=${horizon}&lat=51.9&lon=4.5`;
}

async function waitForRuntime(records: RuntimeRecord[]): Promise<TestController> {
  await waitFor(() => expect(records.length).toBeGreaterThan(0));
  await waitFor(() => expect(screen.getByRole("button", { name: /select test map point/i })).toBeEnabled());
  return records.at(-1)!.controller;
}

describe("production static application composition", () => {
  it("matches only removed application API roots, not immutable release configuration", () => {
    const assessRoot = "/ass" + "ess";
    const geocodeRoot = "/geo" + "code";
    const configRoot = "/con" + "fig";
    for (const pathname of [
      assessRoot,
      `${assessRoot}/point`,
      geocodeRoot.toUpperCase(),
      `${geocodeRoot}/search`,
      configRoot,
      `${configRoot}/runtime.json`,
    ]) {
      expect(isForbiddenApplicationApiPath(pathname), pathname).toBe(true);
    }
    for (const pathname of [
      "/assessment",
      "/geocoded-place",
      "/configuration",
      `/releases/${releaseContext.dataReleaseId}${configRoot}/methodology.json`,
      `/releases/${releaseContext.dataReleaseId}${configRoot}/source-attribution.json`,
    ]) {
      expect(isForbiddenApplicationApiPath(pathname), pathname).toBe(false);
    }
  });

  it("renders the shell and enables local search only after the exact runtime scope is ready", async () => {
    const runtime = runtimeFactory();
    render(<App runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);

    expect(screen.getByRole("heading", { level: 1, name: /take me there/i })).toBeVisible();
    expect(screen.getByText(/synthetic fixture · illustrative only/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /methodology and sources/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
    expect(await screen.findByText(/release contract ready · 9 exact combinations/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("combobox", { name: /find a city/i })).toBeEnabled());
    expect(document.querySelector(".flight-scene")).toBeInTheDocument();
    expect(document.querySelector("[data-flight-phase='idle']")).toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(2);
    expect(document.querySelector(".selection-status")).toHaveAttribute("aria-live", "polite");
    expect(document.querySelector(".search-shell .status")).toHaveAttribute("aria-live", "polite");
  });

  it("binds landing release disclosure to verified bootstrap disposition", () => {
    expect(releaseScopeStatus({ phase: "loading", attempt: 0 })).toEqual({
      title: "Release validation pending",
      detail: "Scientific release status appears only after the pinned manifest is verified.",
    });
    expect(releaseScopeStatus(ready())).toEqual({
      title: "Synthetic fixture",
      detail: "Demonstration data only; no public scientific release is claimed.",
    });
    for (const [disposition, title, detail] of [
      ["private-engineering", "Private engineering candidate", /local validation only/i],
      ["public-promoted", "Public promoted release", /approved immutable release artifacts/i],
    ] as const) {
      const context = new ReleaseContext({
        manifest: releaseContext.manifest,
        manifestUrl: releaseContext.manifestUrl,
        disposition,
        artifacts: { ...releaseContext.artifacts },
        datasets: { ...releaseContext.datasets },
      });
      const copy = releaseScopeStatus(ready(context));
      expect(copy.title).toBe(title);
      expect(copy.detail).toMatch(detail);
    }
  });

  it("hands a search result to one deeply frozen selection command and never sends query text to a server", async () => {
    const runtime = runtimeFactory();
    const workers: TestSearchWorker[] = [];
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory(workers)} />);
    const controller = await waitForRuntime(runtime.records);

    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Fixture");
    await user.click(await screen.findByRole("option", { name: /Fixturehafen/i }));

    expect(controller.select).toHaveBeenCalledOnce();
    const selection = controller.select.mock.calls[0][0];
    expect(selection).toMatchObject({
      dataReleaseId: releaseContext.dataReleaseId,
      scenario: "ssp2-45",
      horizon: 2050,
      location: {
        kind: "settlement",
        placeId: SETTLEMENT.placeId,
        coordinates: { latitude: SETTLEMENT.latitude, longitude: SETTLEMENT.longitude },
      },
    });
    expect(Object.isFrozen(selection)).toBe(true);
    expect(Object.isFrozen(selection.location)).toBe(true);
    expect(Object.isFrozen(selection.location.coordinates)).toBe(true);
    expect(JSON.stringify(workers.flatMap((worker) => worker.requests))).toContain("Fixture");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("moves from idle through a truthful Flight transition before revealing the first result", async () => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    expect(document.querySelector("[data-flight-phase='idle'] .flight-search")).toBeInTheDocument();

    controller.deferNextSelection = true;
    await user.click(await screen.findByRole("button", { name: /select test map point/i }));
    expect(document.querySelector("[data-flight-phase='transition'] .flight-scene")).toBeInTheDocument();
    expect(screen.getByText(/flying to the selected point/i)).toBeVisible();
    expect(document.querySelector("[data-outcome]")).toBeNull();

    await user.click(screen.getByRole("button", { name: /skip motion/i }));
    expect(document.querySelector("[data-flight-phase='transition']")).toBeInTheDocument();
    expect(screen.getByTestId("map-motion-skip-token")).toHaveTextContent("1");
    expect(screen.getByText(/camera motion skipped/i)).toBeVisible();
    expect(document.querySelector("[data-outcome]")).toBeNull();

    act(() => controller.resolveDeferred());
    await waitFor(() => expect(document.querySelector("[data-flight-phase='result'] .flight-result")).toBeInTheDocument());
    expect(document.querySelector("[data-outcome]")).toHaveAttribute("data-outcome", "OutOfScope");
    expect(screen.queryByText(/flying to the selected point/i)).not.toBeInTheDocument();
  });

  it("moves focus from a selected search result to progress, result, and reset search", async () => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    const input = screen.getByRole("combobox", { name: /find a city/i });

    controller.deferNextSelection = true;
    await user.type(input, "Fixture");
    await user.click(await screen.findByRole("option", { name: /Fixturehafen/i }));
    await waitFor(() => expect(screen.getByText(/selected place accepted/i)).toHaveFocus());

    act(() => controller.resolveDeferred());
    await waitFor(() => expect(screen.getByRole("heading", { name: /outside the coastal analysis area/i })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: /reset selection/i }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /find a city/i })).toHaveFocus());
  });

  it.each([
    ["technical-error", { kind: "technical-error", code: "FetchFailed", message: "Temporary fetch failure.", recoverable: true }, undefined],
    ["integrity-error", { kind: "technical-error", code: "IntegrityFailed", message: "Selected bytes failed integrity verification.", recoverable: false }, undefined],
    ["offline", { kind: "technical-error", code: "FetchFailed", message: "Selected bytes are not cached.", recoverable: true }, "offline"],
    ["connection-required", { kind: "technical-error", code: "FetchFailed", message: "A connection is required.", recoverable: true }, "connection-required"],
  ] as const)("moves focus from the selected-place transition to a visible %s alert", async (
    phase,
    error,
    availability,
  ) => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    const input = screen.getByRole("combobox", { name: /find a city/i });

    controller.deferNextSelection = true;
    await user.type(input, "Fixture");
    await user.click(await screen.findByRole("option", { name: /Fixturehafen/i }));
    await waitFor(() => expect(screen.getByText(/selected place accepted/i)).toHaveFocus());

    act(() => controller.failDeferredAssessment(error, availability));
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(alert).toHaveFocus());
    expect(document.querySelector(".projection-panel")).toHaveAttribute("data-phase", phase);
    expect(document.activeElement).not.toBe(document.body);
  });

  it("keeps the accepted result on the map while one new command is pending, then swaps atomically", async () => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    const environment = new TestUrlEnvironment(urlFor());
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    await screen.findByText(/outside the coastal analysis area/i);
    expect(await screen.findByTestId("map-accepted-selection")).toHaveTextContent("ssp2-45/2050/51.9");

    controller.deferNextSelection = true;
    await user.click(screen.getByLabelText(/Higher-emissions scenario/i));
    expect(document.querySelector("[data-flight-phase='result']")).toBeInTheDocument();
    expect(document.querySelector(".projection-panel[data-phase='updating']")).toBeInTheDocument();
    expect(screen.queryByText(/flying to the selected point/i)).not.toBeInTheDocument();
    expect(document.querySelector(".flight-progress")).not.toBeInTheDocument();
    expect(screen.getByTestId("map-journey-active")).toHaveTextContent("false");
    expect(screen.getByTestId("map-journey-target")).toHaveTextContent("none");
    expect(screen.getByText(/previous accepted result.*new selection is being checked/i)).toBeVisible();
    expect(screen.getByTestId("map-accepted-selection")).toHaveTextContent("ssp2-45/2050/51.9");
    expect(controller.select).toHaveBeenCalledTimes(2);

    act(() => controller.resolveDeferred());
    await waitFor(() => expect(screen.getByTestId("map-accepted-selection")).toHaveTextContent("ssp5-85/2050/51.9"));
    expect(document.querySelector("[data-flight-phase='result']")).toBeInTheDocument();
  });

  it("announces a terminal assessment failure without implying that evaluation is still running", async () => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    controller.failNextAssessment({
      kind: "technical-error",
      code: "FetchFailed",
      message: "Selected immutable bytes are temporarily unavailable.",
      recoverable: true,
    });

    await user.click(await screen.findByRole("button", { name: /select test map point/i }));

    const status = document.querySelector(".selection-status");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /technical failure.*not a DataUnavailable scientific outcome/i,
    );
    expect(status).toHaveTextContent(
      "The selected operation ended in a technical failure. No scientific outcome was produced.",
    );
    expect(status).not.toHaveTextContent(/being checked/i);
    expect(document.querySelector("[data-outcome]")).toBeNull();
  });

  it("announces a failed update separately while retaining the previous scientific outcome", async () => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment(urlFor())} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    expect(await screen.findByText(/outside the coastal analysis area/i)).toBeVisible();
    expect(document.querySelector(".selection-status")).toHaveTextContent(
      "The accepted projection is shown in the result panel.",
    );
    controller.failNextAssessment({
      kind: "technical-error",
      code: "FetchFailed",
      message: "Selected immutable bytes are temporarily unavailable.",
      recoverable: true,
    });

    await user.click(screen.getByLabelText("2100"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /technical failure.*not a DataUnavailable scientific outcome/i,
    );
    expect(document.querySelector(".selection-status")).toHaveTextContent(
      "The previous accepted projection remains in the result panel; the latest operation ended in a technical failure.",
    );
    expect(document.querySelector(".selection-status")).not.toHaveTextContent(/being checked/i);
    expect(document.querySelector("[data-outcome]")).toHaveAttribute("data-outcome", "OutOfScope");
    expect(screen.queryByText(/model data unavailable for this point/i)).not.toBeInTheDocument();
  });

  it("routes panel, map, retry, reset, share, and methodology controls through their owned commands", async () => {
    const runtime = runtimeFactory();
    const environment = new TestUrlEnvironment(urlFor());
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    await screen.findByText(/outside the coastal analysis area/i);

    const methodologyButton = screen.getByRole("button", { name: /methodology and sources/i });
    methodologyButton.focus();
    await user.click(methodologyButton);
    expect(await screen.findByRole("dialog", { name: /methodology and data/i })).toBeVisible();
    await user.click(screen.getByRole("button", { name: /close methodology/i }));
    await waitFor(() => expect(methodologyButton).toHaveFocus());

    await user.click(screen.getByRole("button", { name: /share accepted result/i }));
    expect(screen.getByText(/share link is ready in the browser address bar/i)).toBeVisible();
    expect(environment.url.searchParams.get("release")).toBe(releaseContext.dataReleaseId);

    await user.click(await screen.findByRole("button", { name: /select test map point/i }));
    expect(screen.queryByRole("listbox", { name: /settlement results/i })).not.toBeInTheDocument();
    expect(controller.select).toHaveBeenLastCalledWith(expect.objectContaining({
      location: { kind: "coordinate", coordinates: { latitude: 42, longitude: 7 } },
    }));
    await waitFor(() => expect(screen.getByTestId("map-accepted-selection")).toHaveTextContent("ssp2-45/2050/42"));
    await user.click(screen.getByRole("button", { name: /select test map scenario/i }));
    expect(controller.select).toHaveBeenLastCalledWith(expect.objectContaining({ scenario: "ssp5-85" }));
    await waitFor(() => expect(screen.getByTestId("map-accepted-selection")).toHaveTextContent("ssp5-85/2050/42"));

    controller.failNextAssessment({
      kind: "technical-error",
      code: "FetchFailed",
      message: "Selected immutable bytes are temporarily unavailable.",
      recoverable: true,
    });
    await user.click(screen.getByLabelText("2100"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/technical failure.*not a DataUnavailable scientific outcome/i);
    await user.click(screen.getByRole("button", { name: /retry exact selection/i }));
    expect(controller.retry).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: /reset selection/i }));
    expect(controller.cancelSearch).toHaveBeenCalled();
    expect(controller.reset).toHaveBeenCalledOnce();
    expect(environment.url.searchParams.has("release")).toBe(false);
    expect(screen.getByRole("heading", { level: 1, name: /take me there/i })).toBeVisible();
  });

  it("deduplicates only duplicate StrictMode initial delivery and accepts the same later popstate", async () => {
    const runtime = runtimeFactory();
    const environment = new TestUrlEnvironment(urlFor());
    render(
      <StrictMode>
        <LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />
      </StrictMode>,
    );
    const controller = await waitForRuntime(runtime.records);
    await waitFor(() => expect(runtime.records.reduce(
      (count, record) => count + record.controller.select.mock.calls.length,
      0,
    )).toBe(1));

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /reset selection/i }));
    expect(controller.reset).toHaveBeenCalledOnce();
    act(() => environment.pop(urlFor()));
    await waitFor(() => expect(runtime.records.reduce(
      (count, record) => count + record.controller.select.mock.calls.length,
      0,
    )).toBe(2));
  });

  it.each([
    ["empty", "https://app.example/?campaign=kept"],
    ["malformed", "https://app.example/?lat=91&lon=4"],
  ])("invalidates a queued initial URL when %s popstate arrives before runtime readiness", async (_label, nextUrl) => {
    const runtime = runtimeFactory({ initiallyBooting: true });
    const environment = new TestUrlEnvironment(urlFor());
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    await waitFor(() => expect(runtime.records).toHaveLength(1));
    const controller = runtime.records[0].controller;
    expect(controller.select).not.toHaveBeenCalled();

    act(() => environment.pop(nextUrl));
    act(() => controller.markReady());
    await waitFor(() => expect(screen.getByRole("combobox", { name: /find a city/i })).toBeEnabled());

    expect(controller.select).not.toHaveBeenCalled();
    expect(controller.reset).not.toHaveBeenCalled();
    if (_label === "malformed") {
      expect(screen.getByRole("alert")).toHaveTextContent(/share or navigation failed/i);
    } else {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    }
  });

  it("handles URL reload, explicit publication, popstate clear, and invalid URL as technical state", async () => {
    const runtime = runtimeFactory();
    const environment = new TestUrlEnvironment(urlFor(releaseContext, "ssp1-26", 2100));
    const { unmount } = render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    await waitFor(() => expect(controller.select).toHaveBeenCalledWith(expect.objectContaining({ scenario: "ssp1-26", horizon: 2100 })));
    expect(environment.replacements).toHaveLength(0);

    act(() => environment.pop("https://app.example/?campaign=kept"));
    await waitFor(() => expect(controller.reset).toHaveBeenCalledOnce());
    expect(environment.url.searchParams.get("campaign")).toBe("kept");
    unmount();

    const invalid = runtimeFactory();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={invalid.factory} urlEnvironment={new TestUrlEnvironment("https://app.example/?lat=91&lon=4") } searchWorkerFactory={searchFactory()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/share or navigation failed.*technical failure, not a scientific outcome/i);
    expect(screen.queryByText(/model data unavailable/i)).not.toBeInTheDocument();
  });

  it("shows methodology and command failures as technical alerts, never outcomes", async () => {
    const failedMethodology = runtimeFactory({ methodologyFailure: true });
    const first = render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={failedMethodology.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/methodology verification failed.*not a scientific outcome/i);
    first.unmount();

    const failedCommand = runtimeFactory();
    const user = userEvent.setup();
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={failedCommand.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(failedCommand.records);
    controller.rejectNextSelection(new TechnicalFailure({
      kind: "technical-error",
      code: "ReleaseIdentityMismatch",
      message: "Stale release selection.",
      recoverable: false,
    }));
    await user.click(await screen.findByRole("button", { name: /select test map point/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/selection command failed.*not a scientific outcome/i);
  });

  it("isolates replacement releases and ignores stale URL listeners and rejected old commands", async () => {
    const runtime = runtimeFactory();
    const environment = new TestUrlEnvironment(urlFor());
    const { rerender } = render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    await waitForRuntime(runtime.records);
    const staleListener = [...environment.listeners][0];

    environment.url = new URL(urlFor(replacementContext));
    rerender(<LandingPage release={ready(replacementContext)} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    await waitFor(() => expect(runtime.records.at(-1)?.context).toBe(replacementContext));
    const current = runtime.records.at(-1)!.controller;
    await waitFor(() => expect(current.select).toHaveBeenCalledWith(expect.objectContaining({
      dataReleaseId: replacementContext.dataReleaseId,
    })));
    const currentCalls = current.select.mock.calls.length;
    act(() => staleListener());
    expect(current.select).toHaveBeenCalledTimes(currentCalls);
    expect(screen.queryByText(releaseContext.dataReleaseId)).not.toBeInTheDocument();
  });

  it("makes zero application API requests and never publishes raw search text during normal selection", async () => {
    const runtime = runtimeFactory();
    const workers: TestSearchWorker[] = [];
    const user = userEvent.setup();
    render(<App runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory(workers)} />);
    await waitForRuntime(runtime.records);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Private query text");

    const fetchUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(fetchUrls).toHaveLength(1);
    expect(fetchUrls[0]).toContain("manifest.json");
    expect(fetchUrls.join("\n")).not.toMatch(/\/(assess|geocode|config)(?:[/?]|$)/);
    expect(fetchUrls.join("\n")).not.toContain("Private query text");
  });

  it("preserves the separate lazy architecture route", async () => {
    window.history.replaceState({}, "", "/about/architecture/");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: /static-first, release-scoped/i })).toBeVisible();
    expect(screen.getByText(/no application backend, database, tile server/i)).toBeVisible();
  });
});
