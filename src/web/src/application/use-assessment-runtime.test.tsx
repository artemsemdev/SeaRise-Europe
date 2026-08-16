import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { CogAnalysisArtifactReader } from "../data/cog-analysis-reader";
import { StaticGeographyClassifier } from "../data/geography-classifier";
import type { ReleaseMethodology } from "../data/methodology-repository";
import {
  createBootingProjectionState,
  projectionReducer,
  projectionReleaseIdentity,
  selectionKey,
  type ProjectionState,
} from "../domain/projection-state";
import { AssessmentEngine, type AssessmentResult } from "../domain/scientific-lookup";
import {
  ReleaseContext,
  TechnicalFailure,
  type Selection,
} from "../domain/release";
import { fixtureReleaseContext } from "../test/release-fixture";
import { createSearchQueryOperation } from "../search/lifecycle";
import { AssessmentController } from "./assessment-controller";
import type {
  RuntimeCapabilityInteractionV1,
  RuntimeCapabilityPort,
} from "./runtime-capability";
import {
  createBrowserRuntime,
  type AssessmentControllerPort,
  type BrowserRuntimeFactory,
  type BrowserRuntimeScope,
} from "./browser-runtime";
import { useAssessmentRuntime } from "./use-assessment-runtime";

let firstContext: ReleaseContext;
let secondContext: ReleaseContext;

beforeAll(async () => {
  firstContext = await fixtureReleaseContext();
  const manifest = structuredClone(firstContext.manifest);
  (manifest as { dataReleaseId: string }).dataReleaseId =
    "searise-europe-v1.0.1-20260816-aaaaaaaaaaaa";
  secondContext = new ReleaseContext({
    manifest,
    manifestUrl: firstContext.manifestUrl.replace(firstContext.dataReleaseId, manifest.dataReleaseId),
    disposition: firstContext.disposition,
    artifacts: { ...firstContext.artifacts },
    datasets: { ...firstContext.datasets },
  });
});

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

function readyState(context: ReleaseContext): ProjectionState {
  return projectionReducer(createBootingProjectionState(context.dataReleaseId), {
    type: "release-ready",
    operationToken: 0,
    release: projectionReleaseIdentity(context),
  });
}

class TestController implements AssessmentControllerPort {
  readonly select = vi.fn(async () => undefined);
  readonly retry = vi.fn(async () => true);
  readonly reset = vi.fn(() => undefined);
  readonly handleSearchLifecycle = vi.fn(() => undefined);
  readonly cancelSearch = vi.fn(() => undefined);
  readonly dispose = vi.fn(() => undefined);
  #snapshot: ProjectionState;
  readonly #listeners = new Set<() => void>();

  constructor(context: ReleaseContext) {
    this.#snapshot = readyState(context);
  }

  readonly getSnapshot = (): ProjectionState => this.#snapshot;
  readonly subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  get listenerCount(): number {
    return this.#listeners.size;
  }

  publish(snapshot: ProjectionState): void {
    this.#snapshot = snapshot;
    for (const listener of this.#listeners) listener();
  }
}

function methodology(context: ReleaseContext): ReleaseMethodology {
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    methodologyVersion: context.methodologyVersion,
    disposition: context.disposition,
  }) as ReleaseMethodology;
}

interface RuntimeRecord {
  readonly scope: BrowserRuntimeScope;
  readonly controller: TestController;
  readonly methodology: Deferred<ReleaseMethodology>;
  readonly signals: AbortSignal[];
}

function runtimeRecord(
  context: ReleaseContext,
  capability?: RuntimeCapabilityPort,
): RuntimeRecord {
  const controller = new TestController(context);
  const pending = deferred<ReleaseMethodology>();
  const signals: AbortSignal[] = [];
  return {
    controller,
    methodology: pending,
    signals,
    scope: {
      context,
      controller,
      methodology: {
        load: (_context, signal) => {
          signals.push(signal);
          return pending.promise;
        },
      },
      ...(capability ? { capability } : {}),
    },
  };
}

