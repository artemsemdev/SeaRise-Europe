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

vi.mock("./components/map/MapExplorer", () => ({
  default: ({ selection, onSelection, context }: {
    selection?: Selection;
    onSelection: (selection: Selection) => void;
    context: ReleaseContext;
  }) => (
    <section aria-label="Test map composition">
      <h2>Explore the source grid</h2>
      <output data-testid="map-accepted-selection">
        {selection ? `${selection.scenario}/${selection.horizon}/${selection.location.coordinates.latitude}` : "preview-only"}
      </output>
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
  await waitFor(() => expect(screen.getByRole("combobox", { name: /find a city/i })).toBeEnabled());
  return records.at(-1)!.controller;
}

describe("production static application composition", () => {
  it("renders the shell and enables local search only after the exact runtime scope is ready", async () => {
    const runtime = runtimeFactory();
    render(<App runtimeFactory={runtime.factory} urlEnvironment={new TestUrlEnvironment()} searchWorkerFactory={searchFactory()} />);

    expect(screen.getByRole("heading", { level: 1, name: /take me there/i })).toBeVisible();
    expect(screen.getByText(/synthetic fixture · illustrative only/i)).toBeVisible();
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
    expect(await screen.findByText(/release contract ready · 9 exact combinations/i)).toBeVisible();
    await waitFor(() => expect(screen.getByRole("combobox", { name: /find a city/i })).toBeEnabled());
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

  it("keeps the accepted result on the map while one new command is pending, then swaps atomically", async () => {
    const runtime = runtimeFactory();
    const user = userEvent.setup();
    const environment = new TestUrlEnvironment(urlFor());
    render(<LandingPage release={ready()} retry={vi.fn()} runtimeFactory={runtime.factory} urlEnvironment={environment} searchWorkerFactory={searchFactory()} />);
    const controller = await waitForRuntime(runtime.records);
    await screen.findByText(/outside the coastal analysis area/i);
    await user.click(screen.getByRole("button", { name: /open static visualization/i }));
    expect(await screen.findByTestId("map-accepted-selection")).toHaveTextContent("ssp2-45/2050/51.9");

    controller.deferNextSelection = true;
    await user.click(screen.getByLabelText(/Higher-emissions scenario/i));
    expect(screen.getByText(/previous accepted result.*new selection is being checked/i)).toBeVisible();
    expect(screen.getByTestId("map-accepted-selection")).toHaveTextContent("ssp2-45/2050/51.9");
    expect(controller.select).toHaveBeenCalledTimes(2);

    act(() => controller.resolveDeferred());
    await waitFor(() => expect(screen.getByTestId("map-accepted-selection")).toHaveTextContent("ssp5-85/2050/51.9"));
  });

  it("validates the pinned fixture and reports all nine combinations", async () => {
    render(<App />);
    expect(await screen.findByText(/release contract ready · 9 exact combinations/i)).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({ pathname: expect.stringContaining(`/releases/${fixture.dataReleaseId}/manifest.json`) }),
      expect.objectContaining({ credentials: "omit" }),
    );
  });

  it("bounds manual retries without substituting another release", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 503 })));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /retry pinned release/i }));
    await user.click(await screen.findByRole("button", { name: /retry pinned release/i }));

    expect(await screen.findByText(/retry limit reached/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: /retry pinned release/i })).not.toBeInTheDocument();
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