function selected(context: ReleaseContext): Selection {
  return {
    dataReleaseId: context.dataReleaseId,
    scenario: "ssp2-45",
    horizon: 2050,
    location: {
      kind: "coordinate",
      coordinates: { latitude: 51.9, longitude: 4.5 },
    },
  };
}

function outOfScopeResult(context: ReleaseContext, selection: Selection): AssessmentResult {
  const dataset = context.dataset(selection.scenario, selection.horizon);
  return {
    dataReleaseId: context.dataReleaseId,
    methodologyVersion: context.methodologyVersion,
    scenario: selection.scenario,
    horizon: selection.horizon,
    analysisArtifactId: dataset.analysisArtifactId,
    analysisArtifactSha256: context.artifact(dataset.analysisArtifactId).sha256,
    visualArtifactId: dataset.visualArtifactId,
    visualArtifactSha256: context.artifact(dataset.visualArtifactId).sha256,
    visualArtifactUrl: context.artifact(dataset.visualArtifactId).url,
    resultState: "OutOfScope",
    reason: "outside-coastal-scope",
  };
}

describe("static browser runtime adapter", () => {
  it("wires the production runtime from the real static scientific classes through the verified router", async () => {
    const close = vi.fn();
    const runtime = await createBrowserRuntime(firstContext, new AbortController().signal, {
      resourceRouter: {
        artifactTransport: vi.fn(),
        cogRangeTransport: {
          validateDelivery: vi.fn(async () => undefined),
          readExpandedRange: vi.fn(async () => new ArrayBuffer(0)),
        },
        close,
      },
    });

    expect(runtime.context).toBe(firstContext);
    expect(runtime.geography).toBeInstanceOf(StaticGeographyClassifier);
    expect(runtime.analysis).toBeInstanceOf(CogAnalysisArtifactReader);
    expect(runtime.assessment).toBeInstanceOf(AssessmentEngine);
    expect(runtime.controller).toBeInstanceOf(AssessmentController);
    expect(runtime.controller.getSnapshot()).toMatchObject({
      phase: "ready",
      release: { dataReleaseId: firstContext.dataReleaseId },
    });
    runtime.dispose();
    expect(close).toHaveBeenCalledOnce();
  });

  it("classifies a missing release resource as connection-required", async () => {
    const runtime = await createBrowserRuntime(firstContext, new AbortController().signal, {
      resourceRouter: {
        artifactTransport: vi.fn(async () => {
          throw new TechnicalFailure({
            kind: "technical-error",
            code: "FetchFailed",
            message: "COG delivery metadata for projection-ssp2-45-2050-cog is unavailable.",
            recoverable: true,
          });
        }),
        cogRangeTransport: {
          validateDelivery: vi.fn(async () => undefined),
          readExpandedRange: vi.fn(async () => new ArrayBuffer(0)),
        },
        close: vi.fn(),
      },
    });

    await runtime.controller.select(selected(firstContext));

    expect(runtime.controller.getSnapshot()).toMatchObject({
      phase: "connection-required",
      error: { code: "FetchFailed" },
    });
    runtime.dispose();
  });

  it("constructs once per context, keeps snapshots stable, and exposes every controller command", async () => {
    const records: RuntimeRecord[] = [];
    const factory: BrowserRuntimeFactory = vi.fn((context) => {
      const record = runtimeRecord(context);
      records.push(record);
      return record.scope;
    });
    const { result, rerender, unmount } = renderHook(
      ({ context }) => useAssessmentRuntime(context, factory),
      { initialProps: { context: firstContext as ReleaseContext | null } },
    );

    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));
    const stableSnapshot = result.current.projection;
    const stableCommands = {
      select: result.current.select,
      retry: result.current.retry,
      reset: result.current.reset,
      handleSearchLifecycle: result.current.handleSearchLifecycle,
      cancelSearch: result.current.cancelSearch,
    };
    rerender({ context: firstContext });

    expect(factory).toHaveBeenCalledOnce();
    expect(result.current.projection).toBe(stableSnapshot);
    expect(result.current.select).toBe(stableCommands.select);
    expect(result.current.retry).toBe(stableCommands.retry);
    expect(result.current.reset).toBe(stableCommands.reset);
    expect(result.current.handleSearchLifecycle).toBe(stableCommands.handleSearchLifecycle);
    expect(result.current.cancelSearch).toBe(stableCommands.cancelSearch);

    const selection = selected(firstContext);
    await act(async () => {
      await result.current.select(selection);
      expect(await result.current.retry()).toBe(true);
      result.current.handleSearchLifecycle({
        type: "search-started",
        operation: createSearchQueryOperation(firstContext.dataReleaseId, "Athens", 1)!,
      });
      result.current.cancelSearch();
      result.current.reset();
    });
    expect(records[0].controller.select).toHaveBeenCalledWith(selection);
    expect(records[0].controller.retry).toHaveBeenCalledOnce();
    expect(records[0].controller.reset).toHaveBeenCalledOnce();
    expect(records[0].controller.handleSearchLifecycle).toHaveBeenCalledOnce();
    expect(records[0].controller.cancelSearch).toHaveBeenCalledOnce();

    unmount();
    expect(records[0].signals[0].aborted).toBe(true);
    expect(records[0].controller.dispose).toHaveBeenCalledOnce();
    expect(records[0].controller.listenerCount).toBe(0);
    act(() => records[0].controller.publish(readyState(firstContext)));
  });

  it("reconfirms the same assessment interaction after a failed operation retries successfully", async () => {
    const selection = selected(firstContext);
    const interaction: RuntimeCapabilityInteractionV1 = Object.freeze({
      generation: 7,
      subject: Object.freeze({
        kind: "assessment",
        scenario: selection.scenario,
        horizon: selection.horizon,
      }),
    });
    const capability = {
      getSnapshot: vi.fn(() => null),
      subscribe: vi.fn(() => () => undefined),
      beginInteraction: vi.fn(() => interaction),
      confirmInteractionAvailable: vi.fn(async () => undefined),
      retry: vi.fn(async () => undefined),
      requestUpdateAction: vi.fn(async () => undefined),
      dispose: vi.fn(() => undefined),
    } satisfies RuntimeCapabilityPort;
    const record = runtimeRecord(firstContext, capability);
    const factory: BrowserRuntimeFactory = () => record.scope;
    const { result } = renderHook(() => useAssessmentRuntime(firstContext, factory));
    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));

    record.controller.select.mockImplementationOnce(async () => {
      const evaluating = projectionReducer(readyState(firstContext), {
        type: "evaluation-started",
        operationToken: 1,
        selection,
      });
      record.controller.publish(projectionReducer(evaluating, {
        type: "operation-unavailable",
        availability: "connection-required",
        operationToken: 1,
        selectionKey: selectionKey(selection),
        dataReleaseId: firstContext.dataReleaseId,
        error: {
          kind: "technical-error",
          code: "FetchFailed",
          message: "Exact assessment bytes are unavailable.",
          recoverable: true,
        },
      }));
    });
    await act(async () => result.current.select(selection));
    expect(result.current.projection?.phase).toBe("connection-required");
    expect(capability.confirmInteractionAvailable).not.toHaveBeenCalled();

    record.controller.retry.mockImplementationOnce(async () => {
      const evaluating = projectionReducer(readyState(firstContext), {
        type: "evaluation-started",
        operationToken: 2,
        selection,
      });
      record.controller.publish(projectionReducer(evaluating, {
        type: "assessment-completed",
        operationToken: 2,
        selectionKey: selectionKey(selection),
        dataReleaseId: firstContext.dataReleaseId,
        result: outOfScopeResult(firstContext, selection),
      }));
      return true;
    });
    await act(async () => expect(result.current.retry()).resolves.toBe(true));

    expect(capability.beginInteraction).toHaveBeenCalledOnce();
    expect(capability.confirmInteractionAvailable).toHaveBeenCalledOnce();
    expect(capability.confirmInteractionAvailable).toHaveBeenCalledWith(interaction);
  });

  it("replaces and disposes the exact release scope without accepting stale methodology", async () => {
    const records: RuntimeRecord[] = [];
    const factory: BrowserRuntimeFactory = (context) => {
      const record = runtimeRecord(context);
      records.push(record);
      return record.scope;
    };
    const { result, rerender } = renderHook(
      ({ context }) => useAssessmentRuntime(context, factory),
      { initialProps: { context: firstContext as ReleaseContext | null } },
    );
    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));

    rerender({ context: secondContext });
    await waitFor(() => {
      expect(result.current.projection).toMatchObject({
        phase: "ready",
        release: { dataReleaseId: secondContext.dataReleaseId },
      });
    });
    expect(records[0].signals[0].aborted).toBe(true);
    expect(records[0].controller.dispose).toHaveBeenCalledOnce();
    expect(records[0].controller.listenerCount).toBe(0);
    act(() => records[0].controller.publish(readyState(firstContext)));
    expect(result.current.projection).toMatchObject({
      release: { dataReleaseId: secondContext.dataReleaseId },
    });
    expect(result.current.methodology).toEqual({
      phase: "loading",
      dataReleaseId: secondContext.dataReleaseId,
    });

    await act(async () => records[0].methodology.resolve(methodology(firstContext)));
    expect(result.current.methodology.phase).toBe("loading");

    const currentMethodology = methodology(secondContext);
    await act(async () => records[1].methodology.resolve(currentMethodology));
    expect(result.current.methodology).toEqual({
      phase: "ready",
      dataReleaseId: secondContext.dataReleaseId,
      methodology: currentMethodology,
    });
  });

  it("reports methodology delivery failure as technical state, never as an ADR-024 outcome", async () => {
    const record = runtimeRecord(firstContext);
    const factory: BrowserRuntimeFactory = () => record.scope;
    const { result } = renderHook(() => useAssessmentRuntime(firstContext, factory));
    await waitFor(() => expect(result.current.methodology.phase).toBe("loading"));

    await act(async () => record.methodology.reject(new TechnicalFailure({
      kind: "technical-error",
      code: "IntegrityFailed",
      message: "Methodology hash mismatch.",
      recoverable: false,
    })));

    expect(result.current.methodology).toMatchObject({
      phase: "technical-error",
      dataReleaseId: firstContext.dataReleaseId,
      error: { kind: "technical-error", code: "IntegrityFailed" },
    });
    expect(JSON.stringify(result.current.methodology)).not.toContain("resultState");
  });

  it("rejects a methodology object from another immutable release", async () => {
    const record = runtimeRecord(firstContext);
    const factory: BrowserRuntimeFactory = () => record.scope;
    const { result } = renderHook(() => useAssessmentRuntime(firstContext, factory));
    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));

    await act(async () => record.methodology.resolve(methodology(secondContext)));

    expect(result.current.methodology).toMatchObject({
      phase: "technical-error",
      dataReleaseId: firstContext.dataReleaseId,
      error: { kind: "technical-error", code: "ReleaseIdentityMismatch" },
    });
  });

  it("stays idle without constructing a runtime and fails commands explicitly", async () => {
    const factory: BrowserRuntimeFactory = vi.fn();
    const { result } = renderHook(() => useAssessmentRuntime(null, factory));

    expect(result.current.projection).toBeNull();
    expect(result.current.methodology).toEqual({ phase: "idle" });
    expect(factory).not.toHaveBeenCalled();
    await expect(result.current.select(selected(firstContext))).rejects.toThrow("not ready");
    await expect(result.current.retry()).rejects.toThrow("not ready");
    expect(() => result.current.reset()).toThrow("not ready");
  });
});
